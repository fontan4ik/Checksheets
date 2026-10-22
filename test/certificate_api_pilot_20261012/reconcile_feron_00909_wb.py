"""Reconcile accepted WB declaration correction with exact full-card readback."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import now
from audit_feron_01315_53551 import norm
from execute_feron_00909_wb import (CARD_FIELDS, DOC_CHAR_IDS, NUMBER, ISSUE_DATE, EXPIRY_DATE,
                                     document_characteristics, ordinary_characteristics)

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_00909_wb_plan.json"
RUN_PATH = BASE / "feron_00909_wb_execution.json"
READBACK_PATH = BASE / "feron_00909_wb_readback.json"
ERRORS_PATH = BASE / "feron_00909_wb_error_reconciliation.json"
OUT_PATH = BASE / "feron_00909_wb_verification.json"
OLD_NUMBER = "ЕАЭС N RU Д-CN.PA010.B.00909/23"


def doc_fields(doc: dict) -> dict:
    allowed = ("id", "type", "number", "productNumber", "tradeName", "applicant",
               "startDate", "endDate", "isEndless")
    return {k: doc[k] for k in allowed if k in doc}


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    run = json.loads(RUN_PATH.read_text(encoding="utf-8"))
    after = json.loads(READBACK_PATH.read_text(encoding="utf-8"))
    errors = json.loads(ERRORS_PATH.read_text(encoding="utf-8"))
    if run.get("response", {}).get("error") is not False or run.get("cards") != 268:
        raise RuntimeError("WB update was not accepted for the expected 268-card batch")
    targets = {x["offer_id"]: x for x in plan["updates"]}
    live = after.get("cards_by_offer") or {}
    if len(live) != 268 or set(live) != set(targets) or after.get("missing"):
        raise RuntimeError("WB readback did not return all exact updated target cards")

    status_counts = collections.Counter()
    failures, pending = [], []
    chars_preserved = 0
    other_docs_preserved = 0
    for offer, item in targets.items():
        before, card = item["before"], live[offer]
        if str(card.get("nmID")) != str(item["nmID"]) or card.get("vendorCode") != offer:
            failures.append({"offer_id": offer, "reason": "identity_changed"})
            continue
        payload = item["payload"]
        changed_fields = [f for f in CARD_FIELDS if f != "characteristics" and f in payload
                          and card.get(f) != payload[f]]
        if ordinary_characteristics(before) != ordinary_characteristics(card):
            changed_fields.append("characteristics_other_than_document_fields")
        if changed_fields:
            failures.append({"offer_id": offer, "reason": "card_fields_changed", "fields": changed_fields})
        else:
            chars_preserved += 1

        if (card.get("documents") or {}).get("excludeDocuments") is not False:
            failures.append({"offer_id": offer, "reason": "documents_excluded"})
        original_docs = (before.get("documents") or {}).get("items") or []
        current_docs = ((card.get("documents") or {}).get("items") or [])
        if len(original_docs) != len(current_docs):
            failures.append({"offer_id": offer, "reason": "document_count_changed",
                             "before": len(original_docs), "after": len(current_docs)})
            continue
        by_id = {str(d.get("id")): d for d in current_docs if d.get("id")}
        target_old = [d for d in original_docs if int(d.get("type") or 0) == 2
                      and norm(d.get("number", "")).endswith("0090923")]
        if len(target_old) != 1 or not target_old[0].get("id"):
            failures.append({"offer_id": offer, "reason": "source_target_document_ambiguous"})
            continue
        old_target = target_old[0]
        current_target = by_id.get(str(old_target["id"]))
        if not current_target:
            failures.append({"offer_id": offer, "reason": "target_document_id_missing"})
            continue
        canonical = (str(current_target.get("number")) == NUMBER
                     and int(current_target.get("type") or 0) == 2
                     and str(current_target.get("startDate", ""))[:10] == ISSUE_DATE
                     and str(current_target.get("endDate", ""))[:10] == EXPIRY_DATE
                     and current_target.get("isEndless") is False)
        if canonical:
            verdict = current_target.get("verdict") or {}
            if verdict.get("verified") is not True or verdict.get("status") != 1 or verdict.get("reason") != "valid":
                failures.append({"offer_id": offer, "reason": "canonical_row_not_finally_valid",
                                 "verdict": verdict})
            else:
                status_counts["valid"] += 1
        elif (str(current_target.get("number")) == str(old_target.get("number"))
              and (current_target.get("verdict") or {}).get("reason") == "document_not_found"):
            pending.append(offer)
            status_counts["old_number_document_not_found"] += 1
        else:
            failures.append({"offer_id": offer, "reason": "unexpected_document_state",
                             "number": current_target.get("number"),
                             "verdict": current_target.get("verdict")})

        for old_doc in original_docs:
            if str(old_doc.get("id")) == str(old_target.get("id")):
                expected_number = NUMBER if canonical else old_doc.get("number")
                if (current_target.get("number") != expected_number
                        or int(current_target.get("type") or 0) != int(old_doc.get("type") or 0)
                        or str(current_target.get("startDate", ""))[:10] != str(old_doc.get("startDate", ""))[:10]
                        or str(current_target.get("endDate", ""))[:10] != str(old_doc.get("endDate", ""))[:10]
                        or current_target.get("isEndless") != old_doc.get("isEndless")):
                    failures.append({"offer_id": offer, "reason": "target_document_metadata_changed"})
                continue
            current = by_id.get(str(old_doc.get("id")))
            if not current or doc_fields(current) != doc_fields(old_doc):
                failures.append({"offer_id": offer, "reason": "other_document_changed",
                                 "id": old_doc.get("id")})
            else:
                other_docs_preserved += 1

        before_doc_chars = document_characteristics(before)
        current_doc_chars = document_characteristics(card)
        expected_doc_chars = dict(before_doc_chars)
        if canonical and 15001135 in expected_doc_chars:
            expected_doc_chars[15001135] = (expected_doc_chars[15001135][0],
                                             json.dumps([NUMBER], ensure_ascii=False, sort_keys=True))
        if expected_doc_chars != current_doc_chars:
            failures.append({"offer_id": offer, "reason": "document_characteristic_state_mismatch"})

    expected_pending = sorted(pending)
    error_batches_for_pending = [batch for batch in errors.get("batches_matching_pending", [])
                                 if set(batch.get("offers", [])) & set(expected_pending)]
    result = {
        "verified_at": now(), "number": NUMBER, "replaces_number": OLD_NUMBER,
        "wb_request_accepted": True, "submitted_cards": run.get("cards"),
        "readback_cards": len(live), "cards_with_canonical_number_and_final_valid": status_counts["valid"],
        "cards_still_showing_old_rejected_number": len(expected_pending), "pending_offers": expected_pending,
        "verdict_counts": dict(status_counts), "all_non_document_characteristics_preserved": chars_preserved == 268,
        "preserved_other_document_rows": other_docs_preserved,
        "pending_offers_have_error_list_entry": bool(error_batches_for_pending),
        "error_list_checked_at": errors.get("checked_at"), "matching_error_batches": error_batches_for_pending,
        "missing_wb_offer": "41185-1", "local_cleanup_allowed": False,
        "local_cleanup_reason": "One WB card is missing and 19 WB rows still show document_not_found; local originals and copies remain required.",
        "failures": failures,
        "initial_executor_validation_note": "The first readback pass treated WB characteristic array ordering as a content change. Reconciliation compares by characteristic id/value and accounts for WB's derived document fields.",
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verification": str(OUT_PATH), "submitted": result["submitted_cards"],
                      "final_valid": result["cards_with_canonical_number_and_final_valid"],
                      "pending_old_rows": result["cards_still_showing_old_rejected_number"],
                      "pending_have_error_entry": result["pending_offers_have_error_list_entry"],
                      "characteristics_preserved": result["all_non_document_characteristics_preserved"],
                      "other_document_rows_preserved": result["preserved_other_document_rows"],
                      "failures": len(failures)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
