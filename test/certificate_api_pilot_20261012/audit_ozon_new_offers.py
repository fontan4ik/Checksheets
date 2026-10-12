"""Read-only enrichment for Ozon offers added after the saved certificate catalog."""
from __future__ import annotations

import collections
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from api_client import Client

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
OUT = BASE / "ozon_new_offers_attributes.json"
CATALOG = ROOT / "output_to_user/ozon_catalog/catalog.csv"


def attr_values(item: dict) -> dict[str, list[str]]:
    result = {}
    for attr in item.get("attributes", []):
        values = [str(x.get("value", "")) for x in attr.get("values", []) if x.get("value") not in (None, "")]
        if values:
            result[str(attr.get("id"))] = values
    return result


with CATALOG.open(encoding="utf-8-sig", newline="") as stream:
    old_offers = {row["Артикул продавца"] for row in csv.DictReader(stream)}
products_doc = json.loads((BASE / "ozon_products_live.json").read_text())
if not products_doc.get("complete"):
    raise RuntimeError("Complete Ozon product catalog is required")
products_by_offer = {x["offer_id"]: x for x in products_doc["products"]}
new_offers = sorted(set(products_by_offer) - old_offers)
client = Client()
records = {}
batch_size = 500
for start in range(0, len(new_offers), batch_size):
    batch = new_offers[start:start + batch_size]
    body = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": batch}, "limit": len(batch),
    })
    items = body.get("result")
    if not isinstance(items, list):
        raise RuntimeError("Ozon attributes response omitted result list")
    for item in items:
        offer = str(item.get("offer_id") or "")
        if not offer or offer not in batch or offer in records:
            raise RuntimeError("Ozon attributes returned a missing, unexpected, or duplicate offer")
        current = products_by_offer[offer]
        pid = str(item.get("id") or item.get("product_id") or "")
        if pid != str(current["product_id"]):
            raise RuntimeError(f"Ozon product ID changed during attribute read for {offer}")
        attrs = attr_values(item)
        records[offer] = {
            "offer_id": offer,
            "product_id": pid,
            "sku": current["sku"],
            "is_archived": current.get("is_archived"),
            "name": str(item.get("name") or current.get("name") or ""),
            "brand": (attrs.get("85") or [""])[0],
            "model": (attrs.get("9048") or [""])[0],
            "barcode": str(item.get("barcode") or ""),
            "type_id": item.get("type_id"),
            "description_category_id": item.get("description_category_id"),
            "attributes": attrs,
        }
    if len(records) != min(start + len(batch), len(new_offers)):
        raise RuntimeError("Ozon attribute batch was incomplete")

if set(records) != set(new_offers):
    raise RuntimeError(f"Ozon attribute catalog missing {len(set(new_offers) - set(records))} offers")

wb_doc = json.loads((BASE / "wb_live.json").read_text())
if not wb_doc.get("complete"):
    raise RuntimeError("Complete WB catalog is required for cross-marketplace exact matching")
wb_codes = {x.get("vendorCode") for x in wb_doc["cards"]}
ozon_live = json.loads((BASE / "ozon_live.json").read_text())
if not ozon_live.get("complete"):
    raise RuntimeError("Complete Ozon certificate/binding snapshot is required")
approved_skus = {
    str(binding.get("sku"))
    for cert in ozon_live["certificates"]
    for binding in cert.get("live_bindings", [])
    if cert.get("status_code") == "approved" and binding.get("product_status_code") == "approved"
}
group4_run = json.loads((BASE / "group4_ozon_execution.json").read_text())
for action in group4_run.get("actions", []):
    if action.get("outcome") == "created_and_bound_readback_present":
        for binding in action.get("live_binding_readback", []):
            if action.get("live_status") == "approved" and binding.get("product_status_code") == "approved":
                approved_skus.add(str(binding.get("sku")))

for offer, row in records.items():
    row["exact_wb_card"] = offer in wb_codes
    row["any_approved_ozon_document"] = row["sku"] in approved_skus

state = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "ozon_products_checked_at": products_doc.get("checked_at"),
    "ozon_certificates_checked_at": ozon_live.get("checked_at"),
    "wb_cards_checked_at": wb_doc.get("checked_at"),
    "complete": True,
    "saved_catalog_offers": len(old_offers),
    "current_ozon_offers": len(products_by_offer),
    "new_offers": len(records),
    "new_offers_with_exact_wb_card": sum(x["exact_wb_card"] for x in records.values()),
    "new_offers_without_exact_wb_card": sum(not x["exact_wb_card"] for x in records.values()),
    "new_offers_with_any_approved_ozon_document": sum(x["any_approved_ozon_document"] for x in records.values()),
    "brands": dict(collections.Counter(x["brand"] or "(brand attribute absent)" for x in records.values())),
    "products": list(records.values()),
}
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
tmp.replace(OUT)
print(json.dumps({k: state[k] for k in ("complete", "saved_catalog_offers", "current_ozon_offers", "new_offers",
                                       "new_offers_with_exact_wb_card", "new_offers_without_exact_wb_card",
                                       "new_offers_with_any_approved_ozon_document", "brands")}, ensure_ascii=False))
