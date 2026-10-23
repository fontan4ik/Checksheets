#!/usr/bin/env python3
"""Reconcile only equivalent WB pagination duplicates in the latest live snapshot."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = HERE / "live_marketplaces_snapshot_latest_20261023.json"
OUT = HERE / "live_marketplaces_snapshot_latest_reconciled_20261023.json"
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from run_all_found_certificates_20261014 import deduplicate_equivalent_wb_rows  # noqa: E402


def main() -> None:
    if OUT.exists():
        raise RuntimeError("reconciled_snapshot_exists_inspect_before_replacing")
    data = json.loads(RAW.read_text(encoding="utf-8"))
    for key in ("ozon_products", "ozon_certificates"):
        if data.get(key, {}).get("complete") is not True:
            raise RuntimeError(f"source_section_incomplete:{key}")
    wb = data.get("wb_catalog") or {}
    raw_cards = wb.get("cards") or []
    if len(raw_cards) != wb.get("cards_read") or wb.get("pages") != 200:
        raise RuntimeError("raw_wb_pagination_not_complete")
    if len(raw_cards) != 20_083:
        raise RuntimeError(f"unexpected_raw_wb_card_count:{len(raw_cards)}")

    cards, duplicates = deduplicate_equivalent_wb_rows(raw_cards)
    nmids = [str(card.get("nmID") or "") for card in cards]
    if duplicates != 121 or len(cards) != 19_962 or any(not value for value in nmids):
        raise RuntimeError(f"unexpected_equivalent_duplicate_reconciliation:{duplicates}:{len(cards)}")
    if len(nmids) != len(set(nmids)):
        raise RuntimeError("unresolved_wb_nmID_duplicates")

    checked_at = str(data.get("updated_at") or "")
    if not checked_at:
        raise RuntimeError("raw_snapshot_timestamp_missing")
    data["raw_snapshot"] = str(RAW)
    data["complete"] = True
    data["wb_catalog"] = {
        "complete": True,
        "checked_at": checked_at,
        "pages": wb["pages"],
        "raw_card_rows": len(raw_cards),
        "equivalent_duplicate_rows_removed": duplicates,
        "unique_cards": len(cards),
        "cards": cards,
    }
    data["wb_trash"] = {"complete": False, "excluded_from_scope": True}
    data["reconciliation"] = {
        "read_only": True,
        "method": "deduplicate_equivalent_wb_rows; equivalent cards only",
        "raw_wb_rows": len(raw_cards),
        "equivalent_duplicates_removed": duplicates,
        "unique_wb_cards": len(cards),
        "nmID_conflicts_remaining": 0,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"complete": True, "raw_wb_rows": len(raw_cards),
                      "equivalent_duplicates_removed": duplicates,
                      "unique_wb_cards": len(cards), "nmID_conflicts_remaining": 0,
                      "output": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
