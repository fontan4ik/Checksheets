#!/usr/bin/env python3
"""Read-only, bounded Ozon seller catalog identity inventory; emits no secret values."""
import json
import os
import pathlib
import stat
import urllib.error
import urllib.request

API_BASE = os.environ.get("PAPERCLIP_API_URL", "").rstrip("/")
if not API_BASE.endswith("/api"):
    API_BASE += "/api"
HEADERS = {
    "Authorization": f"Bearer {os.environ.get('PAPERCLIP_API_KEY', '')}",
    "X-Paperclip-Run-Id": os.environ.get("PAPERCLIP_RUN_ID", ""),
    "Accept": "application/json",
}

def result(stage, **details):
    print(json.dumps({"stage": stage, **details}, ensure_ascii=False))

try:
    req = urllib.request.Request(
        f"{API_BASE}/agents/me/secrets/ozon_reviews_secrets_file/value",
        data=b"", headers=HEADERS, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        locator = json.load(response).get("value")
except Exception as error:
    result("ozon_secret_grant_unavailable", errorType=type(error).__name__)
    raise SystemExit(0)

path = pathlib.Path(locator)
try:
    info = path.stat()
    if not path.is_file() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("locator_not_private_regular")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("locator_wrong_owner")
    if info.st_size > 65536:
        raise ValueError("locator_too_large")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.removeprefix("export ").strip()] = value.strip().strip("\"'")
except Exception as error:
    result("ozon_secret_locator_unavailable", errorType=type(error).__name__)
    raise SystemExit(0)

client_id = values.get("OZON_CLIENT_ID", "")
api_key = values.get("OZON_API_KEY", "")
if not client_id or not api_key:
    result("seller_credentials_missing")
    raise SystemExit(0)

url = "https://api-seller.ozon.ru/v3/product/list"
last_id = ""
seen_cursors = set()
offers = []
expected_total = None
pages = 0
while pages < 40:
    body = {"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": 1000}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        result("catalog_http_error", httpStatus=error.code, pages=pages)
        raise SystemExit(0)
    result_body = payload.get("result", {})
    items = result_body.get("items")
    total = result_body.get("total_items", result_body.get("total"))
    if not isinstance(items, list) or not isinstance(total, int):
        result("catalog_shape_incomplete", pages=pages)
        raise SystemExit(0)
    if expected_total is None:
        expected_total = total
    elif total != expected_total:
        result("catalog_count_changed", pages=pages)
        raise SystemExit(0)
    for item in items:
        offers.append({
            "offerId": str(item.get("offer_id") or ""),
            "productId": str(item.get("product_id") or ""),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "barcode": [str(value) for value in item.get("barcode", [])] if isinstance(item.get("barcode"), list) else [],
        })
    cursor = str(result_body.get("last_id") or "")
    if not items:
        if not cursor:
            break
        result("empty_page_with_cursor", pages=pages)
        raise SystemExit(0)
    if not cursor or cursor == last_id or cursor in seen_cursors:
        result("cursor_missing_or_repeated", pages=pages)
        raise SystemExit(0)
    seen_cursors.add(cursor)
    last_id = cursor
    pages += 1
else:
    result("page_cap_exceeded", pages=pages)
    raise SystemExit(0)

result(
    "complete", pages=pages, count=len(offers), expectedCount=expected_total,
    uniqueOfferCount=len({item["offerId"] for item in offers if item["offerId"]}),
    feronNameCount=sum("feron" in item["name"].lower() for item in offers),
    feronBrandCount=sum("feron" in item["name"].lower() for item in offers),
    offers=offers,
)
