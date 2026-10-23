#!/usr/bin/env python3
"""Summarize confirmed source-document assignments for Ozon products lacking a current approved document."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import re
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPSHOT = HERE / "live_marketplaces_snapshot_normalized_20261023.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "confirmed_source_gaps_audit_resume_20261023.json"


def norm(value: object) -> str:
    return "".join(c for c in str(value or "").upper() if c.isalnum())


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists_inspect_first")
    snap = json.loads(SNAPSHOT.read_text())
    if not all(snap.get(k, {}).get("complete") is True for k in
               ("ozon_products", "ozon_certificates", "wb_catalog")):
        raise RuntimeError("complete_marketplace_snapshot_required")
    products = snap["ozon_products"]["products"]
    by_sku = {str(p.get("sku")): p for p in products if p.get("sku")}
    today = date.today().isoformat()
    covered = set()
    for cert in snap["ozon_certificates"]["certificates"]:
        if (cert.get("status_code") != "approved"
                or str(cert.get("issue_date") or "")[:10] > today
                or str(cert.get("expire_date") or "")[:10] < today
                or not str(cert.get("expire_date") or "")[:10]):
            continue
        for b in cert.get("live_bindings") or []:
            product = by_sku.get(str(b.get("sku") or ""))
            if (b.get("product_status_code") == "approved" and product
                    and str(product.get("product_id")) == str(b.get("product_id"))):
                covered.add(str(product.get("product_id")))
    active_products = [p for p in products if not p.get("is_archived")]
    products_by_offer = collections.defaultdict(list)
    for product in active_products:
        products_by_offer[str(product.get("offer_id"))].append(product)
    uncovered_product_ids = {str(p.get("product_id")) for p in active_products
                             if str(p.get("product_id")) not in covered}
    uncovered_offers = {offer for offer, rows in products_by_offer.items()
                        if any(str(p.get("product_id")) in uncovered_product_ids for p in rows)}
    groups = {}
    totals = collections.Counter()
    hash_cache = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            applicability = str(row.get("Применимость") or "").strip()
            if applicability not in ("Подтверждено статусом покрытия", "Подтверждено источником"):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer not in uncovered_offers:
                continue
            totals[applicability] += 1
            brand = str(row.get("Бренд подтвержденный") or "").strip()
            number = str(row.get("Номер/название документа") or "").strip()
            kind = str(row.get("Тип документа") or "").strip()
            source_file = str(row.get("Локальный файл") or "").strip()
            source_path = (ROOT / source_file).resolve() if source_file else None
            declared_sha = str(row.get("SHA256 фактический") or row.get("SHA256 заявленный") or "").strip()
            exists = bool(source_path and source_path.is_file())
            actual_sha = ""
            if exists:
                if source_path not in hash_cache:
                    hash_cache[source_path] = hashlib.sha256(source_path.read_bytes()).hexdigest()
                actual_sha = hash_cache[source_path]
            key = (brand, kind, norm(number), source_file, declared_sha)
            group = groups.setdefault(key, {
                "brand": brand, "document_type": kind, "document_number": number,
                "offers": set(), "applicability_counts": collections.Counter(),
                "validity_examples": set(), "scope_examples": set(), "source_urls": set(),
                "source_file": source_file, "source_exists": exists,
                "declared_sha256": declared_sha, "actual_sha256": actual_sha,
                "sha256_matches": bool(exists and declared_sha and actual_sha == declared_sha),
            })
            group["offers"].add(offer)
            group["applicability_counts"][applicability] += 1
            group["validity_examples"].add(str(row.get("Сроки/валидность") or ""))
            group["scope_examples"].add(str(row.get("Основание сопоставления") or ""))
            group["source_urls"].add(str(row.get("URL документа") or ""))
    rows = []
    for g in groups.values():
        rows.append({**{k: v for k, v in g.items() if k not in (
            "offers", "applicability_counts", "validity_examples", "scope_examples", "source_urls")},
            "missing_ozon_offers": len(g["offers"]),
            "offer_examples": sorted(g["offers"])[:20],
            "applicability_counts": dict(g["applicability_counts"]),
            "validity_examples": sorted(g["validity_examples"])[:5],
            "scope_examples": sorted(g["scope_examples"])[:5],
            "source_urls": sorted(x for x in g["source_urls"] if x)[:5]})
    rows.sort(key=lambda x: (-x["missing_ozon_offers"], x["brand"], x["document_number"]))
    result = {"checked_at_utc": date.today().isoformat(), "snapshot_checked_at": snap["ozon_products"].get("checked_at"),
              "read_only": True, "active_ozon_products": len(active_products),
              "active_ozon_products_with_current_approved_document": len(covered),
              "active_ozon_products_without_current_approved_document": len(uncovered_product_ids),
              "active_ozon_offers_with_at_least_one_uncovered_product": len(uncovered_offers),
              "uncovered_products_with_confirmed_source_assignment_rows": sum(totals.values()),
              "confirmed_assignment_rows_by_applicability": dict(totals),
              "candidate_source_groups": rows,
              "limitations": "A confirmed source row is a lead, not proof that each assignment should be uploaded; inspect official scope, active status, exact current model and TN VED before any marketplace write."}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in (
        "active_ozon_products", "active_ozon_products_without_current_approved_document",
        "active_ozon_offers_with_at_least_one_uncovered_product",
        "uncovered_products_with_confirmed_source_assignment_rows", "confirmed_assignment_rows_by_applicability")},
        ensure_ascii=False, indent=2))
    for row in rows[:40]:
        print(json.dumps({k: row[k] for k in (
            "brand", "document_type", "document_number", "missing_ozon_offers", "source_exists",
            "sha256_matches", "validity_examples", "source_file")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
