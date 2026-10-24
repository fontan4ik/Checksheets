"""Read-only complete Ozon/WB catalog and certificate/binding snapshot.

Calls only the explicitly listed read endpoints. No marketplace mutations.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"))
from api_client import Client  # noqa: E402

ALLOWED = {
    ("ozon", "/v3/product/list"),
    ("ozon", "/v3/product/info/list"),
    ("ozon", "/v4/product/info/attributes"),
    ("ozon", "/v1/product/certificate/list"),
    ("ozon", "/v1/product/certificate/products/list"),
    ("wb", "/content/v2/get/cards/list"),
    ("wb", "/content/v2/get/cards/trash"),
}
OUT = HERE / "live_marketplaces_snapshot_resume_20261024.json"
STATE = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "read_only_endpoint_allowlist": sorted(f"{p}:{path}" for p, path in ALLOWED),
    "ozon_products": {"complete": False, "products": []},
    "ozon_certificates": {"complete": False, "certificates": []},
    "wb_catalog": {"complete": False, "cards": []},
    "wb_trash": {"complete": False, "cards": []},
}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def save() -> None:
    STATE["updated_at"] = stamp()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(STATE, ensure_ascii=False))
    tmp.replace(OUT)


client = Client()


def call(platform: str, path: str, payload: dict) -> dict:
    if (platform, path) not in ALLOWED:
        raise RuntimeError(f"Blocked non-allowlisted endpoint: {platform}:{path}")
    return client.call(platform, path, payload, mutation=False)


def read_ozon_products() -> None:
    page = 0
    cursor = ""
    seen_cursors: set[str] = set()
    listed: dict[str, dict] = {}
    while True:
        body = call("ozon", "/v3/product/list", {
            "filter": {"visibility": "ALL"}, "last_id": cursor, "limit": 1000,
        }).get("result") or {}
        batch = body.get("items")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon product listing omitted items")
        page += 1
        for row in batch:
            pid = str(row.get("product_id") or row.get("id") or "")
            if not pid or pid in listed:
                raise RuntimeError("Ozon product ID missing or duplicated")
            listed[pid] = row
        next_cursor = str(body.get("last_id") or "")
        STATE["ozon_products"].update(pages=page, list_rows=len(listed), cursor=next_cursor)
        save()
        print(json.dumps({"phase": "ozon_product_list", "pages": page, "products": len(listed)}, ensure_ascii=False), flush=True)
        if not batch or not next_cursor:
            break
        if next_cursor == cursor or next_cursor in seen_cursors:
            raise RuntimeError("Ozon product-list cursor repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    ids = list(listed)
    details: dict[str, dict] = {}
    for start in range(0, len(ids), 500):
        batch_ids = ids[start:start + 500]
        result = call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch_ids],
        }).get("items")
        if not isinstance(result, list):
            raise RuntimeError("Ozon product details omitted items")
        for row in result:
            pid = str(row.get("product_id") or row.get("id") or "")
            if not pid or pid not in batch_ids or pid in details:
                raise RuntimeError("Ozon product detail identity missing or unexpected")
            details[pid] = row
        if set(batch_ids) != set(details).intersection(batch_ids):
            raise RuntimeError("Ozon product detail batch incomplete")
        STATE["ozon_products"]["detail_rows"] = len(details)
        save()
        print(json.dumps({"phase": "ozon_product_details", "rows": len(details), "total": len(ids)}, ensure_ascii=False), flush=True)

    if set(details) != set(listed):
        raise RuntimeError("Ozon complete catalog does not have complete detail records")

    attrs: dict[str, dict] = {}
    offers = [str((details[pid].get("offer_id") or listed[pid].get("offer_id") or "")) for pid in ids]
    if "" in offers or len(set(offers)) != len(offers):
        raise RuntimeError("Ozon offer IDs absent or duplicated; quarantine required")
    for start in range(0, len(offers), 100):
        batch_offers = offers[start:start + 100]
        response = call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch_offers}, "limit": len(batch_offers),
        }).get("result")
        if not isinstance(response, list):
            raise RuntimeError("Ozon attributes response omitted result list")
        for row in response:
            offer = str(row.get("offer_id") or "")
            if offer not in batch_offers or offer in attrs:
                raise RuntimeError("Ozon attribute row unexpected or duplicate")
            attrs[offer] = row
        if set(batch_offers) != set(attrs).intersection(batch_offers):
            raise RuntimeError("Ozon product attribute batch incomplete")
        STATE["ozon_products"]["attributes_read"] = len(attrs)
        save()
        if (start // 100 + 1) % 40 == 0:
            print(json.dumps({"phase": "ozon_product_attributes", "rows": len(attrs), "total": len(offers)}, ensure_ascii=False), flush=True)

    products = []
    for pid in ids:
        detail, source = details[pid], listed[pid]
        offer = str(detail.get("offer_id") or source.get("offer_id") or "")
        attribute_row = attrs[offer]
        if str(attribute_row.get("id") or attribute_row.get("product_id") or "") != pid:
            raise RuntimeError(f"Ozon attribute product ID changed: {offer}")
        attributes = {str(x.get("id")): x for x in attribute_row.get("attributes") or []}
        brand_values = [str(x.get("value")) for x in (attributes.get("85") or {}).get("values") or []
                        if x.get("value") not in (None, "")]
        tnved_values = [str(x.get("value")) for x in (attributes.get("22232") or {}).get("values") or []
                        if x.get("value") not in (None, "")]
        products.append({
            "product_id": pid,
            "offer_id": offer,
            "sku": str(detail.get("sku") or ""),
            "is_archived": detail.get("is_archived"),
            "visibility": source.get("visibility"),
            "name": detail.get("name") or source.get("name"),
            "brand_values": brand_values,
            "tnved_values": tnved_values,
        })
    STATE["ozon_products"].update({
        "complete": True,
        "checked_at": stamp(),
        "pages": page,
        "products": products,
        "active_products": sum(x.get("is_archived") is False for x in products),
        "archived_products": sum(x.get("is_archived") is True for x in products),
        "missing_sku": sum(not x["sku"] for x in products),
    })
    save()


def read_ozon_certificates() -> None:
    records = []
    page = 1
    ids = set()
    while page <= 100:
        data = call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list omitted certificates")
        for record in batch:
            cid = str(record.get("certificate_id") or "")
            if not cid or cid in ids:
                raise RuntimeError("Ozon certificate ID missing or duplicated")
            ids.add(cid)
        records.extend(batch)
        page_count = int(data.get("page_count") or page)
        STATE["ozon_certificates"].update(pages=page, listed=len(records), page_count=page_count)
        save()
        if page >= page_count:
            break
        page += 1
    else:
        raise RuntimeError("Ozon certificate pagination limit exceeded")

    for index, record in enumerate(records, 1):
        bindings = client.ozon_bindings(record["certificate_id"])
        record["live_bindings"] = bindings
        record["live_binding_count"] = len(bindings)
        if index % 10 == 0 or index == len(records):
            STATE["ozon_certificates"].update(read=index, certificates=records)
            save()
            print(json.dumps({"phase": "ozon_certificate_bindings", "read": index, "total": len(records)}, ensure_ascii=False), flush=True)
    status_counts = Counter(str(x.get("status_code") or "unknown") for x in records)
    STATE["ozon_certificates"].update({
        "complete": True,
        "checked_at": stamp(),
        "records": len(records),
        "status_counts": dict(status_counts),
        "total_bindings": sum(len(x.get("live_bindings") or []) for x in records),
        "certificates": records,
    })
    save()


def read_wb_collection(path: str, key: str) -> None:
    cards = []
    pages = 0
    cursor: dict = {"limit": 100}
    seen: set[tuple] = set()
    while True:
        settings = {"sort": {"ascending": True}, "cursor": cursor}
        if path.endswith("/get/cards/list"):
            settings["filter"] = {"withPhoto": -1}
        body = call("wb", path, {"settings": settings})
        data = body.get("data", body)
        batch = (data.get("cards") or data.get("items") or []) if isinstance(data, dict) else []
        returned = (data.get("cursor") or body.get("cursor") or {}) if isinstance(data, dict) else {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError(f"Invalid WB {key} page/cursor")
        pages += 1
        cards.extend(batch)
        STATE[key].update(pages=pages, cards_read=len(cards), cursor=cursor, cards=cards)
        save()
        if pages % 50 == 0:
            print(json.dumps({"phase": key, "pages": pages, "cards": len(cards)}, ensure_ascii=False), flush=True)
        if len(batch) < 100:
            break
        fields = ("updatedAt", "nmID") if key == "wb_catalog" else ("trashedAt", "nmID")
        signature = tuple(returned.get(k) for k in fields)
        if None in signature or signature in seen:
            raise RuntimeError(f"WB {key} cursor incomplete or repeated")
        seen.add(signature)
        cursor = {"limit": 100, **dict(zip(fields, signature))}
        time.sleep(0.65)
    nmids = [str(x.get("nmID") or "") for x in cards]
    if any(not x for x in nmids) or len(set(nmids)) != len(nmids):
        raise RuntimeError(f"WB {key} has missing or duplicate nmID")
    STATE[key].update({"complete": True, "checked_at": stamp(), "pages": pages, "cards": cards})
    save()


try:
    print(json.dumps({"phase": "start", "started_at": STATE["started_at"], "allowed_endpoints": len(ALLOWED)}, ensure_ascii=False), flush=True)
    read_ozon_products()
    read_ozon_certificates()
    read_wb_collection("/content/v2/get/cards/list", "wb_catalog")
    try:
        read_wb_collection("/content/v2/get/cards/trash", "wb_trash")
    except Exception as exc:
        STATE["wb_trash"].update({"complete": False, "error_type": type(exc).__name__})
        save()
        print(json.dumps({"phase": "wb_trash_unavailable", "error_type": type(exc).__name__}, ensure_ascii=False), flush=True)
    STATE["finished_at"] = stamp()
    STATE["complete"] = STATE["ozon_products"]["complete"] and STATE["ozon_certificates"]["complete"] and STATE["wb_catalog"]["complete"]
    save()
    print(json.dumps({
        "complete": STATE["complete"],
        "ozon_products": len(STATE["ozon_products"]["products"]),
        "ozon_active": STATE["ozon_products"]["active_products"],
        "ozon_archived": STATE["ozon_products"]["archived_products"],
        "ozon_certificates": STATE["ozon_certificates"]["records"],
        "ozon_bindings": STATE["ozon_certificates"]["total_bindings"],
        "wb_cards": len(STATE["wb_catalog"]["cards"]),
        "wb_trash_complete": STATE["wb_trash"]["complete"],
        "snapshot": str(OUT),
    }, ensure_ascii=False), flush=True)
except Exception as exc:
    STATE["fatal_error_type"] = type(exc).__name__
    STATE["failed_at"] = stamp()
    save()
    raise
