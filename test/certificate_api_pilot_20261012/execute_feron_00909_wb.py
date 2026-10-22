"""Submit exact Feron 00909/23 full-card corrections to WB once and read them back."""
from __future__ import annotations

import collections
import hashlib
import json
import time
from pathlib import Path

from api_client import Client, now
from audit_feron_01315_53551 import norm

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_00909_wb_plan.json"
RUN_PATH = BASE / "feron_00909_wb_execution.json"
READBACK_PATH = BASE / "feron_00909_wb_readback.json"
NUMBER = "ЕАЭС N RU Д-CN.РА10.В.00909/23"
ISSUE_DATE = "2023-11-23"
EXPIRY_DATE = "2028-11-22"
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def save_run(state: dict) -> None:
    state["updated_at"] = now()
    temp = RUN_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(RUN_PATH)


def ordinary_characteristics(card: dict) -> list[tuple]:
    result = []
    for row in card.get("characteristics") or []:
        if int(row.get("id", -1)) in DOC_CHAR_IDS:
            continue
        result.append((int(row.get("id", -1)), row.get("name"),
                       json.dumps(row.get("value"), ensure_ascii=False, sort_keys=True)))
    return sorted(result)


def document_characteristics(card: dict) -> dict[int, tuple]:
    return {int(row.get("id", -1)): (row.get("name"),
             json.dumps(row.get("value"), ensure_ascii=False, sort_keys=True))
            for row in card.get("characteristics") or [] if int(row.get("id", -1)) in DOC_CHAR_IDS}


