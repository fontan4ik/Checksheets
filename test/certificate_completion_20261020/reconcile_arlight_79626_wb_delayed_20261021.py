"""Read-only delayed verification after WB's successful 79626/26 update."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, doc_key, norm_number  # noqa: E402

PREFLIGHT = HERE / "arlight_79626_preflight_live_20261021.json"
STATE = HERE / "arlight_79626_wb_execution_20261021.json"
BEFORE = HERE / "arlight_79626_wb_before_20261021.json"
READBACK = HERE / "arlight_79626_wb_delayed_readback_20261021.json"
NUMBER = "ЕАЭС N RU Д-CN.РА03.В.79626/26"
ISSUE = "2026-04-29"
EXPIRY = "2031-04-27"


def signatures(items: list[dict]) -> list[tuple]:
    return [(doc_key(x), str(x.get("startDate", ""))[:10],
             str(x.get("endDate", ""))[:10], bool(x.get("isEndless"))) for x in items]


def status(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "", "valid"):
        return "rejected_or_invalid"
    return "pending_or_no_verdict"


def main() -> None:
    pre = json.loads(PREFLIGHT.read_text())
    before_data = json.loads(BEFORE.read_text())
    state = json.loads(STATE.read_text())
    safe = {str(x["offer_id"]): x for x in pre["wb_targets"] if x.get("safe_for_update") is True}
    before = {str(x.get("vendorCode")): x for x in before_data.get("cards") or []}
    if (len(safe) != 70 or len(before) != 70
            or state.get("phase") != "wb_readback_incomplete"
            or state.get("writes_sent") != 1):
        raise RuntimeError("unexpected_wb_reconciliation_artifacts")

    client = Client()
    rows = []
    statuses = collections.Counter()
    failures = []
    for offer, expected in sorted(safe.items()):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "card_count_changed", "card_count": len(cards)})
            continue
        card = cards[0]
        raw_docs = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in raw_docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if int(x.get("type") or 0) == 2
                 and str(x.get("startDate", ""))[:10] == ISSUE
                 and str(x.get("endDate", ""))[:10] == EXPIRY
                 and x.get("isEndless") is False]
        old_card = before[offer]
        prior_docs = (old_card.get("documents") or {}).get("items") or []
        prior = signatures(prior_docs)
        current = signatures(raw_docs)
        preserved = (comparable_card(card) == comparable_card(old_card)
                     and all(x in current for x in prior))
        problem = None
        if (str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or str(card.get("vendorCode") or "") != offer
                or str(card.get("brand") or "").strip().casefold() != "arlight"):
            problem = "card_identity_changed"
        elif len(same) != 1 or len(exact) != 1:
            problem = "document_missing_or_metadata_conflict"
        elif not preserved:
            problem = "prior_docs_or_unrelated_fields_changed"
        doc_status = status(exact[0]) if len(exact) == 1 else "missing_or_conflicting"
        statuses[doc_status] += 1
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "exact_document_count": len(same), "metadata_exact": len(exact) == 1,
               "prior_documents_and_unrelated_fields_preserved": preserved,
               "document_status": doc_status,
               "verdict": exact[0].get("verdict") if len(exact) == 1 else None,
               "problem": problem}
        rows.append(row)
        if problem:
            failures.append(row)

    result = {"checked_at": now(), "complete": len(rows) == 70, "number": NUMBER,
              "target_cards": 70, "verified_target_cards": len(rows) - len(failures),
              "status_counts": dict(statuses), "failures": failures,
              "cards": rows, "wb_review_left_pending": True}
    tmp = READBACK.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    tmp.replace(READBACK)
    if failures or len(rows) != 70:
        state.update(phase="wb_readback_incomplete", failure_count=len(failures), updated_at=now())
        state_tmp = STATE.with_suffix(".tmp")
        state_tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        state_tmp.replace(STATE)
        raise RuntimeError("wb_readback_still_incomplete")
    state.update(phase="verified_complete", readback_path=str(READBACK),
                 verified_target_cards=70, wb_status_counts=dict(statuses),
                 wb_review_left_pending=True, local_file_deleted=False, updated_at=now())
    state_tmp = STATE.with_suffix(".tmp")
    state_tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    state_tmp.replace(STATE)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": 70,
                      "status_counts": dict(statuses), "failures": failures,
                      "wb_review_left_pending": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
