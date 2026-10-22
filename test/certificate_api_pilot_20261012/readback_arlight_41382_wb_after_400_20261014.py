"""Read-only exact-card reconciliation after WB returned HTTP 400."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import Client, now
from execute_arlight_41382_declaration_wb_20261014 import (
    NUMBER, ISSUE, EXPIRY, PLAN, OUTPUT, norm_number, wb_key,
    read_exact_wb_cards, card_doc_items, comparable,
)

BASE = Path(__file__).resolve().parent
RESULT = BASE / "arlight_41382_declaration_wb_after_400_readback_20261014.json"


def main():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    rows = [r for r in plan.get("updates", []) if any(
        int(d.get("type", 0)) == 2 and norm_number(d.get("number")) == norm_number(NUMBER)
        for d in r.get("additions", []))]
    if len(rows) != 62:
        raise RuntimeError(f"Expected 62 exact target rows, got {len(rows)}")
    client = Client()
    results = []
    for row in rows:
        cards = read_exact_wb_cards(client, row["offer_id"])
        after = cards[0] if len(cards) == 1 else None
        exact = [d for d in card_doc_items(after or {})
                 if wb_key(d) == (2, norm_number(NUMBER))
                 and str(d.get("startDate", ""))[:10] == ISSUE
                 and str(d.get("endDate", ""))[:10] == EXPIRY]
        old_docs = {wb_key(d): d for d in card_doc_items(row.get("before") or {})}
        new_docs = {wb_key(d): d for d in card_doc_items(after or {})}
        old_preserved = all(
            key in new_docs
            and str(new_docs[key].get("startDate", ""))[:10] == str(doc.get("startDate", ""))[:10]
            and str(new_docs[key].get("endDate", ""))[:10] == str(doc.get("endDate", ""))[:10]
            for key, doc in old_docs.items())
        fields_preserved = bool(after) and comparable(row.get("before") or {}) == comparable(after)
        results.append({
            "offer_id": row["offer_id"], "sku": row.get("sku"), "product_id": row.get("product_id"),
            "expected_nmID": row.get("nmID"), "actual_nmID": (after or {}).get("nmID"),
            "exact_card_count": len(cards), "declaration_visible": bool(exact),
            "unrelated_fields_match_prior_full_snapshot": fields_preserved,
            "preexisting_documents_match_prior_full_snapshot": old_preserved,
            "declaration_verdict": (exact[0].get("verdict") if exact else None),
        })
    summary = {
        "checked_at": now(), "read_only": True, "trigger": "WB HTTP 400 from prior single batch",
        "target_count": len(results), "exact_card_count": sum(r["exact_card_count"] == 1 for r in results),
        "declaration_visible_count": sum(r["declaration_visible"] for r in results),
        "unrelated_fields_match_prior_full_snapshot_count": sum(r["unrelated_fields_match_prior_full_snapshot"] for r in results),
        "preexisting_documents_match_prior_full_snapshot_count": sum(r["preexisting_documents_match_prior_full_snapshot"] for r in results),
        "verdict_counts": {str(v): sum(r["declaration_verdict"] == v for r in results)
                           for v in {str(r["declaration_verdict"]) for r in results}},
        "results": results,
    }
    RESULT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
