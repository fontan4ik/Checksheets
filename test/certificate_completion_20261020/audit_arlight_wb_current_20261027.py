#!/usr/bin/env python3
"""Read-only live audit of Arlight WB cards and the WB error queue."""
from __future__ import annotations
import collections
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client  # noqa: E402

OUT = HERE / "arlight_wb_current_audit_20261027.json"
if OUT.exists():
    raise RuntimeError("audit output exists; inspect before replacing")
client = Client()
started = datetime.now(timezone.utc).isoformat()
cards = []
page = 0
cursor = {"limit": 100}
seen = set()
while True:
    body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
        "sort": {"ascending": True}, "cursor": cursor,
        "filter": {"withPhoto": -1}}})
    batch = body.get("cards")
    returned = body.get("cursor") or {}
    if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
        raise RuntimeError("WB card page incomplete")
    page += 1
    cards.extend(batch)
    if len(batch) < 100:
        break
    signature = (returned.get("updatedAt"), returned.get("nmID"))
    if None in signature or signature in seen:
        raise RuntimeError("WB card cursor incomplete or repeated")
    seen.add(signature)
    cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
    if page % 50 == 0:
        print(json.dumps({"phase": "cards", "pages": page, "rows": len(cards)}), flush=True)

nmid_counts = collections.Counter(str(c.get("nmID") or "") for c in cards)
if any(not k for k in nmid_counts):
    raise RuntimeError("WB card without nmID")
arlight_cards = [c for c in cards if str(c.get("brand") or "").strip().casefold() == "arlight"]
arlight_offers = {str(c.get("vendorCode") or "") for c in arlight_cards}
if "" in arlight_offers:
    raise RuntimeError("Arlight card with empty vendorCode")

error_rows = []
error_cursor = {"limit": 100}
error_seen = set()
error_pages = 0
while True:
    body = client.call("wb", "/content/v2/cards/error/list", {
        "cursor": error_cursor, "order": {"ascending": True}})
    if body.get("error"):
        raise RuntimeError("WB error-list API returned error")
    data = body.get("data") or {}
    items = data.get("items") or []
    if not isinstance(items, list):
        raise RuntimeError("WB error-list items missing")
    error_rows.extend(items)
    error_pages += 1
    cur = data.get("cursor") or {}
    if cur.get("next") is not True:
        break
    signature = (cur.get("updatedAt"), cur.get("batchUUID"))
    if None in signature or signature in error_seen:
        raise RuntimeError("WB error-list cursor incomplete or repeated")
    error_seen.add(signature)
    error_cursor = {"limit": 100, "updatedAt": signature[0], "batchUUID": signature[1]}
    if error_pages > 1000:
        raise RuntimeError("WB error-list pagination exceeded bound")

# Include Arlight rows and any seller error rows pointing at a live Arlight vendorCode.
arlight_errors = []
for row in error_rows:
    errors = row.get("errors") or {}
    offer = str(row.get("vendorCode") or row.get("offerId") or row.get("vendor_code") or "")
    brand = str(row.get("brand") or "").strip().casefold()
    if offer in arlight_offers or brand == "arlight" or any(
        offer and offer.casefold() in str(k).casefold() for k in arlight_offers
    ):
        arlight_errors.append(row)

summary = {
    "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    "started_at_utc": started,
    "complete": True,
    "wb_catalog_pages": page,
    "wb_catalog_cards": len(cards),
    "wb_duplicate_nmids": {k: v for k, v in nmid_counts.items() if v > 1},
    "arlight_card_count": len(arlight_cards),
    "arlight_unique_offers": len(arlight_offers),
    "arlight_cards_with_documents": sum(bool((c.get("documents") or {}).get("items")) for c in arlight_cards),
    "arlight_cards_without_documents": sum(not bool((c.get("documents") or {}).get("items")) for c in arlight_cards),
    "wb_error_pages": error_pages,
    "wb_error_rows": len(error_rows),
    "arlight_error_rows": len(arlight_errors),
}
out = {"summary": summary, "arlight_cards": arlight_cards, "arlight_error_rows": arlight_errors}
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(OUT)
print(json.dumps({**summary, "output": str(OUT)}, ensure_ascii=False), flush=True)
