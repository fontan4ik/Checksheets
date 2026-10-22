"""Attach active Kosmos 03254/23 only to exact-scope WB cards; leave WB review intact."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now, digest  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    UPDATE_CARD_FIELDS, comparable_card, copy_documents, doc_key, norm_number,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

PREFLIGHT = HERE / "kosmos_03254_wb_preflight_live_20261021.json"
STATE = HERE / "kosmos_03254_wb_execution_20261021.json"
BEFORE = HERE / "kosmos_03254_wb_before_20261021.json"
READBACK = HERE / "kosmos_03254_wb_readback_20261021.json"
JOURNAL = HERE / "kosmos_03254_wb_mutation_journal_20261021.jsonl"
SOURCE = ROOT / "output_to_user/certificates/group_3/docs/kosmos_cert_03254_23.pdf"
NUMBER = "ЕАЭС RU С-CN.НВ93.В.03254/23"
ISSUE = "2023-05-19"
EXPIRY = "2028-05-18"
ALLOWED_TNVED = {"8539520002", "8539520003", "8539520009"}
TARGET_DOC = {"type": 1, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
              "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}


def save(path: pathlib.Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                values.append(str(value).split(" - ", 1)[0].strip())
    return sorted(set(values))


def doc_signature(row: dict) -> tuple:
    return (doc_key(row), str(row.get("startDate", ""))[:10],
            str(row.get("endDate", ""))[:10], bool(row.get("isEndless")))


def doc_status(row: dict) -> str:
    verdict = row.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True:
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    if any(path.exists() for path in (STATE, BEFORE, READBACK, JOURNAL)):
        raise RuntimeError("wb_execution_artifact_exists; reconcile before any retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("official_fsa_record", {}).get("record_id") != 3249749:
        raise RuntimeError("fresh_source_preflight_missing_or_malformed")
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 600:
        raise RuntimeError("live_wb_preflight_older_than_10_minutes")
    if (pre.get("official_fsa_record", {}).get("status_observed") != "Действует"
            or pre.get("official_fsa_record", {}).get("number") != NUMBER
            or pre.get("official_fsa_record", {}).get("issue_date") != ISSUE
            or pre.get("official_fsa_record", {}).get("expiry_date") != EXPIRY
            or digest(SOURCE) != pre.get("source_pdf", {}).get("sha256")):
        raise RuntimeError("official_registry_metadata_or_source_pdf_hash_changed")
    targets = {str(row["offer_id"]): row for row in pre.get("cards") or []}
    if len(targets) != 232 or len(pre.get("cards") or []) != 232:
        raise RuntimeError("preflight_target_set_not_exactly_232")

    client = Client()
    prepared = []
    already_exact = []
    before_rows = []
    for index, (offer, expected) in enumerate(sorted(targets.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError(f"wb_card_missing_or_ambiguous:{offer}:{len(cards)}")
        card = cards[0]
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "космос"
                or card_tnved(card) != expected.get("tnved_codes")
                or not set(card_tnved(card)) <= ALLOWED_TNVED):
            raise RuntimeError("fresh_wb_identity_or_tnved_changed:" + offer)
        title = str(card.get("title") or "").casefold()
        if "ламп" not in title or not any(word in title for word in ("led", "светодиод")):
            raise RuntimeError("fresh_wb_product_type_changed:" + offer)
        docs_container = card.get("documents") or {}
        if docs_container.get("excludeDocuments") is True:
            raise RuntimeError("fresh_wb_card_excludes_documents:" + offer)
        docs = copy_documents(card)
        same = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        if same:
            exact = (len(same) == 1 and doc_key(same[0]) == doc_key(TARGET_DOC)
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY
                     and same[0].get("isEndless") is False)
            if not exact:
                raise RuntimeError("same_certificate_number_has_conflicting_metadata:" + offer)
            already_exact.append(offer)
            continue
        payload = merge_wb(card, [TARGET_DOC])
        if payload is None:
            raise RuntimeError("wb_merge_did_not_add_missing_certificate:" + offer)
        if any(payload.get(key) != card.get(key) for key in UPDATE_CARD_FIELDS if key in card):
            raise RuntimeError("full_card_payload_would_change_unrelated_field:" + offer)
        prior_037 = [doc for doc in docs if norm_number(doc.get("number")) ==
                     norm_number("ЕАЭС N RU Д-CN.РА06.В.78454/22")]
        before_rows.append({"offer_id": offer, "nmID": str(card["nmID"]), "card": card,
                            "prior_document_signatures": [doc_signature(doc) for doc in docs],
                            "prior_037_count": len(prior_037),
                            "prior_037_status": doc_status(prior_037[0]) if len(prior_037) == 1 else "missing_or_ambiguous"})
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]), "payload": payload})
        if index % 40 == 0 or index == len(targets):
            print(f"WB final prewrite reread {index}/{len(targets)}", flush=True)

    if len(prepared) + len(already_exact) != len(targets):
        raise RuntimeError("prewrite_target_accounting_incomplete")
    payloads = [row["payload"] for row in prepared]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 9_000_000:
        raise RuntimeError("wb_request_exceeds_conservative_9mb_limit")
    payload_hash = hashlib.sha256(encoded).hexdigest()
    save(BEFORE, {
        "checked_at_utc": now(), "complete": True, "number": NUMBER,
        "target_count": len(targets), "update_count": len(prepared),
        "already_exact_count": len(already_exact), "cards": before_rows,
        "preexisting_037_rows": sum(x["prior_037_count"] == 1 for x in before_rows),
        "preexisting_037_valid": sum(x["prior_037_status"] == "valid" for x in before_rows),
        "payload_sha256": payload_hash, "payload_bytes": len(encoded),
    })
    state = {
        "started_at_utc": now(), "phase": "wb_fresh_prewrite_verified",
        "number": NUMBER, "wb_target_cards": len(targets), "wb_update_count": len(prepared),
        "already_exact_count": len(already_exact), "wb_no_exact_card_count": 0,
        "document_type": "certificate_of_conformity", "issue_date": ISSUE, "expire_date": EXPIRY,
        "official_fsa_record_id": 3249749,
        "official_fsa_registry_status_observed": "Действует",
        "official_fsa_sample_date_cutoff": "2022-07-01; item lot manufacture dates are not present in marketplace cards",
        "tnved_counts": {"8539520009": len(targets)},
        "ozon_write_skipped": True,
        "ozon_skip_reason": pre.get("ozon_skip_reason"),
        "wb_review_left_to_wb": True, "local_file_deleted": False,
        "payload_bytes": len(encoded), "payload_sha256": payload_hash,
        "writes_sent": 0,
    }
    save(STATE, state)
    if prepared:
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "prepared", "at": now(), "cards": len(prepared),
                                     "payload_sha256": payload_hash}, ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="wb_update_sent", writes_sent=1, sent_at_utc=now())
        save(STATE, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            state.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at_utc=now())
            save(STATE, state)
            raise RuntimeError("wb_update_outcome_uncertain; reconcile live readback before retry") from None
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "response", "at": now(), "response": response},
                                    ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="wb_update_response", wb_response_error=response.get("error"), updated_at_utc=now())
        save(STATE, state)
        if response.get("error") is not False:
            state.update(phase="wb_update_rejected", error_text=str(response.get("errorText") or "")[:500])
            save(STATE, state)
            raise RuntimeError("wb_update_rejected; inspect live state before retry")

    before_by_offer = {row["offer_id"]: row for row in before_rows}
    rows = []
    failures = []
    status_counts = collections.Counter()
    for index, (offer, expected) in enumerate(sorted(targets.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count_changed", "count": len(cards)})
            continue
        card = cards[0]
        docs = (card.get("documents") or {}).get("items") or []
        exact = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        exact_meta = [doc for doc in exact if doc_key(doc) == doc_key(TARGET_DOC)
                      and str(doc.get("startDate", ""))[:10] == ISSUE
                      and str(doc.get("endDate", ""))[:10] == EXPIRY
                      and doc.get("isEndless") is False]
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "exact_document_count": len(exact), "metadata_exact": len(exact_meta) == 1,
               "document_status": doc_status(exact_meta[0]) if len(exact_meta) == 1 else "readback_missing_or_conflicting",
               "verdict": exact_meta[0].get("verdict") if len(exact_meta) == 1 else None,
               "overall_verdict": card.get("documents", {}).get("overallVerdict"),
               "tnved_codes": card_tnved(card), "brand": card.get("brand")}
        if offer in before_by_offer:
            before = before_by_offer[offer]
            preserved = comparable_card(card) == comparable_card(before["card"])
            after_signatures = [doc_signature(doc) for doc in copy_documents(card)]
            preserved = preserved and all(signature in after_signatures
                                          for signature in before["prior_document_signatures"])
            row["unrelated_card_fields_and_prior_documents_preserved"] = preserved
        else:
            # The exact row already existed; verify its metadata did not regress.
            row["unrelated_card_fields_and_prior_documents_preserved"] = True
        status_counts[row["document_status"]] += 1
        rows.append(row)
        if (not row["metadata_exact"] or not row["unrelated_card_fields_and_prior_documents_preserved"]
                or str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(expected.get("nmID") or "")):
            failures.append(row)
        if index % 40 == 0 or index == len(targets):
            print(f"WB readback {index}/{len(targets)}", flush=True)

    result = {"checked_at_utc": now(), "complete": len(rows) == len(targets),
              "number": NUMBER, "target_cards": len(targets), "updated_cards": len(prepared),
              "verified_target_cards": len(rows) - len(failures), "status_counts": dict(status_counts),
              "failures": failures, "wb_review_left_pending": all(
                  row["document_status"] == "pending_review_or_verdict_missing" for row in rows),
              "cards": rows}
    save(READBACK, result)
    if failures or len(rows) != len(targets):
        state.update(phase="wb_readback_incomplete", failure_count=len(failures), updated_at_utc=now())
        save(STATE, state)
        raise RuntimeError("wb_readback_incomplete; inspect readback artifact")
    state.update(phase="verified_complete", readback_path=str(READBACK),
                 verified_target_cards=len(rows), wb_status_counts=dict(status_counts),
                 wb_review_left_pending=result["wb_review_left_pending"],
                 local_file_deleted=False, updated_at_utc=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "updated_cards": len(prepared),
                      "verified_target_cards": len(rows), "status_counts": dict(status_counts),
                      "wb_review_left_pending": result["wb_review_left_pending"],
                      "ozon_write_skipped": True, "source_pdf_deleted": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
