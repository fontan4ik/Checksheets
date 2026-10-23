#!/usr/bin/env python3
"""Merge fresh all-brand marketplace snapshots and confirmed WB readbacks."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRODUCTS = HERE / "all_found_ozon_products_snapshot_20261014.json"
CERTS = HERE / "all_found_ozon_certificates_snapshot_20261014.json"
WB = HERE / "all_found_wb_cards_snapshot_20261014.json"
IMMEDIATE = HERE / "all_found_wb_readback_7e2263c3d25893a4.json"
DELAYED = HERE / "all_found_wb_delayed_readback_20261023.json"
FULL_SNAPSHOT = HERE / "live_marketplaces_snapshot_fresh_reconciled_20261023.json"
OUT = HERE / "live_marketplaces_snapshot_allbrand_postreconcile_final_20261023.json"
REPORT_SCRIPT = HERE / "_build_allbrand_coverage_final_worker_20261023.py"
GAPS_SCRIPT = HERE / "_audit_allbrand_source_gaps_final_worker_20261023.py"


def read(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    products, certs, wb, immediate, delayed, full = map(
        read, (PRODUCTS, CERTS, WB, IMMEDIATE, DELAYED, FULL_SNAPSHOT))
    if not all(x.get("complete") is True for x in (products, certs, wb)):
        raise RuntimeError("incomplete_fresh_marketplace_snapshots")
    if delayed.get("read_only") is not True or delayed.get("visible_exact_document_count") != 17:
        raise RuntimeError("delayed_readback_incomplete")

    cards = wb.get("cards") or []
    by_offer = {}
    for i, card in enumerate(cards):
        offer = str(card.get("vendorCode") or "")
        if offer:
            by_offer.setdefault(offer, []).append(i)
    refreshed = {}
    for row in immediate.get("results") or []:
        if row.get("expected_docs_visible") is True and len(row.get("cards") or []) == 1:
            refreshed[str(row["offer_id"])] = row["cards"][0]
    for row in delayed.get("rows") or []:
        if row.get("expected_documents_visible") is True and len(row.get("fresh_cards") or []) == 1:
            refreshed[str(row["offer_id"])] = row["fresh_cards"][0]
    if len(refreshed) != 75:
        raise RuntimeError(f"visible_card_readbacks_not_75:{len(refreshed)}")
    for offer, card in refreshed.items():
        positions = by_offer.get(offer, [])
        if len(positions) != 1 or str(cards[positions[0]].get("nmID")) != str(card.get("nmID")):
            raise RuntimeError("wb_snapshot_identity_missing_or_ambiguous:" + offer)
        cards[positions[0]] = card

    cert_rows = certs.get("certificates") or []
    products["active_products"] = len(products.get("products") or []) + int(
        (full.get("ozon_products") or {}).get("missing_sku") or 0)
    products["archived_products"] = (full.get("ozon_products") or {}).get("archived_products", 0)
    products["missing_sku"] = (full.get("ozon_products") or {}).get("missing_sku")
    certs["records"] = len(cert_rows)
    certs["status_counts"] = dict(__import__("collections").Counter(
        str(x.get("status_code") or "unknown") for x in cert_rows))
    certs["total_bindings"] = sum(len(x.get("live_bindings") or []) for x in cert_rows)
    snapshot = {
        "started_at": wb.get("checked_at"),
        "ozon_products": products,
        "ozon_certificates": certs,
        "wb_catalog": {"complete": True, "checked_at": delayed["checked_at_utc"],
                       "raw_card_rows": wb.get("raw_rows"),
                       "unique_cards": len(cards), "cards": cards},
        "wb_trash": {"complete": False, "excluded_from_scope": True, "cards": []},
        "updated_at": delayed["checked_at_utc"],
        "finished_at": delayed["checked_at_utc"],
        "complete": True,
        "merged_wb_readback": {
            "initial_readback_at": immediate["checked_at"],
            "delayed_readback_at": delayed["checked_at_utc"],
            "cards_confirmed": len(refreshed),
            "initially_visible_cards": sum(bool(x.get("expected_docs_visible")) for x in immediate["results"]),
            "delayed_sync_cards": delayed["visible_exact_document_count"],
            "review_left_pending": True,
        },
    }
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    coverage = (HERE / "_build_current_coverage_report_fresh_worker_20261023.py").read_text(encoding="utf-8")
    coverage = coverage.replace('live_marketplaces_snapshot_fresh_reconciled_20261023.json', OUT.name)
    coverage = coverage.replace('current_coverage_report_fresh_20261023.json', 'current_coverage_report_allbrand_postreconcile_final_20261023.json')
    coverage = coverage.replace('verified_group_edges_current_fresh_20261023.csv', 'verified_group_edges_allbrand_postreconcile_final_20261023.csv')
    coverage = coverage.replace(
        'ROOT / "test/certificate_api_pilot_20261012/all_source_certificates_verified_manifest_20261014.json"',
        'HERE / "approved_crossplatform_reconcile_manifest_20261023.json"')
    REPORT_SCRIPT.write_text(coverage, encoding="utf-8")

    gaps = (HERE / "audit_confirmed_source_gaps_postwrite_20261023.py").read_text(encoding="utf-8")
    gaps = gaps.replace('live_marketplaces_snapshot_postwrite_ozon_20261023.json', OUT.name)
    gaps = gaps.replace('confirmed_source_gaps_audit_postwrite_20261023.json', 'confirmed_source_gaps_allbrand_postreconcile_final_20261023.json')
    GAPS_SCRIPT.write_text(gaps, encoding="utf-8")

    print(json.dumps({"snapshot": str(OUT), "merged_wb_cards": len(refreshed),
                      "report_script": str(REPORT_SCRIPT), "gaps_script": str(GAPS_SCRIPT)}, ensure_ascii=False))
    subprocess.run([sys.executable, str(REPORT_SCRIPT)], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(GAPS_SCRIPT)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
