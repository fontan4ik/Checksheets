"""One-time NTC migration: keep existing I formulas and delete duplicate L."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import gspread


ROOT = Path(__file__).resolve().parents[1]
SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"
BACKUP = ROOT / "logs" / "ntc_before_i_only_cleanup.json"


def without_trailing_blanks(rows):
    return [list(row[:11])[:next((index for index in range(min(len(row), 11) - 1, -1, -1)
                                 if row[index] not in ("", None)), -1) + 1] for row in rows]


def verify_preserved(sheet, values, formulas):
    if sheet.col_count != 11:
        raise RuntimeError("Expected A:K after L deletion")
    if sheet.get("A1:K1000", value_render_option="UNFORMATTED_VALUE") != without_trailing_blanks(values):
        raise RuntimeError("A:K values changed after L deletion")
    if sheet.get("A1:K1000", value_render_option="FORMULA") != without_trailing_blanks(formulas):
        raise RuntimeError("A:K formulas changed after L deletion")


def main(apply: bool) -> None:
    client = gspread.service_account(
        filename=str(ROOT / "nomadic-bedrock-485314-b0-d7624dedd83c.json")
    )
    book = client.open_by_key(SPREADSHEET_ID)
    sheet = book.worksheet("НТЦ списания")
    if sheet.col_count == 11:
        saved = json.loads(BACKUP.read_text(encoding="utf-8"))
        verify_preserved(sheet, saved["values"], saved["formulas"])
        print("NTC already has A:K only; values and formulas match backup")
        return
    if sheet.col_count != 12:
        raise RuntimeError(f"Unexpected NTC column count: {sheet.col_count}")
    values = sheet.get("A1:L1000", value_render_option="UNFORMATTED_VALUE")
    formulas = sheet.get("A1:L1000", value_render_option="FORMULA")
    if values[0][8] != "Округлённое+прогруз на мп" or values[0][11] != "Остаток для маркетплейсов, упаковок":
        raise RuntimeError("Unexpected I/L headers")
    for row_number, row in enumerate(values[1:], 2):
        if not row or not row[0]:
            continue
        if len(row) < 12 or row[8] != row[11]:
            raise RuntimeError(f"I{row_number} and L{row_number} differ; review before deletion")
    print(f"NTC: {len(values) - 1} rows checked; I/L values match")
    if not apply:
        return
    if BACKUP.exists():
        raise RuntimeError(f"Backup already exists: {BACKUP}")
    BACKUP.write_text(json.dumps({
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "values": values,
        "formulas": formulas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    sheet.delete_columns(12, 12)
    sheet = book.worksheet("НТЦ списания")
    verify_preserved(sheet, values, formulas)
    print(f"Deleted L; A:K values and formulas unchanged. Backup: {BACKUP}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    main(parser.parse_args().apply)
