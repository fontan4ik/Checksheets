"""Read-only full Ozon catalog and compliance-attribute snapshot without body logs."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
from network_bypass import SourceAddressAdapter

OUT = BASE / "ozon_catalog_scoped_recheck_20261014.json"
PAGE_SIZE = 1000
BATCH_SIZE = 500


def build_session() -> tuple[requests.Session, dict[str, str]]:
    config = (ROOT / "Shared_Настройки.js").read_text()
    client_id = re.search(r"const clientId\s*=\s*'([^']+)'", config)
    api_key = re.search(r"const apiKey\s*=\s*'([^']+)'", config)
    if not client_id or not api_key:
        raise RuntimeError("Ozon credentials are unavailable in existing configuration")
    session = requests.Session()
    session.trust_env = False
    for interface in ("en1", "en0"):
        result = subprocess.run(["ifconfig", interface], capture_output=True, text=True)
        ip = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if ip and "status: active" in result.stdout:
            session.mount("https://", SourceAddressAdapter(ip[1], interface_name=interface))
            return session, {"Client-Id": client_id[1], "Api-Key": api_key[1],
                             "Content-Type": "application/json"}
    raise RuntimeError("No active physical network interface is available")


def call(session: requests.Session, headers: dict[str, str], path: str, payload: dict) -> dict:
    for attempt in range(5):
        response = session.post("https://api-seller.ozon.ru" + path, json=payload,
                                headers=headers, timeout=(15, 120))
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(min(2 ** (attempt + 1), 30))
            continue
        response.raise_for_status()
        time.sleep(0.2)
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"Ozon returned malformed JSON for {path}")
        return body
    raise RuntimeError(f"Ozon retry limit reached for {path}")


def values(item: dict, attribute_id: str) -> list[str]:
    for attr in item.get("attributes") or []:
        if str(attr.get("id")) == attribute_id:
            return [str(v.get("value")) for v in attr.get("values") or []
                    if v.get("value") not in (None, "")]
    return []


def main() -> None:
    session, headers = build_session()
    checked_at = datetime.now(timezone.utc).isoformat()
    listed: dict[str, dict] = {}
    last_id = ""
    seen_cursors: set[str] = set()
    pages = 0
    while True:
        body = call(session, headers, "/v3/product/list", {
            "filter": {"visibility": "ALL"}, "last_id": last_id, "limit": PAGE_SIZE})
        result = body.get("result") or {}
        items = result.get("items")
        if not isinstance(items, list):
            raise RuntimeError("Ozon full product list omitted result.items")
        pages += 1
        for item in items:
            pid = str(item.get("product_id") or item.get("id") or "")
            if not pid or pid in listed:
                raise RuntimeError("Ozon product list contains a missing or duplicate product ID")
            listed[pid] = item
        next_id = str(result.get("last_id") or "")
        if not items or not next_id:
            break
        if next_id == last_id or next_id in seen_cursors:
            raise RuntimeError("Ozon product pagination cursor repeated")
        seen_cursors.add(next_id)
        last_id = next_id

    ids = list(listed)
    details: dict[str, dict] = {}
    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start:start + BATCH_SIZE]
        body = call(session, headers, "/v3/product/info/list", {
            "product_id": [int(pid) for pid in batch]})
        items = body.get("items")
        if not isinstance(items, list):
            raise RuntimeError("Ozon product info omitted items")
        for item in items:
            pid = str(item.get("product_id") or item.get("id") or "")
            if pid not in batch or pid in details:
                raise RuntimeError("Ozon product info contains an unexpected or duplicate product")
            details[pid] = item
    if set(details) != set(listed):
        raise RuntimeError(f"Ozon product details incomplete: {len(set(listed) - set(details))} missing")

    products = []
    offers = []
    for pid, source in listed.items():
        detail = details[pid]
        offer = str(detail.get("offer_id") or source.get("offer_id") or "")
        if not offer:
            raise RuntimeError(f"Ozon product {pid} has no seller offer ID")
        offers.append(offer)
        products.append({"product_id": pid, "offer_id": offer,
                         "sku": str(detail.get("sku") or ""),
                         "is_archived": detail.get("is_archived"),
                         "name": str(detail.get("name") or source.get("name") or "")})
    if len(offers) != len(set(offers)):
        raise RuntimeError("Ozon full catalog contains duplicate seller offer IDs")

    by_offer = {x["offer_id"]: x for x in products}
    attributes: dict[str, dict] = {}
    offers_sorted = sorted(by_offer)
    for start in range(0, len(offers_sorted), BATCH_SIZE):
        batch = offers_sorted[start:start + BATCH_SIZE]
        body = call(session, headers, "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)})
        items = body.get("result")
        if not isinstance(items, list):
            raise RuntimeError("Ozon attributes omitted result list")
        found: set[str] = set()
        for item in items:
            offer = str(item.get("offer_id") or "")
            source = by_offer.get(offer)
            pid = str(item.get("id") or item.get("product_id") or "")
            if offer not in batch or offer in found or not source or pid != source["product_id"]:
                raise RuntimeError("Ozon attribute offer/product identity mismatch")
            attributes[offer] = {"brand_values": values(item, "85"),
                                 "tnved_values": values(item, "22232")}
            found.add(offer)
        if found != set(batch):
            raise RuntimeError(f"Ozon attribute batch incomplete: {len(set(batch) - found)} offers missing")
        print(json.dumps({"attributes_read": len(attributes), "total": len(offers_sorted)}), flush=True)

    for product in products:
        product.update(attributes[product["offer_id"]])
    state = {"checked_at": checked_at, "complete": True, "pages": pages,
             "catalog_products": len(products),
             "active_products": sum(x["is_archived"] is False for x in products),
             "archived_products": sum(x["is_archived"] is True for x in products),
             "products": sorted(products, key=lambda x: x["offer_id"])}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: state[k] for k in ("checked_at", "complete", "pages",
          "catalog_products", "active_products", "archived_products")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
