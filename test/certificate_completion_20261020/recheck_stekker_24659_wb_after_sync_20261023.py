#!/usr/bin/env python3
"""Read-only delayed WB readback for STEKKER declaration 24659/26."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.24659/26"
ISSUE, EXPIRY = "2026-01-22", "2031-01-21"
TARGETS = {"50282-1": "1055655750", "50283-1": "1055646340", "50284-1": "1055651057"}
OUT = HERE / "stekker_24659_wb_delayed_readback_20261023.json"


def main():
    client = Client()
    rows = []
    for offer, expected_nmid in sorted(TARGETS.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            rows.append({"offer_id": offer, "expected_nmID": expected_nmid, "card_count": len(cards),
                         "exact_metadata_visible": False, "error": "missing_or_duplicate_card"})
            continue
        card = cards[0]
        matching = [x for x in ((card.get("documents") or {}).get("items") or [])
                    if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in matching if str(x.get("type") or "") == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        rows.append({"offer_id": offer, "expected_nmID": expected_nmid,
                     "nmID": str(card.get("nmID") or ""),
                     "identity_exact": str(card.get("nmID") or "") == expected_nmid
                     and str(card.get("vendorCode") or "") == offer
                     and str(card.get("brand") or "").strip().casefold() == "stekker",
                     "brand": card.get("brand"), "title": card.get("title"),
                     "matching_number_items": matching,
                     "exact_metadata_count": len(exact), "exact_metadata_visible": len(exact) == 1,
                     "verdict": (exact[0].get("verdict") or {}) if len(exact) == 1 else None})
    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
              "target_count": len(TARGETS),
              "exact_metadata_count": sum(row.get("exact_metadata_visible") is True for row in rows),
              "identity_exact_count": sum(row.get("identity_exact") is True for row in rows),
              "rows": rows}
    verdict_counts = collections.Counter()
    for row in rows:
        if not row.get("exact_metadata_visible"):
            continue
        verdict = row.get("verdict") or {}
        if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid":
            verdict_counts["valid"] += 1
        elif verdict.get("status") in (None, 1) and verdict.get("reason") in (None, "", "valid"):
            verdict_counts["pending_or_absent"] += 1
        else:
            verdict_counts["rejected_or_invalid"] += 1
    result["verdict_counts"] = dict(verdict_counts)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
