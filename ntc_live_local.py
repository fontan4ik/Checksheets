"""Run NTC FBS/manual write-offs locally; write only Google Sheet F, M, N.

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
BACKUP_PATH = ROOT / "logs" / "ntc_live_first_snapshot.json"
OLD_LEDGER_NAME = "_НТЦ FBS резерв"


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
    rows = stock.get("A1:N1000", value_render_option="UNFORMATTED_VALUE")
    headers = rows[0]
    if headers[0] != "Артикул продавца" or headers[5] != "Остаток склад по моделям" or \
            headers[10] != "Ручное списание штук":
        raise ValueError("НТЦ: unexpected sheet headers")
    articles, stock_by_model, manual_k, model_rows, old_m = [], {}, {}, {}, {}
    for row_number, row in enumerate(rows[1:], 2):
        if not row or not row[0]:
            continue
        offer = str(row[0]).strip()
        model = str(row[1] if len(row) > 1 else "").strip()
        f = positive_integer(row[5] if len(row) > 5 else None, f"F{row_number}")
        size = positive_integer(row[7] if len(row) > 7 else None, f"H{row_number}", zero_allowed=False)
        manual_raw = row[10] if len(row) > 10 else ""
        manual = 0 if manual_raw in ("", None) else positive_integer(manual_raw, f"K{row_number}")
        m_raw = row[12] if len(row) > 12 else ""
        m = 0 if m_raw in ("", None) else positive_integer(m_raw, f"M{row_number}")
        if not model or any(item["offer_id"] == offer for item in articles):
            raise ValueError(f"row {row_number}: missing model or duplicate article")
        if model in stock_by_model and stock_by_model[model] != f:
            raise ValueError(f"F differs across rows of model {model}")
        stock_by_model[model] = f
        if model in old_m and old_m[model] != m:
            raise ValueError(f"M differs across rows of model {model}")
        old_m[model] = m
        articles.append({"offer_id": offer, "model": model, "H": size})
        manual_k[offer] = manual
        model_rows.setdefault(model, []).append(row_number)
    if not articles:
        raise ValueError("НТЦ: no article rows")
    if max(max(numbers) for numbers in model_rows.values()) != len(rows):
        raise ValueError("НТЦ: blank/interleaved product rows need manual review")
    return {"articles": articles, "stock_by_model": stock_by_model,
            "manual_k": manual_k, "model_rows": model_rows, "old_m": old_m,
            "row_count": len(rows) - 1}


def old_tracking(ledger: gspread.Worksheet) -> tuple[datetime, list[dict]]:
    control = ledger.get("E1:F2")
    start_raw = control[1][0] if len(control) > 1 and control[1] else ""
    start = datetime.fromisoformat(start_raw.replace("Z", "+00:00")) if start_raw else utc_now()
    updates = []
    for row in ledger.get("A2:C10000"):
        if len(row) < 3 or not row[0]:
            continue
        data = json.loads(row[2])
        updates.append({"posting_number": str(row[0]), "status": str(row[1]),
                        "items": data.get("items", []),
                        "ever_handed_over": bool(data.get("shipped", False))})
    return start, updates


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


def verify_written(stock: gspread.Worksheet, target_f: dict, model_rows: dict,
                   *, migration: bool) -> None:
    snapshot = read_sheet(stock)
    if snapshot["stock_by_model"] != target_f:
        raise RuntimeError("НТЦ: F read-back differs from planned values")
    if migration:
        if any(snapshot["old_m"].values()):
            raise RuntimeError("НТЦ: M was not cleared")
        formula_rows = stock.get(f"N2:N{snapshot['row_count'] + 1}", value_render_option="FORMULA")
        for row_number in range(2, snapshot["row_count"] + 2):
            if formula_rows[row_number - 2][0] != f"=F{row_number}":
                raise RuntimeError(f"НТЦ: N{row_number} is not linked to F")


def write_sheet(stock: gspread.Worksheet, target_f: dict, model_rows: dict,
                row_count: int, *, migration: bool) -> None:
    by_row = {row: target_f[model] for model, numbers in model_rows.items() for row in numbers}
    requests = [{"range": f"F2:F{row_count + 1}",
                 "values": [[by_row[row]] for row in range(2, row_count + 2)]}]
    if migration:
        requests.extend([
            {"range": f"M2:M{row_count + 1}", "values": [[0] for _ in range(row_count)]},
            {"range": f"N2:N{row_count + 1}",
             "values": [[f"=F{row}"] for row in range(2, row_count + 2)]},
        ])
    stock.batch_update(requests, value_input_option="USER_ENTERED")
    verify_written(stock, target_f, model_rows, migration=migration)


def recover_pending(stock: gspread.Worksheet) -> None:
    pending = read_json(PENDING_PATH)
    if not pending:
        return
    snapshot = read_sheet(stock)
    current = snapshot["stock_by_model"]
    if current == pending["old_f"]:
        write_sheet(stock, pending["new_f"], snapshot["model_rows"], snapshot["row_count"],
                    migration=pending["migration"])
    elif current == pending["new_f"]:
        verify_written(stock, pending["new_f"], snapshot["model_rows"],
                       migration=pending["migration"])
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
    migration = saved is None
    if migration and BACKUP_PATH.exists():
        raise RuntimeError("НТЦ: state file is missing after first migration; restore the ledger before retry")
    if not migration and any(snapshot["old_m"].values()):
        raise RuntimeError("НТЦ: M is nonzero after migration; old Apps Script may have run")
    ledger = book.worksheet(OLD_LEDGER_NAME)
    legacy_start, legacy = old_tracking(ledger)
    start = datetime.fromisoformat(saved["start"].replace("Z", "+00:00")) if saved else legacy_start
    now = utc_now()
    http, headers = make_http(), ozon_headers()
    wid = warehouse_id(http, headers)
    since = iso(start - timedelta(days=2))
    end = iso(now)
    if migration:
        raw = fetch_postings(http, headers, wid, since, end)
        known = {item["posting_number"] for item in legacy}
    else:
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
                    "postings": (legacy if migration else []) + updates, "returns": returns}
    result = advance(engine_input, saved["engine"] if saved else None)
    new_state = {"start": iso(start), "cursor": end, "engine": result["state"]}
    print(f"NTC {'apply' if apply else 'dry-run'}: tracked={len(result['state']['postings'])}, "
          f"returns={len(result['state']['returns'])}, delta={result['delta_physical_by_model']}, "
          f"F={result['F_by_model']}, migration={migration}")
    if not apply:
        return
    if not migration and result["F_by_model"] == snapshot["stock_by_model"]:
        save_json(STATE_PATH, new_state)
        return
    if migration and not BACKUP_PATH.exists():
        save_json(BACKUP_PATH, {"at": end, "F": snapshot["stock_by_model"],
                                "M": snapshot["old_m"], "manual_K": snapshot["manual_k"]})
    pending = {"old_f": snapshot["stock_by_model"], "new_f": result["F_by_model"],
               "new_state": new_state, "migration": migration}
    save_json(PENDING_PATH, pending)
    write_sheet(stock, result["F_by_model"], snapshot["model_rows"], snapshot["row_count"],
                migration=migration)
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
            raise SystemExit("NTC local sync already running")
        run(apply=args.apply)
