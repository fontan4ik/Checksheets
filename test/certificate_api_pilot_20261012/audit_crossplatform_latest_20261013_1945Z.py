"""Refresh Ozon certificate metadata, then join live bindings to latest full catalogs."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import BASE, Client, now, save
from audit_brand_certificate_coverage_recheck_20261013 import wb_pair_status
from reconcile_approved_ozon_docs_to_wb import OZON_TO_WB_TYPE, norm_number

OUT = "crossplatform_latest_recheck_20261013_1945Z.json"


def main() -> None:
    client = Client()
    certificates = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("Malformed Ozon certificate listing")
        certificates.extend(rows)
        if len(rows) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination limit exceeded")
    cert_ids = [str(x.get("certificate_id") or "") for x in certificates]
    if not all(cert_ids) or len(cert_ids) != len(set(cert_ids)):
        raise RuntimeError("Ozon certificate IDs are missing or duplicated")

    binding_doc = json.loads((BASE / "ozon_global_certificate_binding_recheck_20261013_1831Z.json").read_text())
    products_doc = json.loads((BASE / "ozon_products_recheck_20261013_1828Z.json").read_text())
    attrs_doc = json.loads((BASE / "ozon_brand_tnved_inventory_recheck_20261013_1828Z.json").read_text())
    wb_doc = json.loads((BASE / "wb_live_recheck_20261013_1828Z.json").read_text())
    if not all(x.get("complete") for x in (binding_doc, products_doc, attrs_doc, wb_doc)):
        raise RuntimeError("A required complete platform snapshot is missing")
    by_binding = {str(x.get("certificate_id")): x for x in binding_doc.get("records") or []}
    if set(by_binding) != set(cert_ids):
        raise RuntimeError("Ozon metadata and binding snapshots have different certificate IDs")

    products = products_doc.get("products") or []
    attrs = attrs_doc.get("products") or []
    if len(products) != 21244 or len(attrs) != 21244 or len(wb_doc.get("cards") or []) != 19962:
        raise RuntimeError("Current catalog row counts differ from the audited complete snapshots")
    by_sku = {str(x.get("sku") or ""): x for x in products if x.get("sku")}
    if len(by_sku) != len([x for x in products if x.get("sku")]):
        raise RuntimeError("Current Ozon catalog contains duplicate SKU identity")
    attr_by_offer = {str(x.get("offer_id") or ""): x for x in attrs}
    if len(attr_by_offer) != len(attrs):
        raise RuntimeError("Current Ozon attribute inventory contains duplicate offer")
    brand_by_offer = {offer: str((next((v.get("value") for v in (next((a for a in row.get("attributes") or [] if str(a.get("id")) == "85"), {}) or {}).get("values") or []), "") or ""))
                      for offer, row in attr_by_offer.items()}
    wb_by_offer: dict[str, list[dict]] = collections.defaultdict(list)
    for card in wb_doc.get("cards") or []:
        wb_by_offer[str(card.get("vendorCode") or "")].append(card)

    today = "2026-10-13"
    pair_counts = collections.Counter()
    binding_status_counts = collections.Counter()
    doc_groups: dict[tuple, dict] = {}
    product_with_eaeu = set()
    product_with_other = set()
    stale_bindings = 0
    seen_wb_nmids = [str(x.get("nmID") or "") for x in wb_doc.get("cards") or []]
    duplicate_nmids = [k for k, v in collections.Counter(seen_wb_nmids).items() if not k or v > 1]

    for cert in certificates:
        type_id = OZON_TO_WB_TYPE.get(cert.get("type_code"))
        if type_id is None:
            continue
        issue = str(cert.get("issue_date") or "")[:10]
        expiry = str(cert.get("expire_date") or "")[:10]
        number = str(cert.get("certificate_number") or "").strip()
        if not number or not issue or not expiry or expiry < today or issue > today:
            continue
        if cert.get("status_code") != "approved":
            continue
        rec = by_binding[str(cert["certificate_id"])]
        if (str(rec.get("certificate_number") or "").strip() != number
                or str(rec.get("status_code") or "") != str(cert.get("status_code") or "")
                or str(rec.get("issue_date") or "")[:10] != issue
                or str(rec.get("expire_date") or "")[:10] != expiry):
            raise RuntimeError(f"Ozon metadata and binding record conflict for certificate_id={cert['certificate_id']}")
        for binding in rec.get("bindings") or []:
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
            if cert.get("accordance_type_code") == "EAEU":
                wanted = {"type": type_id, "number": number, "startDate": issue,
                          "endDate": expiry, "isEndless": False}
                cards = wb_by_offer.get(offer, [])
                if not cards:
                    status, card = "missing_card", None
                elif len(cards) != 1:
                    status, card = "duplicate_wb_cards", None
                else:
                    card = cards[0]
                    status, _ = wb_pair_status(card, wanted)
                pair_counts[(brand, status)] += 1
                group_key = (type_id, norm_number(number), issue, expiry)
                group = doc_groups.setdefault(group_key, {"number": number, "type": type_id,
                    "issue_date": issue, "expire_date": expiry, "certificate_ids": set(),
                    "targets": [], "status_counts": collections.Counter(), "brand_counts": collections.Counter()})
                group["certificate_ids"].add(str(cert["certificate_id"]))
                group["status_counts"][status] += 1
                group["brand_counts"][brand] += 1
                group["targets"].append({"offer_id": offer, "product_id": str(product["product_id"]),
                    "sku": sku, "brand": brand, "wb_status": status,
                    "wb_nmID": card.get("nmID") if card else None})
                product_with_eaeu.add(str(product["product_id"]))
            elif cert.get("accordance_type_code"):
                product_with_other.add(str(product["product_id"]))

    docs = []
    for g in doc_groups.values():
        docs.append({"number": g["number"], "type": g["type"], "issue_date": g["issue_date"],
            "expire_date": g["expire_date"], "certificate_ids": sorted(g["certificate_ids"]),
            "target_pairs": len(g["targets"]), "wb_status_counts": dict(sorted(g["status_counts"].items())),
            "brand_counts": dict(sorted(g["brand_counts"].items())), "targets": g["targets"]})
    serialized = {k: [{**x, **({"live_bindings": by_binding[str(x["certificate_id"])].get("bindings") or []})}
                      for x in certificates if str(x.get("certificate_id")) == k]
                  for k in []}
    summary = {"checked_at_utc": now(), "read_only": True, "complete": True,
        "ozon_certificate_list_count": len(certificates), "ozon_certificate_list_pages": page,
        "ozon_bindings_checked_at_utc": binding_doc.get("finished_at_utc"),
        "ozon_products_checked_at_utc": products_doc.get("checked_at"),
        "ozon_brand_tnved_checked_at_utc": attrs_doc.get("checked_at"),
        "wb_catalog_checked_at_utc": wb_doc.get("checked_at"),
        "current_ozon_products": len(products), "current_wb_cards": len(wb_doc["cards"]),
        "wb_duplicate_nmids": duplicate_nmids, "stale_identity_mismatched_approved_bindings": stale_bindings,
        "ozon_binding_status_counts": dict(sorted(binding_status_counts.items())),
        "approved_current_eaeu_pairs": sum(pair_counts.values()),
        "current_products_with_approved_eaeu_doc": len(product_with_eaeu),
        "current_products_with_other_accordance_doc": len(product_with_other),
        "brand_pair_status_counts": {b: dict(sorted({s:n for (bb,s),n in pair_counts.items() if bb==b}.items()))
                                     for b in sorted({x[0] for x in pair_counts})},
        "documents": sorted(docs, key=lambda x: (x["number"], x["type"]))}
    save(OUT, summary)
    wb_statuses = collections.Counter(s for _, s in pair_counts.elements())
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": summary["checked_at_utc"],
        "certificate_count": len(certificates), "current_products": len(products), "wb_cards": len(wb_doc["cards"]),
        "binding_status_counts": summary["ozon_binding_status_counts"],
        "approved_eaeu_pairs": summary["approved_current_eaeu_pairs"],
        "wb_statuses": dict(wb_statuses), "stale_bindings": stale_bindings,
        "duplicate_wb_nmids": len(duplicate_nmids),
        "missing_document_groups": [d for d in docs if d["wb_status_counts"].get("missing_document")],
        "top_pending": sorted([d for d in docs if d["wb_status_counts"].get("pending")],
                              key=lambda x: x["wb_status_counts"]["pending"], reverse=True)[:5]},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
