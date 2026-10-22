"""Reconcile WB cards that became visible after the first post-write readback."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number,
)

STATE = HERE / "stekker_15150_wb_execution_20261021.json"
BEFORE = HERE / "stekker_15150_wb_before_20261021.json"
READBACK = HERE / "stekker_15150_wb_readback_20261021.json"
SETTLEMENT = HERE / "stekker_15150_wb_delayed_settlement_20261021.json"
NUMBER = "ЕАЭС N RU Д-CN.РА07.В.15150/25"
ISSUE = "2025-08-25"
EXPIRY = "2030-08-24"
DESIRED = {"type": 2, "number": NUMBER,
           "startDate": ISSUE + "T00:00:00Z", "endDate": EXPIRY + "T00:00:00Z",
           "isEndless": False}


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def status(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "", "valid"):
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def save(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if SETTLEMENT.exists():
        raise RuntimeError("settlement_exists_reconcile_before_retry")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    readback = json.loads(READBACK.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    if (state.get("phase") != "wb_readback_incomplete" or readback.get("complete") is not True
            or not readback.get("failures") or before.get("complete") is not True):
        raise RuntimeError("delayed_readback_precondition_failed")
    prior_by_offer = {str(card.get("vendorCode")): card for card in before.get("cards") or []}
    client = Client()
    rows = []
    for failed in readback["failures"]:
        offer = str(failed["offer_id"])
        old = prior_by_offer.get(offer)
        cards = client.wb_cards(offer)
        if len(cards) != 1 or old is None:
            rows.append({"offer_id": offer, "verified": False,
                         "reason": "missing_or_duplicate_card_or_before_snapshot"})
            continue
        card = cards[0]
        raw_docs = ((card.get("documents") or {}).get("items") or [])
        same = [doc for doc in raw_docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        exact = [doc for doc in same if doc_key(doc) == doc_key(DESIRED)
                 and str(doc.get("startDate", ""))[:10] == ISSUE
                 and str(doc.get("endDate", ""))[:10] == EXPIRY
                 and doc.get("isEndless") is False]
        old_docs = copy_documents(old)
        after_docs = copy_documents(card)
        after_sigs = collections.Counter(signature(doc) for doc in after_docs)
        old_sigs = collections.Counter(signature(doc) for doc in old_docs)
        preserved = comparable_card(card) == comparable_card(old) and all(
            after_sigs[sig] >= count for sig, count in old_sigs.items())
        okay = (str(card.get("vendorCode") or "") == offer
                and str(card.get("nmID") or "") == str(failed.get("nmID") or "")
                and str(card.get("brand") or "").strip().casefold() == "stekker"
                and len(same) == 1 and len(exact) == 1 and preserved)
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "verified": okay, "document_status": status(exact[0]) if len(exact) == 1 else "missing_or_conflicting",
                     "verdict": exact[0].get("verdict") if len(exact) == 1 else None,
                     "prior_docs_and_unrelated_fields_preserved": preserved})
    if any(not row.get("verified") for row in rows):
        save(SETTLEMENT, {"checked_at": now(), "complete": False, "number": NUMBER,
                          "settled_cards": rows, "prior_readback_failures": len(readback["failures"])})
        raise RuntimeError("delayed_wb_readback_still_incomplete")

    row_by_offer = {row["offer_id"]: row for row in readback["cards"]}
    supplemental = {row["offer_id"]: row for row in rows}
    for offer, row in supplemental.items():
        row_by_offer[offer] = {"offer_id": offer, "nmID": row["nmID"],
                               "document_exact": True,
                               "prior_docs_and_unrelated_fields_preserved": row["prior_docs_and_unrelated_fields_preserved"],
                               "document_status": row["document_status"], "verdict": row["verdict"]}
    merged = [row_by_offer[offer] for offer in sorted(row_by_offer)]
    counts = collections.Counter(row["document_status"] for row in merged)
    final_failures = [row for row in merged if not row.get("document_exact")
                      or not row.get("prior_docs_and_unrelated_fields_preserved")]
    save(SETTLEMENT, {"checked_at": now(), "complete": not final_failures,
                      "number": NUMBER, "delayed_settlement_cards": rows,
                      "initial_readback_count": len(readback["cards"]),
                      "late_cards_now_exact": len(rows), "status_counts": dict(counts),
                      "repeated_marketplace_write": False})
    readback.update(checked_at=now(), complete=not final_failures,
                    verified_target_cards=len(merged) - len(final_failures),
                    failures=final_failures, status_counts=dict(counts), cards=merged,
                    delayed_settlement_path=str(SETTLEMENT), wb_review_left_pending=True)
    save(READBACK, readback)
    if final_failures or len(merged) != 303:
        state.update(phase="wb_readback_incomplete_after_settlement", failure_count=len(final_failures),
                     updated_at=now())
        save(STATE, state)
        raise RuntimeError("wb_final_settlement_incomplete")
    state.update(phase="verified_complete", readback_path=str(READBACK),
                 verified_target_cards=len(merged), wb_status_counts=dict(counts),
                 wb_review_left_pending=True, delayed_settlement_count=len(rows),
                 local_file_deleted=False, updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": len(merged),
                      "delayed_settlement_cards": len(rows), "status_counts": dict(counts),
                      "review_left_pending": True, "source_pdf_deleted": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
