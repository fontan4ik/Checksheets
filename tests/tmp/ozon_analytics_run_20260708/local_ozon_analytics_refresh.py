#!/usr/bin/env python3
"""One-off local equivalent of Apps Script startFetchAndWriteAnalytics.

Reads Ozon Seller credentials from settings.gs, reads SKUs from sheet column V,
then refreshes Ozon analytics columns using /v1/analytics/data:
- I: ordered_units month
- L: revenue month
- J: ordered_units fixed quarter
- AO: revenue year

Do not print secrets.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import gspread
import requests
from google.oauth2.service_account import Credentials

PROJECT_DIR = Path(__file__).resolve().parents[3]
SETTINGS_GS = PROJECT_DIR / "settings.gs"
CREDS_FILE = PROJECT_DIR / "nomadic-bedrock-485314-b0-d7624dedd83c.json"
SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"
SHEET_NAME = "ТЕСТ"
API_URL = "https://api-seller.ozon.ru/v1/analytics/data"
BATCH_SIZE = 500
REQUEST_INTERVAL = 8.0
MAX_RETRIES = 3


def load_ozon_headers() -> dict[str, str]:
    text = SETTINGS_GS.read_text(encoding="utf-8")
    client_match = re.search(r"const\s+clientId\s*=\s*['\"]([^'\"]+)['\"]", text)
    key_match = re.search(r"const\s+apiKey\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not client_match or not key_match:
        raise RuntimeError("Ozon credentials not found in settings.gs")
    return {
        "Content-Type": "application/json",
        "Client-Id": client_match.group(1),
        "Api-Key": key_match.group(1),
    }


def sheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(str(CREDS_FILE), scopes=scopes)
    return gspread.authorize(creds)


def retry(label: str, fn, attempts: int = 6, base_delay: float = 2.0):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one-off operational script
            last = exc
            if attempt == attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), 30.0)
            print(f"{label}: transient {type(exc).__name__}, retry {attempt}/{attempts} in {delay:.1f}s", flush=True)
            time.sleep(delay)
    if last is not None:
        raise last
    raise RuntimeError("retry loop exited unexpectedly")


def fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def month_range() -> tuple[str, str]:
    # Same as Apps Script get3rdTo3rdDateRangeFormatted(): month ago through yesterday.
    end = date.today() - timedelta(days=1)
    year = end.year
    month = end.month - 1
    if month == 0:
        year -= 1
        month = 12
    # JS Date rolls invalid day to the next month; current day 7 is safe for this run.
    start = date(year, month, end.day)
    return fmt(start), fmt(end)


def fixed_quarter_range() -> tuple[str, str]:
    return "2025-11-25", "2026-02-25"


def year_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=365)
    return fmt(start), fmt(end)


def chunks(seq: list[str], size: int) -> Iterable[tuple[int, list[str]]]:
    for offset in range(0, len(seq), size):
        yield offset, seq[offset : offset + size]


def post_analytics(headers: dict[str, str], payload: dict) -> dict:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=120)
            if 200 <= response.status_code < 300:
                return response.json()
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            if response.status_code < 500 and response.status_code != 429:
                raise last_error
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt < MAX_RETRIES:
            delay = 30 * (2 ** (attempt - 1))
            print(f"Ozon analytics retry {attempt}/{MAX_RETRIES} after {delay}s: {type(last_error).__name__}", flush=True)
            time.sleep(delay)
    raise last_error or RuntimeError("Ozon analytics failed")


def fetch_period(headers: dict[str, str], skus: list[str], date_from: str, date_to: str, metrics: list[str], label: str) -> dict[str, list[float]]:
    total_batches = (len(skus) + BATCH_SIZE - 1) // BATCH_SIZE
    result: dict[str, list[float]] = {}
    last_request = time.monotonic() - REQUEST_INTERVAL
    print(f"[{label}] Period {date_from} -> {date_to}; SKUs={len(skus)}; batches={total_batches}", flush=True)
    for batch_no, (offset, _batch) in enumerate(chunks(skus, BATCH_SIZE), start=1):
        elapsed = time.monotonic() - last_request
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        payload = {
            "date_from": date_from,
            "date_to": date_to,
            "dimension": ["sku"],
            "metrics": metrics,
            "limit": BATCH_SIZE,
            "offset": offset,
        }
        data = post_analytics(headers, payload)
        last_request = time.monotonic()
        rows = (data.get("result") or {}).get("data") or []
        for entry in rows:
            dims = entry.get("dimensions") or []
            if not dims:
                continue
            sku = str((dims[0] or {}).get("id") or "").strip()
            if not sku:
                continue
            vals = entry.get("metrics") or []
            result[sku] = vals
        print(f"[{label}] batch {batch_no}/{total_batches}; rows={len(rows)}; total_keys={len(result)}", flush=True)
    print(f"[{label}] done; result SKUs={len(result)}", flush=True)
    if not result:
        raise RuntimeError(f"[{label}] got zero analytics rows; refusing to write zeros")
    return result


def update_range(ws, a1: str, values: Sequence[Sequence[object]]):
    retry(f"update {a1}", lambda: ws.update(range_name=a1, values=values))


def main() -> int:
    started = time.strftime("%Y-%m-%d %H:%M:%S %z")
    print(f"START local Ozon analytics refresh at {started}", flush=True)
    headers = load_ozon_headers()
    client = sheets_client()
    spreadsheet = retry("open spreadsheet", lambda: client.open_by_key(SPREADSHEET_ID))
    ws = retry("open worksheet", lambda: spreadsheet.worksheet(SHEET_NAME))

    col_v = retry("read V", lambda: ws.col_values(22))
    raw_skus = [str(x).strip() for x in col_v[1:]]
    valid_skus = sorted({x for x in raw_skus if x})
    row_count = len(raw_skus)
    print(f"Sheet rows={row_count}; unique non-empty SKUs={len(valid_skus)}", flush=True)
    if not valid_skus:
        raise RuntimeError("No SKUs found in column V")

    m_from, m_to = month_range()
    q_from, q_to = fixed_quarter_range()
    y_from, y_to = year_range()

    month = fetch_period(headers, valid_skus, m_from, m_to, ["ordered_units", "revenue"], "Month")
    vals_i = [[(month.get(sku) or [0, 0])[0] if sku else ""] for sku in raw_skus]
    vals_l = [[(month.get(sku) or [0, 0, 0])[1] if sku else ""] for sku in raw_skus]
    update_range(ws, f"I2:I{row_count+1}", vals_i)
    update_range(ws, f"L2:L{row_count+1}", vals_l)
    print("Month written: I and L", flush=True)

    quarter = fetch_period(headers, valid_skus, q_from, q_to, ["ordered_units"], "Quarter")
    vals_j = [[(quarter.get(sku) or [0])[0] if sku else ""] for sku in raw_skus]
    update_range(ws, f"J2:J{row_count+1}", vals_j)
    print("Quarter written: J", flush=True)

    year = fetch_period(headers, valid_skus, y_from, y_to, ["revenue"], "Year")
    vals_ao = [[(year.get(sku) or [0])[0] if sku else ""] for sku in raw_skus]
    update_range(ws, f"AO2:AO{row_count+1}", vals_ao)
    print("Year written: AO", flush=True)

    # quick target read-back if present
    try:
        idx = next(i for i, sku in enumerate(raw_skus, start=2) if sku == "986315608")
        row = retry("read target row", lambda: ws.row_values(idx))
        print(f"TARGET sku=986315608 row={idx} I={row[8] if len(row)>8 else ''} L={row[11] if len(row)>11 else ''}", flush=True)
    except StopIteration:
        print("TARGET sku=986315608 not found in column V", flush=True)

    print("DONE local Ozon analytics refresh", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
