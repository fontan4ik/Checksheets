"""Read the WB trash listing with explicit read-only endpoint guard."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"))
from api_client import Client

PATH = "/content/v2/get/cards/trash"
STATE_FILE = HERE / "live_marketplaces_snapshot.json"
state = json.loads(STATE_FILE.read_text())
if not state.get("wb_catalog", {}).get("complete"):
    raise RuntimeError("Do not read trash until the live-card catalog is complete")
client = Client()
cards = []
cursor = {"limit": 100}
seen = set()
pages = 0
while True:
    if PATH != "/content/v2/get/cards/trash":
        raise RuntimeError("Blocked non-read endpoint")
    body = client.call("wb", PATH, {"settings": {"sort": {"ascending": True}, "cursor": cursor}}, mutation=False)
    data = body.get("data", body)
    batch = (data.get("cards") or data.get("items") or []) if isinstance(data, dict) else []
    page_cursor = (data.get("cursor") or body.get("cursor") or {}) if isinstance(data, dict) else {}
    if body.get("error") or not isinstance(batch, list):
        raise RuntimeError("Invalid WB trash page")
    pages += 1
    cards.extend(batch)
    state["wb_trash"].update({"complete": False, "pages": pages, "cards_read": len(cards), "cursor": cursor, "cards": cards})
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    tmp.replace(STATE_FILE)
    if len(batch) < 100:
        break
    signature = (page_cursor.get("trashedAt"), page_cursor.get("nmID"))
    if None in signature or signature in seen:
        raise RuntimeError("WB trash cursor incomplete or repeated")
    seen.add(signature)
    cursor = {"limit": 100, "trashedAt": signature[0], "nmID": signature[1]}
    time.sleep(0.65)

nmids = [str(x.get("nmID") or "") for x in cards]
if any(not x for x in nmids) or len(nmids) != len(set(nmids)):
    raise RuntimeError("WB trash has missing or duplicate nmID")
state["wb_trash"].update({"complete": True, "pages": pages, "checked_at": datetime.now(timezone.utc).isoformat(), "cards_read": len(cards), "cards": cards})
state["complete"] = bool(state["ozon_products"].get("complete") and state["ozon_certificates"].get("complete") and state["wb_catalog"].get("complete"))
state["updated_at"] = datetime.now(timezone.utc).isoformat()
tmp = STATE_FILE.with_suffix(".tmp")
tmp.write_text(json.dumps(state, ensure_ascii=False))
tmp.replace(STATE_FILE)
print(json.dumps({"wb_trash_complete": True, "cards": len(cards), "pages": pages}, ensure_ascii=False))
