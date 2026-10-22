"""Read-only refresh of the exact Saffit SSL10 marketplace targets."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import BASE, Client, now, save

PREFLIGHT = BASE / "saffit_ssl10_live_preflight_20261013.json"
OUT = "saffit_01893_live_readback_20261014.json"
NUMBER = "ЕАЭС RU C-CN.НВ46.В.01893/23"
CERT_ID = 3306480
TNVED_ATTRIBUTE = "22232"
BRAND_ATTRIBUTE = "85"


def main() -> None:
    old = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    expected = {t["offer_id"]: t for t in old["targets"]}
    offers = sorted(expected)
    client = Client()

    product_resp = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = product_resp.get("items") or product_resp.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != len(offers):
        raise RuntimeError("Fresh Ozon product read did not return all five offers")
    by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon product read has missing or duplicate offers")

    attrs_resp = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": 100
    })
    attrs = attrs_resp.get("result") or attrs_resp.get("items")
    if not isinstance(attrs, list) or {str(x.get("offer_id")) for x in attrs} != set(offers):
        raise RuntimeError("Fresh Ozon attributes read did not return all five offers")
    attrs_by_offer = {str(x["offer_id"]): {str(a.get("id")): a for a in x.get("attributes") or []}
                      for x in attrs}

    records = []
    for page in range(1, 20):
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate-list response")
        records.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination limit exceeded")

    exact_records = [r for r in records if r.get("certificate_number") == NUMBER]
    bindings_by_record = {}
    for record in exact_records:
        bindings_by_record[str(record["certificate_id"])] = client.ozon_bindings(record["certificate_id"])

    targets = []
    for offer in offers:
        expected_target = expected[offer]
        product = by_offer[offer]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        if not product_id or not sku:
            raise RuntimeError("Fresh Ozon identity lacks product ID or SKU: " + offer)
        attributes = attrs_by_offer[offer]
        brands = [str(v.get("value") or "") for v in
                  (attributes.get(BRAND_ATTRIBUTE) or {}).get("values") or []]
        tnved_values = [str(v.get("value") or "") for v in
                        (attributes.get(TNVED_ATTRIBUTE) or {}).get("values") or []]
        tnved_codes = sorted({v.split(" - ", 1)[0].strip() for v in tnved_values if v.strip()})
        ozon_record_bindings = []
        for record in exact_records:
            ozon_record_bindings.extend(
                b for b in bindings_by_record[str(record["certificate_id"])]
                if str(b.get("product_id") or "") == product_id
                and str(b.get("sku") or "") == sku
            )

        cards = client.wb_cards(offer)
        wb_rows = []
        for card in cards:
            docs = card.get("documents") or card.get("docs") or {}
            wb_rows.append({
                "nmID": str(card.get("nmID") or ""),
                "vendorCode": str(card.get("vendorCode") or ""),
                "brand": card.get("brand"),
                "updatedAt": card.get("updatedAt"),
                "certificate_rows": [d for d in docs.get("items") or []
                                     if int(d.get("type") or 0) == 1
                                     and d.get("number") == NUMBER],
                "all_document_rows": docs.get("items") or [],
                "excludeDocuments": docs.get("excludeDocuments"),
                "overallVerdict": docs.get("overallVerdict"),
            })
        targets.append({
            "offer_id": offer,
            "model": expected_target.get("model"),
            "expected_product_id": expected_target.get("expected_ozon_product_id"),
            "live_product_id": product_id,
            "expected_sku": expected_target.get("expected_ozon_sku"),
            "live_sku": sku,
            "is_archived": bool(product.get("is_archived")),
            "name": product.get("name"),
            "ozon_brand_values": brands,
            "ozon_tnved_values": tnved_values,
            "ozon_identity_exact": (product_id == str(expected_target.get("expected_ozon_product_id"))
                                    and sku == str(expected_target.get("expected_ozon_sku"))),
            "ozon_record_binding_rows": ozon_record_bindings,
            "wb_exact_cards": wb_rows,
        })

    result = {
        "checked_at_utc": now(),
        "read_only": True,
        "certificate_number": NUMBER,
        "official_fsa_record": {
            "record_id": CERT_ID,
            "url": f"https://pub.fsa.gov.ru/rss/certificate/view/{CERT_ID}/product",
            "status": "Действует",
            "validity": "2023-08-30—2028-08-29",
            "applicant": "ООО \"СИЛА СВЕТА\"",
            "brands_and_series": ["Feron SP/DH/SSL/SPL/SAL", "SAFFIT SP/DH/SSL/SPL/SAL"],
            "fsa_tnved_codes": ["9405420032", "9405110033", "9405490036"],
            "sample_date_from_fsa_ui": "06.2023",
            "ui_verified_at_utc": "2026-10-14",
        },
        "ozon_matching_records": exact_records,
        "targets": targets,
        "summary": {
            "target_count": len(targets),
            "ozon_exact_identities": sum(t["ozon_identity_exact"] for t in targets),
            "ozon_products_in_fsa_code_scope": sum(
                bool(set(x.split(" - ", 1)[0].strip() for x in t["ozon_tnved_values"]) &
                     set(["9405420032", "9405110033", "9405490036"])) for t in targets),
            "ozon_matching_document_records": len(exact_records),
            "wb_exact_cards": sum(len(t["wb_exact_cards"]) == 1 and
                                   t["wb_exact_cards"][0]["vendorCode"] == t["offer_id"]
                                   for t in targets),
            "wb_matching_document_rows": sum(bool(c["certificate_rows"])
                                              for t in targets for c in t["wb_exact_cards"]),
            "wb_all_item_verdicts_valid": all(
                len(c["certificate_rows"]) == 1
                and (c["certificate_rows"][0].get("verdict") or {}).get("verified") is True
                and (c["certificate_rows"][0].get("verdict") or {}).get("reason") == "valid"
                for t in targets for c in t["wb_exact_cards"] if c["vendorCode"] == t["offer_id"]),
        },
        "decision": "No marketplace write: all five current Ozon codes are outside the official FSA code list; do not change marketplace TN VED to force acceptance.",
    }
    save(OUT, result)
    print(json.dumps({
        "output": OUT,
        "checked_at_utc": result["checked_at_utc"],
        "summary": result["summary"],
        "targets": [{"offer_id": t["offer_id"], "model": t["model"],
                     "product_id": t["live_product_id"], "sku": t["live_sku"],
                     "brand": t["ozon_brand_values"], "tnved": t["ozon_tnved_values"],
                     "wb_card_count": len(t["wb_exact_cards"]),
                     "wb_cert_rows": sum(len(c["certificate_rows"]) for c in t["wb_exact_cards"])}
                    for t in targets],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
