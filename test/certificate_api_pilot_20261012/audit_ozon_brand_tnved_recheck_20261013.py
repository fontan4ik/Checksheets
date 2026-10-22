"""Read current brand attributes for every product in the complete Ozon catalog."""
from __future__ import annotations

import collections
import json
from datetime import datetime, timezone
from pathlib import Path

from api_client import Client

BASE = Path(__file__).resolve().parent
PRODUCTS = BASE / "ozon_products_recheck_20261013.json"
OUT = BASE / "ozon_brand_tnved_inventory_recheck_20261013.json"
BATCH_SIZE = 500


def main() -> None:
    catalog = json.loads(PRODUCTS.read_text())
    if not catalog.get("complete"):
        raise RuntimeError("Complete current Ozon product catalog is required")
    products = catalog.get("products") or []
    by_offer = {str(x.get("offer_id") or ""): x for x in products}
    if "" in by_offer or len(by_offer) != len(products):
        raise RuntimeError("Ozon offer IDs are missing or duplicated")

    client = Client()
    rows = []
    offers = sorted(by_offer)
    for start in range(0, len(offers), BATCH_SIZE):
        batch = offers[start:start + BATCH_SIZE]
        body = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch),
        })
        result = body.get("result")
        if not isinstance(result, list):
            raise RuntimeError("Ozon attribute response omitted result list")
        found = set()
        for item in result:
            offer = str(item.get("offer_id") or "")
            if offer not in batch or offer in found:
                raise RuntimeError("Ozon returned an unexpected or duplicate offer")
            source = by_offer[offer]
            product_id = str(item.get("id") or item.get("product_id") or "")
            if product_id != str(source.get("product_id") or ""):
                raise RuntimeError(f"Ozon product identity changed during read: {offer}")
            brands = []
            tnved_values = []
            for attr in item.get("attributes") or []:
                if str(attr.get("id")) == "85":
                    brands = [str(v.get("value")) for v in attr.get("values") or []
                              if v.get("value") not in (None, "")]
                elif str(attr.get("id")) == "22232":
                    tnved_values = [str(v.get("value")) for v in attr.get("values") or []
                                    if v.get("value") not in (None, "")]
            tnved_codes = sorted({value.split(" - ", 1)[0].strip() for value in tnved_values})
            rows.append({
                "offer_id": offer,
                "product_id": product_id,
                "sku": str(source.get("sku") or ""),
                "is_archived": source.get("is_archived"),
                "brand": brands[0] if brands else "",
                "brand_values": brands,
                "tnved_values": tnved_values,
                "tnved_codes": tnved_codes,
                "name": str(item.get("name") or source.get("name") or ""),
            })
            found.add(offer)
        if found != set(batch):
            raise RuntimeError(f"Ozon attribute batch is incomplete: {len(set(batch) - found)} offers missing")
        print(json.dumps({"attributes_read": len(rows), "total": len(offers)}, ensure_ascii=False), flush=True)

    counts = collections.Counter(row["brand"] or "(brand attribute absent)" for row in rows)
    tnved_counts = collections.Counter(code for row in rows for code in row["tnved_codes"])
    state = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "catalog_checked_at": catalog.get("checked_at"),
        "complete": True,
        "catalog_products": len(products),
        "attributes_read": len(rows),
        "active_products": sum(row.get("is_archived") is False for row in rows),
        "archived_products": sum(row.get("is_archived") is True for row in rows),
        "brand_counts": dict(sorted(counts.items())),
        "tnved_code_counts": dict(sorted(tnved_counts.items())),
        "products": sorted(rows, key=lambda row: row["offer_id"]),
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: state[k] for k in (
        "complete", "catalog_products", "attributes_read", "active_products",
        "archived_products", "brand_counts", "tnved_code_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