def main() -> None:
    if RUN_PATH.exists() or READBACK_PATH.exists():
        raise RuntimeError("WB update was already attempted; reconcile live cards before any retry")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    cards = plan.get("updates") or []
    if len(cards) != 268 or plan.get("counts", {}).get("wb_cards_to_update") != len(cards):
        raise RuntimeError("Unexpected exact WB update target set")
    if plan.get("local_cleanup_allowed") is not False:
        raise RuntimeError("Plan must retain all local files")
    payloads = []
    for item in cards:
        before, payload = item.get("before") or {}, item.get("payload") or {}
        if (str(before.get("nmID")) != str(item.get("nmID"))
                or str(payload.get("nmID")) != str(item.get("nmID"))
                or before.get("vendorCode") != item.get("offer_id")
                or payload.get("vendorCode") != item.get("offer_id")):
            raise RuntimeError("WB exact card identity mismatch for " + item.get("offer_id", ""))
        for field in CARD_FIELDS:
            if field in before and payload.get(field) != before[field]:
                raise RuntimeError(f"Full-card payload changed existing {field} for {item['offer_id']}")
        if payload.get("documents", {}).get("excludeDocuments") is not False:
            raise RuntimeError("WB documents are excluded in payload for " + item["offer_id"])
        old_docs = (before.get("documents") or {}).get("items") or []
        new_docs = (payload.get("documents") or {}).get("items") or []
        old_rows = [x for x in old_docs if int(x.get("type") or 0) == 2 and norm(x.get("number", "")) != norm(NUMBER)
                    and norm(x.get("number", "")).endswith("0090923")]
        new_rows = [x for x in new_docs if int(x.get("type") or 0) == 2 and norm(x.get("number", "")) == norm(NUMBER)]
        if len(old_rows) != 1 or len(new_rows) != 1:
            raise RuntimeError("WB document correction is missing or duplicated for " + item["offer_id"])
        if (str(new_rows[0].get("startDate", ""))[:10] != ISSUE_DATE
                or str(new_rows[0].get("endDate", ""))[:10] != EXPIRY_DATE):
            raise RuntimeError("Corrected WB document dates differ from FSA for " + item["offer_id"])
        payloads.append(payload)

    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payloads) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB update exceeds official card/size limit: {len(payloads)} / {len(encoded)}")
    state = {"started_at": now(), "phase": "prepared", "cards": len(payloads),
             "document_number": NUMBER, "documents_corrected": len(payloads),
             "preserved_all_other_document_rows": True, "preserved_full_card_fields": list(CARD_FIELDS),
             "wb_live_checked_at": plan["source_live_audit"]["checked_at"],
             "ozon_record_status": plan["ozon_evidence"]["record_status"],
             "ozon_binding_statuses": plan["ozon_evidence"]["binding_statuses"],
             "request_bytes": len(encoded), "request_sha256": hashlib.sha256(encoded).hexdigest(),
             "limit_bytes": 10_000_000, "limit_cards": 3000}
    save_run(state)
    client = Client()
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain", "error_type": type(exc).__name__})
        save_run(state)
        raise RuntimeError("WB update outcome uncertain; read live cards before retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state["phase"] = "response_error"
        save_run(state)
        raise RuntimeError("WB did not accept update; reconcile before retry")
    state["phase"] = "accepted_waiting_for_sync"
    save_run(state)

    # WB documents the update as asynchronous. Read every exact target once; if the
    # number has not propagated, retain the accepted journal and never auto-resubmit.
    readback = {"started_at": now(), "complete": False, "cards_by_offer": {}, "missing": [], "failures": []}
    temp_path = READBACK_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(READBACK_PATH)
    status_counts = collections.Counter()
    expected = {x["offer_id"]: x for x in cards}
    for index, offer in enumerate(sorted(expected), 1):
        try:
            found = client.wb_cards(offer)
        except Exception as exc:
            readback["failures"].append({"offer_id": offer, "error_type": type(exc).__name__})
            readback["updated_at"] = now()
            temp_path.write_text(json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(READBACK_PATH)
            state.update({"phase": "readback_incomplete", "readback_count": index - 1})
            save_run(state)
            raise
        if len(found) != 1:
            readback["missing"].append(offer)
        else:
            card = found[0]
            if str(card.get("nmID")) != str(expected[offer]["nmID"]):
                readback["failures"].append({"offer_id": offer, "error_type": "nmID_changed"})
            readback["cards_by_offer"][offer] = card
            before = expected[offer]["before"]
            payload = expected[offer]["payload"]
            changed_fields = [field for field in CARD_FIELDS if field != "characteristics"
                              and field in payload and card.get(field) != payload[field]]
            if ordinary_characteristics(before) != ordinary_characteristics(card):
                changed_fields.append("characteristics_other_than_document_fields")
            if changed_fields:
                readback["failures"].append({"offer_id": offer, "error_type": "preserved_card_fields_changed",
                                              "fields": changed_fields})
            rows = [d for d in ((card.get("documents") or {}).get("items") or [])
                    if int(d.get("type") or 0) == 2 and norm(d.get("number", "")) == norm(NUMBER)]
            expected_doc_chars = document_characteristics(before)
            old_target = next((d for d in ((before.get("documents") or {}).get("items") or [])
                               if int(d.get("type") or 0) == 2
                               and norm(d.get("number", "")).endswith("0090923")), None)
            if len(rows) == 1 and old_target and 15001135 in expected_doc_chars:
                char_name = expected_doc_chars[15001135][0]
                expected_doc_chars[15001135] = (char_name,
                    json.dumps([NUMBER], ensure_ascii=False, sort_keys=True))
            if document_characteristics(card) != expected_doc_chars:
                readback["failures"].append({"offer_id": offer,
                                              "error_type": "document_characteristics_changed_unexpectedly"})
            if (card.get("documents") or {}).get("excludeDocuments") is not False:
                readback["failures"].append({"offer_id": offer, "error_type": "documents_excluded"})
            current_docs = (card.get("documents") or {}).get("items") or []
            original_docs = (before.get("documents") or {}).get("items") or []
            if len(current_docs) != len(original_docs):
                readback["failures"].append({"offer_id": offer, "error_type": "document_row_count_changed",
                                              "before": len(original_docs), "after": len(current_docs)})
            else:
                original_by_id = {str(d.get("id")): d for d in original_docs if d.get("id")}
                current_by_id = {str(d.get("id")): d for d in current_docs if d.get("id")}
                for original_id, original in original_by_id.items():
                    current_doc = current_by_id.get(original_id)
                    if current_doc is None:
                        readback["failures"].append({"offer_id": offer, "error_type": "existing_document_id_missing",
                                                      "id": original_id})
                        continue
                    target_doc = (int(original.get("type") or 0) == 2
                                  and norm(original.get("number", "")).endswith("0090923"))
                    expected_number = (NUMBER if len(rows) == 1 and target_doc else original.get("number"))
                    if (current_doc.get("number") != expected_number
                            or int(current_doc.get("type") or 0) != int(original.get("type") or 0)
                            or str(current_doc.get("startDate", ""))[:10] != str(original.get("startDate", ""))[:10]
                            or str(current_doc.get("endDate", ""))[:10] != str(original.get("endDate", ""))[:10]
                            or current_doc.get("isEndless") != original.get("isEndless")):
                        readback["failures"].append({"offer_id": offer, "error_type": "existing_document_values_changed",
                                                      "id": original_id})
            if len(rows) == 1:
                verdict = rows[0].get("verdict") or {}
                status_counts[f"{verdict.get('status')}:{verdict.get('reason')}"] += 1
            else:
                status_counts["canonical_row_not_yet_visible"] += 1
        if index % 20 == 0 or index == len(expected):
            readback["read_count"] = index
            readback["checked_at"] = now()
            temp_path.write_text(json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(READBACK_PATH)
            print(json.dumps({"readback": index, "total": len(expected),
                              "canonical_rows_visible": sum(v for k, v in status_counts.items() if not k.startswith("canonical_row_not_yet_visible")),
                              "statuses": dict(status_counts)}, ensure_ascii=False), flush=True)
    readback["complete"] = len(readback["cards_by_offer"]) == len(expected) and not readback["failures"]
    readback["readback_count"] = len(expected)
    readback["canonical_number"] = NUMBER
    readback["canonical_row_status_counts"] = dict(status_counts)
    readback["all_canonical_rows_visible"] = (sum(v for k, v in status_counts.items()
                                                   if not k.startswith("canonical_row_not_yet_visible")) == len(expected))
    readback["updated_at"] = now()
    temp_path.write_text(json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(READBACK_PATH)
    state.update({"phase": "readback_complete" if readback["all_canonical_rows_visible"] else "accepted_waiting_for_wb_sync",
                  "readback_checked_at": readback["updated_at"], "canonical_rows_visible": sum(v for k, v in status_counts.items()
                                                                                             if not k.startswith("canonical_row_not_yet_visible")),
                  "canonical_row_status_counts": dict(status_counts)})
    save_run(state)
    print(json.dumps({"phase": state["phase"], "cards_submitted": len(payloads),
                      "canonical_rows_visible": state["canonical_rows_visible"],
                      "row_status_counts": dict(status_counts), "readback": str(READBACK_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
