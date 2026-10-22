"""Build a fresh all-brand WB document-gap plan from complete live snapshots."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import reconcile_approved_ozon_docs_to_wb as reconcile

BASE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ozon-products", default="ozon_catalog_scoped_recheck_20261014.json")
    parser.add_argument("--ozon-certificates", default="ozon_live_recheck_20261014.json")
    parser.add_argument("--wb-cards", default="wb_live_recheck_20261014.json")
    parser.add_argument("--today", default="2026-10-14")
    parser.add_argument("--out", default="all_groups_wb_gap_plan_20261014.json")
    args = parser.parse_args()
    date.fromisoformat(args.today)

    paths = {
        "ozon_products_live.json": BASE / args.ozon_products,
        "ozon_live.json": BASE / args.ozon_certificates,
        args.wb_cards: BASE / args.wb_cards,
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    original_reader = reconcile.read_json

    def read_snapshot(name: str) -> dict:
        if name not in paths:
            return original_reader(name)
        return json.loads(paths[name].read_text())

    products_snapshot = read_snapshot("ozon_products_live.json")
    certificates_snapshot = read_snapshot("ozon_live.json")
    wb_snapshot = read_snapshot(args.wb_cards)
    if not all(x.get("complete") for x in (products_snapshot, certificates_snapshot, wb_snapshot)):
        raise RuntimeError("All three marketplace snapshots must be complete")
    reconcile.read_json = read_snapshot
    reconcile.TODAY = args.today
    plan = reconcile.plan_updates(args.wb_cards)
    catalog = products_snapshot
    brand_by_offer = {str(x.get("offer_id") or ""): x.get("brand_values") or []
                      for x in catalog.get("products") or []}

    by_document: dict[str, dict] = {}
    for row in plan["updates"]:
        for doc in row["additions"]:
            entry = by_document.setdefault(doc["number"], {"type": doc["type"], "cards": 0,
                                                               "documents": 0, "brands": set()})
            entry["cards"] += 1
            entry["documents"] += 1
            entry["brands"].update(brand_by_offer.get(row["offer_id"], []))
    for entry in by_document.values():
        entry["brands"] = sorted(entry["brands"])
    plan["all_groups_snapshot_inputs"] = {
        "ozon_products": str(paths["ozon_products_live.json"]),
        "ozon_certificates": str(paths["ozon_live.json"]),
        "wb_cards": str(paths[args.wb_cards]),
        "today_used_for_expiry": args.today,
        "wb_duplicate_nmids": wb_snapshot.get("duplicate_nmids"),
        "wb_catalog_reliable_for_global_coverage": wb_snapshot.get("duplicate_nmids") == 0,
        "note": ("Repeated nmID values were observed during WB pagination; any planned writes must be re-read by exact vendorCode before execution. This snapshot alone cannot prove complete global WB coverage."
                 if wb_snapshot.get("duplicate_nmids") else "WB pagination returned no repeated nmID values."),
    }
    plan["document_summary"] = by_document
    out = BASE / args.out
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    tmp.replace(out)
    print(json.dumps({"out": str(out), "counts": plan["counts"],
                      "missing_wb_cards": len(plan["missing_exact_wb_cards"]),
                      "blocked_conflicts": len(plan["blocked_conflicts"]),
                      "documents": by_document}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
