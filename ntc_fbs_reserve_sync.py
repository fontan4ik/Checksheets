"""Legacy read-only NTC FBS reservation diagnostic.

The old M writer is disabled because ntc_live_local.py now changes F directly.
The persistent posting ledger is retained only for migration/history.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
import requests

from network_bypass import SourceAddressAdapter


ROOT = Path(__file__).resolve().parent
SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"
SHEET_NAME = "НТЦ списания"
LEDGER_NAME = "_НТЦ FBS резерв"
BASE_URL = "https://api-seller.ozon.ru"
PENDING = (
    "acceptance_in_progress", "awaiting_approve", "awaiting_packaging",
    "awaiting_deliver", "awaiting_registration",
)
SHIPPED = {"driver_pickup", "delivering", "delivered", "last_mile"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_http() -> requests.Session:
    session = requests.Session()
    for interface in (os.getenv("CHECKSHEETS_BYPASS_INTERFACE", ""), "en1", "en0"):
        if not interface:
            continue
        result = subprocess.run(["ifconfig", interface], capture_output=True, text=True, check=False)
        match = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if "status: active" in result.stdout and match:
            adapter = SourceAddressAdapter(match.group(1), interface_name=interface)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            break
    return session


def ozon_headers() -> dict[str, str]:
    source = (ROOT / "settings.js").read_text(encoding="utf-8")
    client = os.getenv("OZON_CLIENT_ID") or re.search(r"const clientId = '([^']+)'", source).group(1)
    key = os.getenv("OZON_API_KEY") or re.search(r"const apiKey = '([^']+)'", source).group(1)
    return {"Client-Id": client, "Api-Key": key, "Content-Type": "application/json"}


def post(http: requests.Session, headers: dict[str, str], path: str, body: dict) -> dict:
    response = http.post(BASE_URL + path, headers=headers, json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def warehouse_id(http: requests.Session, headers: dict[str, str]) -> int:
    offset = 0
    while True:
        result = post(http, headers, "/v2/warehouse/list", {"limit": 200, "offset": offset})
        warehouses = result.get("warehouses") or result.get("result") or []
        if isinstance(warehouses, dict):
            warehouses = warehouses.get("warehouses", [])
        for warehouse in warehouses:
            if str(warehouse.get("name", "")).strip().casefold() == "нтц склад":
                return int(warehouse["warehouse_id"])
        if len(warehouses) < 200:
            break
        offset += len(warehouses)
    raise RuntimeError("Ozon warehouse «НТЦ СКЛАД» not found")


def fetch_postings(http: requests.Session, headers: dict[str, str], wid: int,
                   since: str, to: str, status: str = "", changed: str = "") -> list[dict]:
    postings: list[dict] = []
    offset = 0
    while True:
        filters = {"since": since, "to": to, "warehouse_id": [wid]}
        if status:
            filters["status"] = status
        if changed:
            filters["last_changed_status_date"] = {"from": changed, "to": to}
        result = post(http, headers, "/v3/posting/fbs/list", {
            "dir": "ASC", "filter": filters, "limit": 1000, "offset": offset,
            "with": {"analytics_data": False, "financial_data": False, "translit": False},
        }).get("result") or {}
        page = result.get("postings")
        if not isinstance(page, list):
            raise RuntimeError("Ozon returned malformed FBS posting page")
        postings.extend(page)
        if not result.get("has_next"):
            return postings
        if not page:
            raise RuntimeError("Ozon returned empty page with has_next=true")
        offset += len(page)


def read_ledger(sheet: gspread.Worksheet) -> dict[str, dict]:
    ledger: dict[str, dict] = {}
    for row in sheet.get("A2:C10000"):
        if len(row) < 3 or not row[0]:
            continue
        data = json.loads(row[2])
        ledger[str(row[0])] = {
            "status": str(row[1]),
            "items": data.get("items", data) if isinstance(data, dict) else data,
            "shipped": bool(data.get("shipped", False)) if isinstance(data, dict) else False,
        }
    return ledger


def reconcile(old: dict[str, dict], postings: list[dict], articles: dict[str, tuple[str, int]],
              start: datetime) -> tuple[dict[str, dict], dict[str, int]]:
    next_ledger = dict(old)
    for posting in postings:
        number = str(posting.get("posting_number") or "").strip()
        status = str(posting.get("status") or "").strip()
        if not number or not status:
            raise ValueError("Posting missing number or status")
        was_tracked = number in old
        created_raw = posting.get("in_process_at") or posting.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            created = datetime.min.replace(tzinfo=timezone.utc)
        if not was_tracked and created < start and status not in PENDING:
            continue
        products = posting.get("products")
        if not isinstance(products, list):
            raise ValueError(f"Posting {number} has no products list")
        items = []
        for product in products:
            offer = str(product.get("offer_id") or "").strip()
            quantity = product.get("quantity")
            if not offer or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ValueError(f"Posting {number} contains invalid product")
            if offer in articles:
                items.append({"offer_id": offer, "quantity": quantity})
        if not items and not was_tracked:
            continue
        next_ledger[number] = {
            "status": status, "items": items,
            "shipped": old.get(number, {}).get("shipped", False) or status in SHIPPED,
        }
    reserved: dict[str, int] = {}
    for record in next_ledger.values():
        if record["status"] in ("cancelled", "not_accepted") and not record["shipped"]:
            continue
        for item in record["items"]:
            article = articles.get(item["offer_id"])
            if article:
                model, size = article
                reserved[model] = reserved.get(model, 0) + item["quantity"] * size
    return next_ledger, reserved


def sync(*, apply: bool = False) -> None:
    if apply:
        raise RuntimeError("Old M-reserve writer is disabled; ntc_live_local.py now accounts through F")
    client = gspread.service_account(filename=str(ROOT / "nomadic-bedrock-485314-b0-d7624dedd83c.json"))
    book = client.open_by_key(SPREADSHEET_ID)
    stock = book.worksheet(SHEET_NAME)
    ledger_sheet = book.worksheet(LEDGER_NAME)
    headers = stock.row_values(1)
    if headers[0] != "Артикул продавца" or headers[10] != "Ручное списание штук":
        raise RuntimeError("NTC sheet headers changed")
    rows = stock.get("A2:H1000", value_render_option="UNFORMATTED_VALUE")
    articles: dict[str, tuple[str, int]] = {}
    for row in rows:
        if not row or not row[0]:
            continue
        offer, model = str(row[0]).strip(), str(row[1]).strip()
        size = row[7] if len(row) > 7 else None
        if not isinstance(size, int) or size <= 0 or not model:
            raise RuntimeError(f"Invalid model or multiplicity for {offer}")
        articles[offer] = (model, size)
    old = read_ledger(ledger_sheet)
    state = ledger_sheet.get("E1:F2")
    now = utc_now()
    if len(state) > 1 and state[1] and state[1][0]:
        start = datetime.fromisoformat(state[1][0].replace("Z", "+00:00"))
    else:
        start = now
    cursor = state[1][1] if len(state) > 1 and len(state[1]) > 1 else ""
    changed = datetime.fromisoformat(cursor.replace("Z", "+00:00")) if cursor else start
    changed -= timedelta(minutes=5)
    since = iso(start - timedelta(days=90))
    to = iso(now)
    http = make_http()
    api_headers = ozon_headers()
    wid = warehouse_id(http, api_headers)
    postings = []
    for status in PENDING:
        postings.extend(fetch_postings(http, api_headers, wid, since, to, status=status))
    postings.extend(fetch_postings(http, api_headers, wid, since, to, changed=iso(changed)))
    next_ledger, reserved = reconcile(old, postings, articles, start)
    print(f"NTC FBS dry-run: {len(next_ledger)} tracked postings, "
          f"{reserved} reserved physical units")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="disabled: use ntc_live_local.py --apply")
    args = parser.parse_args()
    lock_path = ROOT / "logs" / "ntc_fbs_reserve.lock"
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("NTC FBS sync already running")
        sync(apply=args.apply)
