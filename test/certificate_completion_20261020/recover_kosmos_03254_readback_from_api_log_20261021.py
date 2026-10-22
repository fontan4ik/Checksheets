"""Recover and verify the completed WB readback from its request journal (read-only)."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, doc_key, norm_number,
)

STATE = HERE / "kosmos_03254_wb_execution_20261021.json"
PREFLIGHT = HERE / "kosmos_03254_wb_preflight_live_20261021.json"
BEFORE = HERE / "kosmos_03254_wb_before_20261021.json"
INCOMPLETE = HERE / "kosmos_03254_wb_readback_20261021.json"
OUTPUT = HERE / "kosmos_03254_wb_readback_verified_20261021.json"
CALL_LOG = API / "api_calls.jsonl"
NUMBER = "ЕАЭС RU С-CN.НВ93.В.03254/23"
ISSUE = "2023-05-19"
EXPIRY = "2028-05-18"
TARGET_DOC = {"type": 1, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
              "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}


def save(path: pathlib.Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def expected_request_hash(offer: str) -> str:
    payload = {"settings": {"sort": {"ascending": True}, "cursor": {"limit": 100},
                            "filter": {"withPhoto": -1, "textSearch": offer}}}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def doc_signature(row: dict) -> list:
    return [list(doc_key(row)), str(row.get("startDate", ""))[:10],
            str(row.get("endDate", ""))[:10], bool(row.get("isEndless"))]


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


def status(row: dict) -> str:
    verdict = row.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True:
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if (state.get("phase") != "wb_readback_incomplete" or state.get("writes_sent") != 1
            or state.get("wb_response_error") is not False):
        raise RuntimeError("unexpected_execution_state_for_log_recovery")
    if OUTPUT.exists():
        raise RuntimeError("verified_readback_already_exists")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    before_doc = json.loads(BEFORE.read_text(encoding="utf-8"))
    targets = {str(row["offer_id"]): row for row in pre.get("cards") or []}
    old = {str(row["offer_id"]): row for row in before_doc.get("cards") or []}
    if len(targets) != 232 or len(old) != 232:
        raise RuntimeError("expected_232_source_and_before_rows")

    latest = {}
    for line in CALL_LOG.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (row.get("path") != "/content/v2/get/cards/list" or row.get("phase") != "response"
                or row.get("http_status") != 200 or not isinstance(row.get("body"), dict)):
            continue
        latest.setdefault(row.get("request_sha256"), []).append(row)

    rows = []
    failures = []
    document_status_counts = collections.Counter()
    prior_037_status_counts = collections.Counter()
    overall_status_counts = collections.Counter()
    write_sent = state.get("sent_at_utc") or ""
    for offer, expected in sorted(targets.items()):
        request_hash = expected_request_hash(offer)
        responses = latest.get(request_hash) or []
        if not responses:
            failures.append({"offer_id": offer, "problem": "no_matching_postwrite_read_response_in_api_log"})
            continue
        response = max(responses, key=lambda item: item.get("finished_at") or item.get("started_at") or "")
        if (response.get("finished_at") or "") <= write_sent:
            failures.append({"offer_id": offer, "problem": "latest_response_not_after_write", "finished_at": response.get("finished_at")})
            continue
        cards = response.get("body", {}).get("cards")
        if not isinstance(cards, list) or len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "postwrite_response_card_count_not_one", "count": len(cards or [])})
            continue
        card = cards[0]
        docs_container = card.get("documents") or {}
        docs = docs_container.get("items") or []
        exact = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        exact_meta = [doc for doc in exact if doc_key(doc) == doc_key(TARGET_DOC)
                      and str(doc.get("startDate", ""))[:10] == ISSUE
                      and str(doc.get("endDate", ""))[:10] == EXPIRY
                      and doc.get("isEndless") is False]
        prior_docs = [doc for doc in docs if norm_number(doc.get("number")) != norm_number(NUMBER)]
        prior_signatures = [doc_signature(doc) for doc in prior_docs]
        wanted_signatures = old[offer].get("prior_document_signatures") or []
        prior_preserved = all(signature in prior_signatures for signature in wanted_signatures)
        prior_037 = [doc for doc in docs if norm_number(doc.get("number")) ==
                     norm_number("ЕАЭС N RU Д-CN.РА06.В.78454/22")]
        prior_037_state = status(prior_037[0]) if len(prior_037) == 1 else "missing_or_ambiguous"
        prior_037_status_counts[prior_037_state] += 1
        doc_state = status(exact_meta[0]) if len(exact_meta) == 1 else "readback_missing_or_conflicting"
        document_status_counts[doc_state] += 1
        overall = docs_container.get("overallVerdict") or {}
        overall_status_counts[str(overall.get("reason") or overall.get("status") or "unknown")] += 1
        unchanged = (str(card.get("vendorCode") or "") == offer
                     and str(card.get("nmID") or "") == str(expected.get("nmID") or "")
                     and comparable_card(card) == comparable_card(old[offer].get("card") or {})
                     and prior_preserved)
        result = {
            "offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "exact_document_count": len(exact), "metadata_exact": len(exact_meta) == 1,
            "document_status": doc_state,
            "verdict": exact_meta[0].get("verdict") if len(exact_meta) == 1 else None,
            "overall_verdict": overall,
            "existing_037_status": prior_037_state,
            "prior_document_rows_preserved": prior_preserved,
            "unrelated_card_fields_and_prior_documents_preserved": unchanged,
            "brand": card.get("brand"), "tnved_codes": card_tnved(card),
            "read_response_finished_at": response.get("finished_at"),
        }
        rows.append(result)
        if (not result["metadata_exact"] or not unchanged
                or result["brand"] != "Космос"
                or result["tnved_codes"] != expected.get("tnved_codes")):
            failures.append(result)

    readback = {
        "checked_at_utc": state.get("updated_at_utc"), "complete": len(rows) == 232,
        "source": "WB API readback responses recovered from the local API request journal; no marketplace writes in this step",
        "number": NUMBER, "target_cards": 232, "updated_cards": state.get("wb_update_count"),
        "verified_target_cards": len(rows) - len(failures),
        "status_counts": dict(document_status_counts),
        "existing_037_status_counts": dict(prior_037_status_counts),
        "overall_verdict_reason_counts": dict(overall_status_counts),
        "failures": failures, "cards": rows,
    }
    save(OUTPUT, readback)
    if INCOMPLETE.exists():
        failed_readback = json.loads(INCOMPLETE.read_text(encoding="utf-8"))
        failed_readback["superseded_by"] = str(OUTPUT)
        failed_readback["superseded_note"] = "The first verifier compared tuple signatures with JSON-decoded list signatures; all metadata rows were exact and WB-valid. This replacement recomputes preservation from journaled raw responses."
        save(INCOMPLETE, failed_readback)
    state.update({"phase": "verified_complete" if len(rows) == 232 and not failures else "wb_readback_incomplete",
                  "readback_path": str(OUTPUT), "verified_target_cards": readback["verified_target_cards"],
                  "wb_status_counts": dict(document_status_counts),
                  "existing_037_status_counts": dict(prior_037_status_counts),
                  "overall_verdict_reason_counts": dict(overall_status_counts),
                  "readback_failure_count": len(failures), "wb_review_left_pending": False,
                  "readback_recovered_from_api_log": True, "local_file_deleted": False,
                  "updated_at_utc": readback["checked_at_utc"]})
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": readback["verified_target_cards"],
                      "status_counts": dict(document_status_counts),
                      "existing_037_status_counts": dict(prior_037_status_counts),
                      "overall_verdict_reason_counts": dict(overall_status_counts),
                      "failure_count": len(failures), "local_file_deleted": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
