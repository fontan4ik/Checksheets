#!/usr/bin/env python3
"""Copy queued Apps Script Telegram alerts into the local unified error log."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import gspread


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402


SHEET_NAME = "Лог ошибок"
LOCAL_LOG = Path(os.environ.get(
    "CHECKSHEETS_ERROR_LOG_FILE",
    str(PROJECT_ROOT / "logs" / "script_errors.jsonl"),
))


def _read_local_ids(path: Path) -> set[str]:
    known_ids: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as log_file:
            for line in log_file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("source") == "Apps Script" and record.get("id"):
                    known_ids.add(str(record["id"]))
    except FileNotFoundError:
        pass
    return known_ids


def sync() -> int:
    client = gspread.service_account(
        filename=str(PROJECT_ROOT / config.GSHEETS_CREDS_FILE)
    )
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        print("Apps Script error queue does not exist yet; nothing to sync.")
        return 0

    rows = worksheet.get_all_values()
    if not rows:
        return 0

    headers = [value.strip().lower() for value in rows[0]]
    positions = {name: index for index, name in enumerate(headers)}
    required = ("id", "timestamp", "source", "service", "error", "details")
    missing = [name for name in required if name not in positions]
    if missing:
        raise RuntimeError(f"Apps Script error queue is missing columns: {', '.join(missing)}")

    known_ids = _read_local_ids(LOCAL_LOG)
    new_records = []
    for row in rows[1:]:
        record_id = row[positions["id"]].strip() if len(row) > positions["id"] else ""
        if not record_id or record_id in known_ids:
            continue

        def value(name: str) -> str:
            index = positions[name]
            return row[index] if len(row) > index else ""

        new_records.append({
            "id": record_id,
            "timestamp": value("timestamp"),
            "source": value("source") or "Apps Script",
            "service": value("service"),
            "error": value("error"),
            "details": value("details"),
        })
        known_ids.add(record_id)

    if not new_records:
        print("Apps Script error queue is up to date.")
        return 0

    LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_LOG.open("a", encoding="utf-8") as log_file:
        for record in new_records:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        log_file.flush()
        os.fsync(log_file.fileno())

    print(f"Copied {len(new_records)} Apps Script error(s) to {LOCAL_LOG}.")
    return len(new_records)


if __name__ == "__main__":
    sync()
