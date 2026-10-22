"""Read back the seven WB cards after the AlphaCable full-card update."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import BASE, Client, now
from feron_53483_crossplatform_20261013 import CARD_FIELDS, clean_wb_doc, norm

EXEC = BASE / "alphacable_00103_wb_execution_20261013.json"
OUT = BASE / "alphacable_00103_wb_verification_20261013.json"
NUMBER = "ЕАЭС RU С-RU.АД38.В.00103/25"
OLD_NUMBER = "ЕАЭС RU С-RU.НА39.В.01186/22"
ISSUE = "2025-05-21"
EXPIRY = "2030-05-20"


def doc_signature(row: dict) -> tuple:
    return (int(row.get("type") or 0), norm(row.get("number") or ""),
            str(row.get("startDate") or "")[:10], str(row.get("endDate") or "")[:10],
            bool(row.get("isEndless", False)))


def docs_counter(rows: list[dict]) -> collections.Counter:
    return collections.Counter(json.dumps(clean_wb_doc(x), ensure_ascii=False, sort_keys=True)
                               for x in rows or [])


def char_counter(rows: list[dict]) -> collections.Counter:
    return collections.Counter((int(x.get("id", -1)), str(x.get("name") or ""),
                                json.dumps(x.get("value"), ensure_ascii=False, sort_keys=True))
                               for x in rows or [])


def read_error_batches(client: Client) -> list[dict]:
    batches = []
    cursor = {"limit": 100}
    for _ in range(100):
        body = client.call("wb", "/content/v2/cards/error/list",
                           {"cursor": cursor, "order": {"ascending": True}})
        if body.get("error"):
            raise RuntimeError("WB error-list returned an API error")
        data = body.get("data") or {}
        batches.extend(data.get("items") or [])
        page = data.get("cursor") or {}
        if page.get("next") is not True:
            return batches
        if not page.get("updatedAt") or not page.get("batchUUID"):
            raise RuntimeError("WB error-list cursor is incomplete")
        cursor = {"limit": 100, "updatedAt": page["updatedAt"], "batchUUID": page["batchUUID"]}
    raise RuntimeError("WB error-list pagination exceeded 100 pages")


def main() -> None:
    execution = json.loads(EXEC.read_text(encoding="utf-8"))
    if execution.get("phase") not in {"accepted_waiting_for_wb_sync", "mutation_uncertain"}:
        raise RuntimeError("WB journal does not indicate an accepted or uncertain write")
    sent = execution.get("payload") or []
    if len(sent) != 7:
        raise RuntimeError("WB journal does not contain seven exact card payloads")
    client = Client()
    results = []
    for payload in sent:
        offer = str(payload.get("vendorCode") or "")
        expected_nmid = str(payload.get("nmID") or "")
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            results.append({"offer_id": offer, "card_count": len(cards), "visible": False})
            continue
        card = cards[0]
        changed_fields = []
        for field in CARD_FIELDS:
            if field == "characteristics":
                if char_counter(card.get(field) or []) != char_counter(payload.get(field) or []):
                    changed_fields.append(field)
            elif card.get(field) != payload.get(field):
                changed_fields.append(field)
        docs = card.get("documents") or card.get("docs") or {}
        actual_rows = docs.get("items") or []
        sent_rows = (payload.get("documents") or {}).get("items") or []
        old_actual = [x for x in actual_rows if norm(x.get("number")) == norm(OLD_NUMBER)]
        old_sent = [x for x in sent_rows if norm(x.get("number")) == norm(OLD_NUMBER)]
        new_rows = [x for x in actual_rows if doc_signature(x) == (1, norm(NUMBER), ISSUE, EXPIRY, False)]
        preserved = docs_counter(old_actual) == docs_counter(old_sent)
        all_docs_match = docs_counter(actual_rows) == docs_counter(sent_rows)
        result = {
            "offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "identity_exact": str(card.get("nmID") or "") == expected_nmid
                              and str(card.get("vendorCode") or "") == offer,
            "updatedAt": card.get("updatedAt"), "changed_non_document_fields": changed_fields,
            "non_document_fields_preserved": not changed_fields,
            "documents_excluded": docs.get("excludeDocuments"),
            "new_document_rows": new_rows, "new_document_count": len(new_rows),
            "old_invalid_document_count_before": len(old_sent),
            "old_invalid_document_count_after": len(old_actual),
            "old_documents_preserved": preserved, "all_document_rows_match_payload": all_docs_match,
            "overallVerdict": docs.get("overallVerdict"),
            "document_verdicts": [{"number": x.get("number"), "verdict": x.get("verdict")}
                                   for x in actual_rows],
        }
        results.append(result)
    visible = len(results) == 7 and all(x.get("identity_exact") and x.get("new_document_count") == 1
                                        for x in results)
    safe = visible and all(x.get("non_document_fields_preserved") and x.get("old_documents_preserved")
                           and x.get("documents_excluded") is False for x in results)
    fully_valid = safe and all((x.get("new_document_rows") or [{}])[0].get("verdict", {}).get("verified") is True
                               and (x.get("new_document_rows") or [{}])[0].get("verdict", {}).get("status") == 1
                               and (x.get("new_document_rows") or [{}])[0].get("verdict", {}).get("reason") == "valid"
                               for x in results)
    target_offers = {str(x.get("vendorCode") or "") for x in sent}
    try:
        error_batches = read_error_batches(client)
        error_matches = []
        for batch in error_batches:
            errors = batch.get("errors") or {}
            matched_codes = sorted(target_offers & set(str(x) for x in errors))
            if matched_codes:
                error_matches.append({"batchUUID": batch.get("batchUUID"),
                                      "updatedAt": batch.get("updatedAt"),
                                      "errors": {code: errors.get(code) for code in matched_codes}})
        error_state = {"checked": True, "batch_count": len(error_batches),
                       "matching_error_batches": error_matches}
    except Exception as exc:
        error_state = {"checked": False, "error_type": type(exc).__name__}
    state = {"checked_at_utc": now(), "write_accepted": (execution.get("response") or {}).get("error") is False,
             "target_count": len(results), "all_seven_documents_visible": visible,
             "all_card_fields_and_prior_docs_preserved": safe,
             "all_seven_finally_valid_on_wb": fully_valid, "wb_error_list": error_state, "products": results}
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": state["checked_at_utc"],
                      "all_seven_documents_visible": visible,
                      "all_card_fields_and_prior_docs_preserved": safe,
                      "all_seven_finally_valid_on_wb": fully_valid,
                      "new_document_statuses": [((x.get("new_document_rows") or [{}])[0].get("verdict") or {}).get("reason")
                                                 for x in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
