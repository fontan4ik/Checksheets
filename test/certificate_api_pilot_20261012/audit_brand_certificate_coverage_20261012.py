"""Join current Ozon brands/documents to exact WB cards and item-level verdicts."""
from __future__ import annotations

import collections
import datetime as dt
import argparse
import json
from pathlib import Path

from reconcile_approved_ozon_docs_to_wb import norm_number, OZON_TO_WB_TYPE

BASE = Path(__file__).resolve().parent
OUT = BASE / "brand_certificate_coverage_audit_20261012.json"
TODAY = dt.datetime.now(dt.timezone.utc).date().isoformat()


def doc_key(doc: dict, wb: bool = False) -> tuple[int, str]:
    doc_type = doc.get("type") if wb else OZON_TO_WB_TYPE.get(doc.get("type_code"))
    return int(doc_type or 0), norm_number(doc.get("number", "") if wb else doc.get("certificate_number", ""))


def wb_pair_status(card: dict | None, wanted: dict) -> tuple[str, dict | None]:
    if card is None:
        return "missing_card", None
    wanted_key = (int(wanted["type"]), norm_number(wanted["number"]))
    docs = (card.get("documents") or {}).get("items") or []
    same_number = [x for x in docs if doc_key(x, wb=True) == wanted_key]
    date_exact = [x for x in same_number
                  if str(x.get("startDate") or "")[:10] == str(wanted["startDate"])[:10]
                  and str(x.get("endDate") or "")[:10] == str(wanted["endDate"])[:10]]
    if not date_exact:
        return ("date_conflict" if same_number else "missing_document"), (same_number[0] if same_number else None)
    doc = date_exact[0]
    verdict = doc.get("verdict") or {}
    card_docs = card.get("documents") or {}
    overall = card_docs.get("overallVerdict") or {}
    if (verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid"
            and card_docs.get("excludeDocuments") is False and overall.get("status") == 1
            and overall.get("isFullyChecked") is True):
        return "valid", doc
    if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid":
        return "valid_item_card_not_final", doc
    if verdict.get("verified") is False or verdict.get("status") == 2:
        return "invalid", doc
    return "pending", doc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wb-snapshot", default="wb_live.json",
                        help="Complete WB catalog snapshot, optionally with fresh full-card overlays")
    args = parser.parse_args()
    products_doc = json.loads((BASE / "ozon_products_live.json").read_text())
    brands_doc = json.loads((BASE / "ozon_brand_inventory_20261012.json").read_text())
    ozon_doc = json.loads((BASE / "ozon_live.json").read_text())
    wb_doc = json.loads((BASE / args.wb_snapshot).read_text())
    if not all(x.get("complete") for x in (products_doc, brands_doc, ozon_doc, wb_doc)):
        raise RuntimeError("Complete Ozon products, brand attributes, certificate bindings, and WB cards are required")

    products = products_doc.get("products") or []
    brand_rows = brands_doc.get("products") or []
    by_offer = {str(x.get("offer_id") or ""): x for x in products}
    brand_by_offer = {str(x.get("offer_id") or ""): str(x.get("brand") or "") for x in brand_rows}
    by_sku = {str(x.get("sku") or ""): x for x in products if x.get("sku")}
    wb_by_offer: dict[str, list[dict]] = collections.defaultdict(list)
    for card in wb_doc.get("cards") or []:
        wb_by_offer[str(card.get("vendorCode") or "")].append(card)

    product_counts = collections.Counter()
    product_with_eaeu = set()
    product_with_other_accordance = set()
    pair_counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    doc_groups: dict[tuple, dict] = {}
    binding_status_counts = collections.Counter()
    stale_bindings = 0
    duplicate_doc_records = collections.defaultdict(set)

    for p in products:
        brand = brand_by_offer.get(str(p.get("offer_id") or ""), "") or "(brand attribute absent)"
        product_counts[brand] += 1

    for cert in ozon_doc.get("certificates") or []:
        cert_type = OZON_TO_WB_TYPE.get(cert.get("type_code"))
        if cert_type is None:
            continue
        issue = str(cert.get("issue_date") or "")[:10]
        expiry = str(cert.get("expire_date") or "")[:10]
        number = str(cert.get("certificate_number") or "").strip()
        if not number or not issue or not expiry:
            continue
        accordance = cert.get("accordance_type_code")
        if (cert.get("status_code") != "approved" or expiry < TODAY or issue > TODAY):
            continue
        cert_key = (cert_type, norm_number(number), issue, expiry)
        duplicate_doc_records[cert_key].add(str(cert.get("certificate_id")))
        for binding in cert.get("live_bindings") or []:
            binding_status_counts[str(binding.get("product_status_code") or "(missing)")] += 1
            if binding.get("product_status_code") != "approved":
                continue
            sku = str(binding.get("sku") or "")
            product = by_sku.get(sku)
            if (not product or str(product.get("product_id")) != str(binding.get("product_id"))
                    or product.get("is_archived") is not False):
                stale_bindings += 1
                continue
            offer = str(product.get("offer_id") or "")
            brand = brand_by_offer.get(offer, "") or "(brand attribute absent)"
            if accordance == "EAEU":
                wanted = {"type": cert_type, "number": number, "startDate": issue, "endDate": expiry,
                          "isEndless": False}
                status = "missing_card" if len(wb_by_offer.get(offer, [])) == 0 else "duplicate_wb_cards" if len(wb_by_offer.get(offer, [])) != 1 else None
                card = wb_by_offer.get(offer, [None])[0] if len(wb_by_offer.get(offer, [])) == 1 else None
                if status is None:
                    status, _ = wb_pair_status(card, wanted)
                pair_counts[brand][status] += 1
                group = doc_groups.setdefault(cert_key, {"number": number, "type": cert_type,
                    "issue_date": issue, "expire_date": expiry, "certificate_ids": set(),
                    "targets": [], "status_counts": collections.Counter()})
                group["certificate_ids"].add(str(cert.get("certificate_id")))
                group["targets"].append({"offer_id": offer, "product_id": str(product["product_id"]),
                    "sku": sku, "brand": brand, "wb_status": status,
                    "wb_nmID": card.get("nmID") if card else None})
                group["status_counts"][status] += 1
                product_with_eaeu.add(str(product["product_id"]))
            elif accordance:
                product_with_other_accordance.add(str(product["product_id"]))

    brand_summary = []
    all_brands = sorted(set(product_counts) | set(pair_counts))
    for brand in all_brands:
        products_total = product_counts[brand]
        has_eaeu = sum(1 for offer, p in by_offer.items()
                       if (brand_by_offer.get(offer, "") or "(brand attribute absent)") == brand
                       and str(p.get("product_id")) in product_with_eaeu)
        brand_summary.append({"brand": brand, "current_ozon_products": products_total,
            "products_with_approved_current_eaeu_document": has_eaeu,
            "products_without_approved_current_eaeu_document": products_total - has_eaeu,
            "approved_eaeu_document_pairs": int(sum(pair_counts[brand].values())),
            "wb_pair_status_counts": dict(sorted(pair_counts[brand].items()))})

    serialized_groups = []
    for group in doc_groups.values():
        targets = group["targets"]
        counts = group["status_counts"]
        serialized_groups.append({"number": group["number"], "type": group["type"],
            "issue_date": group["issue_date"], "expire_date": group["expire_date"],
            "certificate_ids": sorted(group["certificate_ids"]), "target_pairs": len(targets),
            "wb_status_counts": dict(sorted(counts.items())),
            "all_targets_valid_on_wb": len(targets) > 0 and counts == {"valid": len(targets)},
            "brand_counts": dict(sorted(collections.Counter(x["brand"] for x in targets).items())),
            "targets": targets})

    summary = {
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ozon_products_checked_at": products_doc.get("checked_at"),
        "ozon_brands_checked_at": brands_doc.get("checked_at"),
        "ozon_certificates_checked_at": ozon_doc.get("checked_at"),
        "wb_cards_checked_at": wb_doc.get("checked_at"),
        "complete": True,
        "current_ozon_products": len(products),
        "ozon_brand_categories": len(product_counts),
        "current_wb_cards": len(wb_doc.get("cards") or []),
        "ozon_certificates": len(ozon_doc.get("certificates") or []),
        "unique_exact_approved_eaeu_document_pairs": sum(sum(c.values()) for c in pair_counts.values()),
        "products_with_approved_current_eaeu_document": len(product_with_eaeu),
        "products_with_approved_current_other_accordance_document": len(product_with_other_accordance),
        "stale_or_identity_mismatched_approved_bindings": stale_bindings,
        "ozon_binding_status_counts": dict(sorted(binding_status_counts.items())),
        "brand_summary": brand_summary,
        "documents": sorted(serialized_groups, key=lambda x: (x["number"], x["type"])),
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: summary[k] for k in (
        "complete", "current_ozon_products", "ozon_brand_categories", "current_wb_cards",
        "ozon_certificates", "unique_exact_approved_eaeu_document_pairs",
        "products_with_approved_current_eaeu_document", "stale_or_identity_mismatched_approved_bindings",
        "ozon_binding_status_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
