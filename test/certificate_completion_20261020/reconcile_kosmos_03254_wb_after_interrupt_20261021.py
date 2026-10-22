"""Read-only reconciliation after WB accepted the 03254/23 update batch."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number,
)

PREFLIGHT = HERE / "kosmos_03254_wb_preflight_live_20261021.json"
STATE = HERE / "kosmos_03254_wb_execution_20261021.json"
BEFORE = HERE / "kosmos_03254_wb_before_20261021.json"
READBACK = HERE / "kosmos_03254_wb_readback_20261021.json"
NUMBER = "ЕАЭС RU С-CN.НВ93.В.03254/23"
ISSUE = "2023-05-19"
EXPIRY = "2028-05-18"
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


def signature(row: dict) -> tuple:
    return (doc_key(row), str(row.get("startDate", ""))[:10],
            str(row.get("endDate", ""))[:10], bool(row.get("isEndless")))


def status(row: dict) -> str:
    verdict = row.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True:
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    if READBACK.exists():
        raise RuntimeError("readback_already_exists; inspect before retry")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("phase") != "wb_update_response" or state.get("writes_sent") != 1 or state.get("wb_response_error") is not False:
        raise RuntimeError("no_confirmed_successful_wb_write_to_reconcile")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    targets = {str(row["offer_id"]): row for row in pre.get("cards") or []}
    prior = {str(row["offer_id"]): row for row in before.get("cards") or []}
    if len(targets) != 232 or len(prior) != 232:
        raise RuntimeError("reconciliation_artifacts_do_not_cover_232_cards")
    client = Client()
    rows = []
    failures = []
    status_counts = collections.Counter()
    prior_037_status = collections.Counter()
    for index, (offer, expected) in enumerate(sorted(targets.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count_changed", "count": len(cards)})
            continue
        card = cards[0]
        docs_container = card.get("documents") or {}
        docs = docs_container.get("items") or []
        exact = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        exact_meta = [doc for doc in exact if doc_key(doc) == doc_key(TARGET_DOC)
                      and str(doc.get("startDate", ""))[:10] == ISSUE
                      and str(doc.get("endDate", ""))[:10] == EXPIRY
                      and doc.get("isEndless") is False]
        prior_037 = [doc for doc in docs if norm_number(doc.get("number")) ==
                     norm_number("ЕАЭС N RU Д-CN.РА06.В.78454/22")]
        if len(prior_037) == 1:
            prior_037_status[status(prior_037[0])] += 1
        else:
            prior_037_status["missing_or_ambiguous"] += 1
        row = {
            "offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "exact_document_count": len(exact), "metadata_exact": len(exact_meta) == 1,
            "document_status": status(exact_meta[0]) if len(exact_meta) == 1 else "readback_missing_or_conflicting",
            "verdict": exact_meta[0].get("verdict") if len(exact_meta) == 1 else None,
            "overall_verdict": docs_container.get("overallVerdict"),
            "brand": card.get("brand"), "tnved_codes": card_tnved(card),
            "existing_037_status": status(prior_037[0]) if len(prior_037) == 1 else "missing_or_ambiguous",
        }
        old = prior[offer]
        unchanged = (str(card.get("vendorCode") or "") == offer
                     and str(card.get("nmID") or "") == str(old.get("nmID") or "")
                     and comparable_card(card) == comparable_card(old.get("card") or {}))
        after_sigs = [signature(doc) for doc in copy_documents(card)]
        unchanged = unchanged and all(sig in after_sigs for sig in old.get("prior_document_signatures") or [])
        row["unrelated_card_fields_and_prior_documents_preserved"] = unchanged
        status_counts[row["document_status"]] += 1
        rows.append(row)
        if (not row["metadata_exact"] or not unchanged
                or str(card.get("brand") or "").strip().casefold() != "космос"
                or card_tnved(card) != expected.get("tnved_codes")):
            failures.append(row)
        if index % 40 == 0 or index == len(targets):
            print(f"WB read-only reconciliation {index}/{len(targets)}", flush=True)

    result = {
        "checked_at_utc": now(), "complete": len(rows) == len(targets),
        "number": NUMBER, "target_cards": len(targets), "updated_cards": state.get("wb_update_count"),
        "verified_target_cards": len(rows) - len(failures),
        "status_counts": dict(status_counts), "existing_037_status_counts": dict(prior_037_status),
        "failures": failures,
        "wb_review_left_pending": all(row["document_status"] == "pending_review_or_verdict_missing" for row in rows),
        "cards": rows,
    }
    save(READBACK, result)
    state.update({"phase": "verified_complete" if not failures and len(rows) == len(targets) else "wb_readback_incomplete",
                  "readback_path": str(READBACK), "verified_target_cards": result["verified_target_cards"],
                  "wb_status_counts": dict(status_counts),
                  "existing_037_status_counts": dict(prior_037_status),
                  "wb_review_left_pending": result["wb_review_left_pending"],
                  "readback_failure_count": len(failures), "updated_at_utc": now(),
                  "local_file_deleted": False})
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": result["verified_target_cards"],
                      "status_counts": dict(status_counts), "existing_037_status_counts": dict(prior_037_status),
                      "failure_count": len(failures), "wb_review_left_pending": result["wb_review_left_pending"],
                      "local_file_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
