"""Read-only, complete Ozon seller product catalog and exact product/SKU pairs."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from api_client import Client

BASE = Path(__file__).resolve().parent
OUT = BASE / "ozon_products_recheck_20261013_1828Z.json"
PAGE_SIZE = 1000
BATCH_SIZE = 1000


def save(state: dict) -> None:
    state["checked_at"] = datetime.now(timezone.utc).isoformat()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


client = Client()
state = {"started_at": datetime.now(timezone.utc).isoformat(), "complete": False,
         "pages": 0, "list_rows": 0, "detail_batches": 0, "products": []}
save(state)
listed: dict[str, dict] = {}
last_id = ""
seen_cursors: set[str] = set()

while True:
    body = client.call("ozon", "/v3/product/list", {
        "filter": {"visibility": "ALL"}, "last_id": last_id, "limit": PAGE_SIZE,
    })
    result = body.get("result", {})
    items = result.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product list did not return result.items")
    state["pages"] += 1
    state["list_rows"] += len(items)
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("Ozon product list returned a non-object item")
        product_id = item.get("product_id") or item.get("id")
        if product_id is None:
            raise RuntimeError("Ozon list row lacks product_id")
        key = str(product_id)
        if key in listed:
            raise RuntimeError(f"Duplicate product_id in Ozon list: {key}")
        listed[key] = item
    next_id = str(result.get("last_id") or "")
    state["unique_listed"] = len(listed)
    state["next_cursor"] = next_id
    save(state)
    if not items or not next_id:
        break
    if next_id == last_id or next_id in seen_cursors:
        raise RuntimeError("Ozon product-list cursor repeated")
    seen_cursors.add(next_id)
    last_id = next_id
    time.sleep(.1)

ids = list(listed)
details: dict[str, dict] = {}
for start in range(0, len(ids), BATCH_SIZE):
    batch = ids[start:start + BATCH_SIZE]
    body = client.call("ozon", "/v3/product/info/list", {"product_id": [int(x) for x in batch]})
    items = body.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product info did not return items")
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("Ozon product info returned a non-object item")
        pid = item.get("product_id") or item.get("id")
        if pid is None:
            raise RuntimeError("Ozon product info row lacks product_id")
        details[str(pid)] = item
    state["detail_batches"] += 1
    state["detail_rows"] = len(details)
    save(state)

missing = sorted(set(listed) - set(details))
if missing:
    state["missing_detail_product_ids"] = missing
    save(state)
    raise RuntimeError(f"Ozon product info is incomplete: {len(missing)} missing details")

products = []
for pid, source in listed.items():
    detail = details[pid]
    products.append({
        "product_id": str(detail.get("product_id") or detail.get("id") or pid),
        "offer_id": str(detail.get("offer_id") or source.get("offer_id") or ""),
        "sku": str(detail.get("sku") or ""),
        "is_archived": detail.get("is_archived"),
        "name": detail.get("name") or source.get("name"),
        "visibility": source.get("visibility"),
    })

offers = [x["offer_id"] for x in products]
product_ids = [x["product_id"] for x in products]
skus = [x["sku"] for x in products]
state.update({
    "products": products,
    "complete": True,
    "unique_listed": len(listed),
    "detail_rows": len(details),
    "duplicate_offer_ids": len(offers) - len(set(offers)),
    "duplicate_product_ids": len(product_ids) - len(set(product_ids)),
    "duplicate_skus": len([x for x in skus if x]) - len({x for x in skus if x}),
    "active_products": sum(x["is_archived"] is False for x in products),
    "archived_products": sum(x["is_archived"] is True for x in products),
})
save(state)
print(json.dumps({k: state[k] for k in (
    "complete", "pages", "unique_listed", "detail_rows", "active_products",
    "archived_products", "duplicate_offer_ids", "duplicate_product_ids", "duplicate_skus"
)}, ensure_ascii=False))
