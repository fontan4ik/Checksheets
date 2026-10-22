"""Submit exact-number corrections to existing in-scope WB cards once."""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_01854_wb_plan.json"
RUN_PATH = BASE / "feron_01854_wb_execution.json"
READBACK_PATH = BASE / "feron_01854_wb_readback.json"
NUMBER = "ЕАЭС RU С-CN.НА83.В.01854/22"
OLD_SUFFIX = "0185422"
OLD_NUMBER = "ЕАЭС RU C-CN.HA83.B.01854/22"
ISSUE_DATE = "2022-04-11"
EXPIRY_DATE = "2027-04-10"
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def clean_document(item: dict) -> dict:
    return {field: item[field] for field in DOC_FIELDS if field in item}


def char_rows(card: dict, *, doc_only: bool) -> dict[int, tuple[str, str]]:
    rows = {}
    for row in card.get("characteristics") or []:
        char_id = int(row.get("id", -1))
        if (char_id in DOC_CHAR_IDS) == doc_only:
            rows[char_id] = (str(row.get("name", "")),
                             json.dumps(row.get("value"), ensure_ascii=False, sort_keys=True))
    return rows


def save_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def main() -> None:
    if RUN_PATH.exists() or READBACK_PATH.exists():
        raise RuntimeError("WB update was already attempted; reconcile the live cards before any retry")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    updates = plan.get("updates") or []
    if len(updates) != 172 or plan.get("counts", {}).get("wb_cards_to_update") != 172:
        raise RuntimeError("Unexpected WB update target set")
    if plan.get("local_cleanup_allowed") is not False or len(plan.get("excluded") or []) != 16:
        raise RuntimeError("Plan must retain files and exclude all out-of-scope/conflicting-TNVED offers")

    payloads = []
    for item in updates:
        before, payload = item.get("before") or {}, item.get("payload") or {}
        offer = item.get("offer_id", "")
        if (str(before.get("nmID")) != str(item.get("nmID"))
                or str(payload.get("nmID")) != str(item.get("nmID"))
                or before.get("vendorCode") != offer or payload.get("vendorCode") != offer):
            raise RuntimeError("WB exact identity mismatch for " + offer)
        for field in CARD_FIELDS:
            if field in before and payload.get(field) != before[field]:
                raise RuntimeError(f"WB payload changed existing {field} for {offer}")
        old_docs = ((before.get("documents") or {}).get("items") or [])
        new_docs = ((payload.get("documents") or {}).get("items") or [])
        old_rows = [d for d in old_docs if int(d.get("type") or 0) == 1
                    and norm(d.get("number", "")).endswith(OLD_SUFFIX)]
        new_rows = [d for d in new_docs if int(d.get("type") or 0) == 1
                    and d.get("number") == NUMBER]
        if (len(old_rows) != 1 or len(new_rows) != 1 or len(old_docs) != len(new_docs)
                or old_rows[0].get("number") != OLD_NUMBER):
            raise RuntimeError("WB document row was dropped, duplicated, or not corrected for " + offer)
        for index, old in enumerate(old_docs):
            expected = clean_document(old)
            if old is old_rows[0]:
                expected["number"] = NUMBER
            if new_docs[index] != expected:
                raise RuntimeError("WB document data changed beyond the exact number for " + offer)
        if str(new_rows[0].get("startDate", ""))[:10] != ISSUE_DATE or str(new_rows[0].get("endDate", ""))[:10] != EXPIRY_DATE:
            raise RuntimeError("WB corrected document dates differ from FSA for " + offer)
        if (payload.get("documents") or {}).get("excludeDocuments") is not False:
            raise RuntimeError("WB payload excludes documents for " + offer)
        payloads.append(payload)

    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payloads) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB update exceeds documented limits: {len(payloads)} cards / {len(encoded)} bytes")
    if hashlib.sha256(encoded).hexdigest() != plan.get("payload_sha256"):
        raise RuntimeError("WB payload hash differs from the reviewed plan")

    state = {"started_at": now(), "phase": "prepared", "cards": len(payloads),
             "document_number": NUMBER, "documents_corrected": len(payloads),
             "excluded_out_of_scope_or_conflicting": len(plan["excluded"]),
             "preserved_all_other_document_rows": True,
             "preserved_full_card_fields": list(CARD_FIELDS),
             "source_wb_checked_at": plan["evidence"]["wb_fullcard_read"]["checked_at"],
             "request_bytes": len(encoded), "request_sha256": hashlib.sha256(encoded).hexdigest(),
             "limit_bytes": 10_000_000, "limit_cards": 3000}
    save_json(RUN_PATH, state)
    client = Client()
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain", "error_type": type(exc).__name__})
        save_json(RUN_PATH, state)
        raise RuntimeError("WB update outcome uncertain; read live cards before any retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state.update({"phase": "response_error", "updated_at": now()})
        save_json(RUN_PATH, state)
        raise RuntimeError("WB did not accept the update; reconcile before retry")
    state.update({"phase": "accepted_waiting_for_sync", "accepted_at": now()})
    save_json(RUN_PATH, state)

    expected = {item["offer_id"]: item for item in updates}
    readback = {"started_at": now(), "complete": False, "target_count": len(expected),
                "read_count": 0, "cards_by_offer": {}, "missing": [], "duplicates": [],
                "failures": [], "certificate_row_status_counts": {}}
    save_json(READBACK_PATH, readback)
    status_counts: collections.Counter[str] = collections.Counter()
    for index, offer in enumerate(sorted(expected), 1):
        try:
            found = client.wb_cards(offer)
            if len(found) == 0:
                readback["missing"].append(offer)
            elif len(found) != 1:
                readback["duplicates"].append({"offer_id": offer, "nmIDs": [str(x.get("nmID")) for x in found]})
            else:
                card = found[0]
                readback["cards_by_offer"][offer] = card
                item = expected[offer]
                before, payload = item["before"], item["payload"]
                if str(card.get("nmID")) != str(item["nmID"]) or card.get("vendorCode") != offer:
                    readback["failures"].append({"offer_id": offer, "error": "card_identity_changed"})
                changed_fields = [field for field in CARD_FIELDS if field not in ("characteristics",)
                                  and field in payload and card.get(field) != payload[field]]
                if changed_fields:
                    readback["failures"].append({"offer_id": offer, "error": "preserved_card_fields_changed",
                                                  "fields": changed_fields})
                if char_rows(before, doc_only=False) != char_rows(card, doc_only=False):
                    readback["failures"].append({"offer_id": offer, "error": "ordinary_characteristics_changed"})

                old_docs = (before.get("documents") or {}).get("items") or []
                live_docs = ((card.get("documents") or {}).get("items") or [])
                expected_docs = {str(d.get("id")): clean_document(d) for d in old_docs if d.get("id")}
                live_docs_by_id = {str(d.get("id")): d for d in live_docs if d.get("id")}
                if (len(expected_docs) != len(old_docs) or len(live_docs_by_id) != len(live_docs)
                        or len(expected_docs) != len(live_docs)):
                    readback["failures"].append({"offer_id": offer, "error": "document_row_count_changed",
                                                  "before": len(expected_docs), "after": len(live_docs)})
                else:
                    old_target = [d for d in expected_docs.values() if int(d.get("type") or 0) == 1
                                  and norm(d.get("number", "")).endswith(OLD_SUFFIX)]
                    current_target = [d for d in live_docs if int(d.get("type") or 0) == 1
                                      and d.get("number") == NUMBER]
                    if len(old_target) == 1 and len(current_target) == 1:
                        for d in expected_docs.values():
                            if int(d.get("type") or 0) == 1 and norm(d.get("number", "")).endswith(OLD_SUFFIX):
                                d["number"] = NUMBER
                    if set(expected_docs) != set(live_docs_by_id) or any(
                            clean_document(live_docs_by_id[doc_id]) != expected
                            for doc_id, expected in expected_docs.items() if doc_id in live_docs_by_id):
                        readback["failures"].append({"offer_id": offer, "error": "document_values_changed_unexpectedly"})
                if (card.get("documents") or {}).get("excludeDocuments") is not False:
                    readback["failures"].append({"offer_id": offer, "error": "documents_excluded"})
                cert_rows = [d for d in live_docs if int(d.get("type") or 0) == 1 and d.get("number") == NUMBER]
                if len(cert_rows) == 1:
                    verdict = cert_rows[0].get("verdict") or {}
                    status_counts[f"{verdict.get('status')}:{verdict.get('reason')}:{verdict.get('verified')}"] += 1
                else:
                    status_counts["canonical_row_not_yet_visible"] += 1
                before_char = char_rows(before, doc_only=True)
                live_char = char_rows(card, doc_only=True)
                if (15001136 in before_char and 15001136 in live_char
                        and NUMBER not in live_char[15001136][1]):
                    readback["failures"].append({"offer_id": offer,
                                                  "error": "certificate_number_characteristic_not_synchronized"})
        except Exception as exc:
            readback["failures"].append({"offer_id": offer, "error_type": type(exc).__name__})
        readback["read_count"] = index
        readback["certificate_row_status_counts"] = dict(status_counts)
        readback["updated_at"] = now()
        if index % 20 == 0 or index == len(expected):
            save_json(READBACK_PATH, readback)
            state.update({"phase": "readback_in_progress", "readback_count": index,
                          "canonical_rows_visible": sum(v for k, v in status_counts.items()
                                                          if k != "canonical_row_not_yet_visible"),
                          "certificate_row_status_counts": dict(status_counts)})
            save_json(RUN_PATH, state)
            print(json.dumps({"readback": index, "total": len(expected),
                              "canonical_statuses": dict(status_counts),
                              "failures": len(readback["failures"])}, ensure_ascii=False), flush=True)

    readback["complete"] = (readback["read_count"] == len(expected)
                            and len(readback["cards_by_offer"]) + len(readback["missing"])
                            + len(readback["duplicates"]) == len(expected))
    readback["all_canonical_rows_visible"] = status_counts.get("canonical_row_not_yet_visible", 0) == 0
    readback["all_documents_valid"] = bool(status_counts) and set(status_counts) == {"1:valid:True"}
    readback["updated_at"] = now()
    save_json(READBACK_PATH, readback)
    state.update({"phase": "readback_complete" if readback["complete"] else "readback_incomplete",
                  "finished_at": now(), "readback_count": readback["read_count"],
                  "canonical_row_status_counts": dict(status_counts),
                  "all_canonical_rows_visible": readback["all_canonical_rows_visible"],
                  "all_documents_valid": readback["all_documents_valid"],
                  "readback_path": str(READBACK_PATH)})
    save_json(RUN_PATH, state)
    print(json.dumps({"phase": state["phase"], "cards_submitted": len(payloads),
                      "excluded": len(plan["excluded"]), "canonical_rows_visible": readback["all_canonical_rows_visible"],
                      "all_documents_valid": readback["all_documents_valid"],
                      "row_status_counts": dict(status_counts), "failures": len(readback["failures"]),
                      "readback": str(READBACK_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
