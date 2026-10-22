"""Fresh read-only Ozon scope and duplicate check for Kosmos 03254/23."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

WB_PREFLIGHT = HERE / "kosmos_03254_wb_preflight_live_20261021.json"
OUT = HERE / "kosmos_03254_ozon_preflight_live_20261021.json"
NUMBER = "ЕАЭС RU С-CN.НВ93.В.03254/23"
ISSUE = "2023-05-19"
EXPIRY = "2028-05-18"
ALLOWED_TNVED = {"8539520002", "8539520003", "8539520009"}


def values_for(attrs: dict, attribute_id: int) -> list[str]:
    mapping = {str(item.get("id")): item for item in attrs.get("attributes") or []}
    return [str(row.get("value") or "").strip()
            for row in (mapping.get(str(attribute_id)) or {}).get("values") or []
            if str(row.get("value") or "").strip()]


def base_code(values: list[str]) -> list[str]:
    return sorted({str(value).split(" - ", 1)[0].strip() for value in values if str(value).strip()})


def list_certificates(client: Client) -> list[dict]:
    result = []
    page = 1
    while page <= 100:
        body = client.call("ozon", "/v1/product/certificate/list",
                           {"page": page, "page_size": 100}).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_missing_rows")
        result.extend(batch)
        if not batch or page >= int(body.get("page_count") or 0):
            return result
        page += 1
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists; inspect it before retry")
    wb_pre = json.loads(WB_PREFLIGHT.read_text(encoding="utf-8"))
    offers = sorted({str(row["offer_id"]) for row in wb_pre.get("cards") or []})
    if len(offers) != 232:
        raise RuntimeError("source_offer_set_not_232")
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(products, list) or not isinstance(attrs, list):
        raise RuntimeError("ozon_product_or_attribute_response_incomplete")
    pmap = {str(row.get("offer_id") or ""): row for row in products}
    amap = {str(row.get("offer_id") or ""): row for row in attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("ozon_current_offer_set_mismatch")
    records = list_certificates(client)
    exact_records = [row for row in records
                     if norm_number(row.get("certificate_number")) == norm_number(NUMBER)]
    counts = collections.Counter()
    targets = []
    rows = []
    for offer in offers:
        product, attr = pmap[offer], amap[offer]
        brand = values_for(attr, 85)
        tnved_values = values_for(attr, 22232)
        codes = base_code(tnved_values)
        if product.get("is_archived") is True:
            counts["archived"] += 1
        else:
            counts["active"] += 1
        if brand == ["Космос"]:
            counts["brand_exact"] += 1
        else:
            counts["brand_other_or_missing"] += 1
        if codes and set(codes) <= ALLOWED_TNVED:
            counts["tnved_exact_in_scope"] += 1
        elif not codes:
            counts["tnved_missing"] += 1
        else:
            counts["tnved_outside_scope"] += 1
        row = {"offer_id": offer, "product_id": str(product.get("product_id") or product.get("id") or ""),
               "sku": str(product.get("sku") or ""), "name": str(product.get("name") or ""),
               "brand_values": brand, "tnved_values": tnved_values, "tnved_codes": codes,
               "is_archived": product.get("is_archived")}
        if (product.get("is_archived") is False and brand == ["Космос"]
                and codes and set(codes) <= ALLOWED_TNVED and row["product_id"] and row["sku"]):
            targets.append(row)
        rows.append(row)
    result = {
        "checked_at_utc": now(), "read_only": True,
        "certificate_number": NUMBER, "issue_date": ISSUE, "expiry_date": EXPIRY,
        "tnved_allowed": sorted(ALLOWED_TNVED), "target_count": len(offers),
        "scope_counts": dict(counts), "currently_in_scope_offer_count": len(targets),
        "exact_ozon_certificate_record_count": len(exact_records),
        "exact_ozon_certificate_records": [{"certificate_id": row.get("certificate_id"),
            "number": row.get("certificate_number"), "type_code": row.get("type_code"),
            "status_code": row.get("status_code"), "issue_date": row.get("issue_date"),
            "expire_date": row.get("expire_date"), "products_count": row.get("products_count")}
            for row in exact_records],
        "ozon_binding_write_skipped": not bool(targets),
        "ozon_skip_reason": ("Current live Ozon cards have missing or out-of-scope TN VED codes for this LED certificate; do not attach it to cards classified as halogen lamps." if not targets else None),
        "offers": rows,
    }
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUT)
    print(json.dumps({"preflight": str(OUT), "scope_counts": result["scope_counts"],
                      "currently_in_scope_offer_count": len(targets),
                      "exact_record_count": len(exact_records),
                      "ozon_binding_write_skipped": result["ozon_binding_write_skipped"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
