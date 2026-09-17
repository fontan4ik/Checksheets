"""Run NTC FBS/manual write-offs locally; write only Google Sheet F.

Ozon calls are read-only: warehouse list, FBS posting list, and returns list.
No marketplace-stock endpoint is present. Default is a read-only dry run;
``--apply`` commits one reconciliation. launchd calls --apply once per minute.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread

from ntc_f_stage import advance
from ntc_fbs_reserve_sync import (
    PENDING, ROOT, SPREADSHEET_ID, SHEET_NAME, fetch_postings, iso,
    make_http, ozon_headers, post, utc_now, warehouse_id,
)


STATE_PATH = ROOT / "logs" / "ntc_live_state.json"
PENDING_PATH = ROOT / "logs" / "ntc_live_pending.json"
LOCK_PATH = ROOT / "logs" / "ntc_live.lock"


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def read_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def positive_integer(value, label: str, *, zero_allowed: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero_allowed else 1):
        raise ValueError(f"{label}: expected {'nonnegative' if zero_allowed else 'positive'} integer")
    return value


def read_sheet(stock: gspread.Worksheet) -> dict:
    rows = stock.get("A1:K1000", value_render_option="UNFORMATTED_VALUE")
    headers = rows[0]
    if headers[0] != "Артикул продавца" or headers[5] != "Остаток склад по моделям" or \
            headers[10] != "Ручное списание штук":
        raise ValueError("НТЦ: unexpected sheet headers")
    articles, stock_by_model, manual_k, model_rows = [], {}, {}, {}
    for row_number, row in enumerate(rows[1:], 2):
        if not row or not row[0]:
            continue
        offer = str(row[0]).strip()
        model = str(row[1] if len(row) > 1 else "").strip()
        f = positive_integer(row[5] if len(row) > 5 else None, f"F{row_number}")
        size = positive_integer(row[7] if len(row) > 7 else None, f"H{row_number}", zero_allowed=False)
        manual_raw = row[10] if len(row) > 10 else ""
        manual = 0 if manual_raw in ("", None) else positive_integer(manual_raw, f"K{row_number}")
        if not model or any(item["offer_id"] == offer for item in articles):
            raise ValueError(f"row {row_number}: missing model or duplicate article")
        if model in stock_by_model and stock_by_model[model] != f:
            raise ValueError(f"F differs across rows of model {model}")
        stock_by_model[model] = f
        articles.append({"offer_id": offer, "model": model, "H": size})
        manual_k[offer] = manual
        model_rows.setdefault(model, []).append(row_number)
    if not articles:
        raise ValueError("НТЦ: no article rows")
    if max(max(numbers) for numbers in model_rows.values()) != len(rows):
        raise ValueError("НТЦ: blank/interleaved product rows need manual review")
    return {"articles": articles, "stock_by_model": stock_by_model,
            "manual_k": manual_k, "model_rows": model_rows,
            "row_count": len(rows) - 1}


def normalize_postings(raw: list[dict], articles: set[str], known: set[str], start: datetime) -> list[dict]:
    updates = {}
    for posting in raw:
        number = str(posting.get("posting_number") or "").strip()
        status = str(posting.get("status") or "").strip()
        if not number or not status:
            raise ValueError("Ozon posting missing number/status")
        created_raw = posting.get("in_process_at") or posting.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            created = datetime.min.replace(tzinfo=timezone.utc)
        if number not in known and created < start and status not in PENDING:
            continue
        products = posting.get("products")
        if not isinstance(products, list):
            raise ValueError(f"Ozon posting {number} missing products")
        relevant = []
        for product in products:
            offer = str(product.get("offer_id") or "").strip()
            quantity = product.get("quantity")
            if not offer or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ValueError(f"Ozon posting {number} has invalid product")
            if offer in articles:
                relevant.append({"offer_id": offer, "quantity": quantity})
        if not relevant and number not in known:
            continue
        update = {"posting_number": number, "status": status}
        if status in ("cancelled", "not_accepted"):
            cancellation = posting.get("cancellation") or {}
            after_ship = cancellation.get("cancelled_after_ship")
            # Unknown cancellation history stays reserved. Ozon supplies this
            # flag on real cancelled FBS postings, including changes between polls.
            update["ever_handed_over"] = after_ship if isinstance(after_ship, bool) else True
        if relevant:
            update["items"] = relevant
        updates[number] = update
    return list(updates.values())


def fetch_returns(http, headers: dict, posting_numbers: list[str]) -> list[dict]:
    found = []
    for offset in range(0, len(posting_numbers), 50):
        group = posting_numbers[offset:offset + 50]
        last_id = 0
        while True:
            response = post(http, headers, "/v1/returns/list", {
                "filter": {"posting_numbers": group}, "limit": 500, "last_id": last_id})
            page = response.get("returns")
            if not isinstance(page, list):
                raise ValueError("Ozon returned malformed returns page")
            found.extend(page)
            if not response.get("has_next"):
                break
            if not page:
                raise ValueError("Ozon returns has_next with empty page")
            new_last_id = int(page[-1]["id"])
            if new_last_id <= last_id:
                raise ValueError("Ozon return pagination did not advance")
            last_id = new_last_id
    return found


def verify_written(stock: gspread.Worksheet, target_f: dict) -> None:
    snapshot = read_sheet(stock)
    if snapshot["stock_by_model"] != target_f:
        raise RuntimeError("НТЦ: F read-back differs from planned values")


def write_sheet(stock: gspread.Worksheet, target_f: dict, model_rows: dict,
                row_count: int) -> None:
    by_row = {row: target_f[model] for model, numbers in model_rows.items() for row in numbers}
    requests = [{"range": f"F2:F{row_count + 1}",
                 "values": [[by_row[row]] for row in range(2, row_count + 2)]}]
    stock.batch_update(requests, value_input_option="USER_ENTERED")
    verify_written(stock, target_f)


def recover_pending(stock: gspread.Worksheet) -> None:
    pending = read_json(PENDING_PATH)
    if not pending:
        return
    snapshot = read_sheet(stock)
    current = snapshot["stock_by_model"]
    if pending.get("migration"):
        raise RuntimeError("НТЦ: unfinished old column migration needs manual recovery")
    if current == pending["old_f"]:
        write_sheet(stock, pending["new_f"], snapshot["model_rows"], snapshot["row_count"])
    elif current == pending["new_f"]:
        verify_written(stock, pending["new_f"])
    else:
        raise RuntimeError("НТЦ: interrupted write and F no longer matches old/new plan")
    save_json(STATE_PATH, pending["new_state"])
    PENDING_PATH.unlink()


def run(*, apply: bool) -> None:
    client = gspread.service_account(filename=str(ROOT / "nomadic-bedrock-485314-b0-d7624dedd83c.json"))
    book = client.open_by_key(SPREADSHEET_ID)
    stock = book.worksheet(SHEET_NAME)
    if apply:
        recover_pending(stock)
    snapshot = read_sheet(stock)
    saved = read_json(STATE_PATH)
    if saved is None:
        raise RuntimeError("НТЦ: local journal is missing; restore it before running")
    start = datetime.fromisoformat(saved["start"].replace("Z", "+00:00"))
    now = utc_now()
    http, headers = make_http(), ozon_headers()
    wid = warehouse_id(http, headers)
    since = iso(start - timedelta(days=2))
    end = iso(now)
    raw = []
    for status in PENDING:
        raw.extend(fetch_postings(http, headers, wid, since, end, status=status))
    cursor = datetime.fromisoformat(saved["cursor"].replace("Z", "+00:00"))
    raw.extend(fetch_postings(http, headers, wid, since, end,
                              changed=iso(cursor - timedelta(minutes=5))))
    known = set(saved["engine"]["postings"])
    updates = normalize_postings(raw, {article["offer_id"] for article in snapshot["articles"]}, known, start)
    posting_numbers = sorted(known | {item["posting_number"] for item in updates})
    returns = fetch_returns(http, headers, posting_numbers)
    engine_input = {"stock_by_model": snapshot["stock_by_model"],
                    "articles": snapshot["articles"], "manual_k": snapshot["manual_k"],
                    "postings": updates, "returns": returns}
    result = advance(engine_input, saved["engine"])
    new_state = {"start": iso(start), "cursor": end, "engine": result["state"]}
    print(f"NTC {'apply' if apply else 'dry-run'}: tracked={len(result['state']['postings'])}, "
          f"returns={len(result['state']['returns'])}, delta={result['delta_physical_by_model']}, "
          f"F={result['F_by_model']}, shortage={result['shortage_physical_by_model']}")
    if not apply:
        return
    if result["F_by_model"] == snapshot["stock_by_model"]:
        save_json(STATE_PATH, new_state)
        return
    pending = {"old_f": snapshot["stock_by_model"], "new_f": result["F_by_model"],
               "new_state": new_state}
    save_json(PENDING_PATH, pending)
    write_sheet(stock, result["F_by_model"], snapshot["model_rows"], snapshot["row_count"])
    save_json(STATE_PATH, new_state)
    PENDING_PATH.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write F and local ledger state")
    args = parser.parse_args()
    LOCK_PATH.parent.mkdir(exist_ok=True)
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("NTC local sync skipped: another run is active")
            raise SystemExit(0)
        run(apply=args.apply)
