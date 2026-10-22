"""Read WB seller cards without logging credentials or full response bodies."""
from __future__ import annotations
import collections, datetime as dt, json, time
from pathlib import Path
from api_client import Client

BASE = Path(__file__).resolve().parent
OUT = BASE / "wb_catalog_minimal_live_20261014.json"
client = Client()
host = "https://content-api.wildberries.ru"
cursor = {"limit": 100}
seen_cursors = set()
cards = []
pages = 0
started = dt.datetime.now(dt.timezone.utc).isoformat()
while True:
    payload = {"settings": {"sort": {"ascending": True}, "cursor": cursor,
                            "filter": {"withPhoto": -1}}}
    response = None
    for attempt in range(5):
        response = client.http.post(host + "/content/v2/get/cards/list", json=payload,
                                    headers=client.wb_headers, timeout=(15, 120))
        if response.status_code == 200:
            break
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(min(2 ** (attempt + 1), 30))
            continue
        raise RuntimeError(f"WB catalog read failed: HTTP {response.status_code}")
    body = response.json()
    batch = body.get("cards")
    if body.get("error") or not isinstance(batch, list):
        raise RuntimeError("WB catalog response missing cards or returned error")
    for card in batch:
        cards.append({k: card.get(k) for k in ("vendorCode", "nmID", "brand", "title", "characteristics", "documents")})
    pages += 1
    returned = body.get("cursor") or {}
    if returned.get("total") != len(batch):
        raise RuntimeError(f"WB page count mismatch at page {pages}")
    if len(batch) < 100:
        break
    signature = (returned.get("updatedAt"), returned.get("nmID"))
    if None in signature or signature in seen_cursors:
        raise RuntimeError(f"WB cursor incomplete or repeated at page {pages}")
    seen_cursors.add(signature)
    cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
    time.sleep(1.05)
by_offer = collections.defaultdict(list)
by_nmid = collections.defaultdict(list)
for card in cards:
    by_offer[str(card.get("vendorCode") or "")].append(card)
    by_nmid[str(card.get("nmID") or "")].append(card)
result = {"started_at_utc": started, "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
          "read_only": True, "complete": True, "pages": pages, "card_rows": len(cards),
          "unique_vendor_codes": len(by_offer), "duplicate_vendor_codes": {k: len(v) for k,v in by_offer.items() if k and len(v)>1},
          "duplicate_nmids": {k: sorted({str(c.get('vendorCode') or '') for c in v}) for k,v in by_nmid.items() if k and len(v)>1},
          "cards": cards}
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
tmp.replace(OUT)
print(json.dumps({k:v for k,v in result.items() if k!="cards"}, ensure_ascii=False))
