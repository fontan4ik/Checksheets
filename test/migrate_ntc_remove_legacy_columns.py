"""One-time NTC migration: L reads F directly, then delete unused M:N."""

import argparse
from pathlib import Path

import gspread


ROOT = Path(__file__).resolve().parents[1]
SPREADSHEET_ID = "15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI"


def main(apply: bool):
    client = gspread.service_account(filename=str(ROOT / "nomadic-bedrock-485314-b0-d7624dedd83c.json"))
    book = client.open_by_key(SPREADSHEET_ID)
    sheet = book.worksheet("НТЦ списания")
    if sheet.col_count == 12:
        print("NTC columns already cleaned")
        return
    if sheet.col_count != 14:
        raise RuntimeError(f"Unexpected NTC column count: {sheet.col_count}")
    headers = sheet.row_values(1)
    if headers[12:] != ["Резерв FBS по модели, шт.", "Доступно по модели, шт."]:
        raise RuntimeError("M/N headers differ from the planned migration")
    last = sheet.row_count
    formulas = sheet.get(f"L2:L{last}", value_render_option="FORMULA")
    values_before = sheet.get(f"L2:L{last}", value_render_option="UNFORMATTED_VALUE")
    f_before = sheet.get(f"F2:F{last}", value_render_option="UNFORMATTED_VALUE")
    replacements = []
    for row_number, row in enumerate(formulas, 2):
        formula = row[0] if row else ""
        old = f"$N{row_number}"
        if formula.count(old) != 1:
            raise RuntimeError(f"L{row_number} has {formula.count(old)} references to {old}")
        replacements.append([formula.replace(old, f"$F{row_number}")])
    print(f"NTC migration plan: {len(replacements)} L formulas N→F, then delete M:N")
    if not apply:
        return
    sheet.update(range_name=f"L2:L{last}", values=replacements, value_input_option="USER_ENTERED")
    formulas_after = sheet.get(f"L2:L{last}", value_render_option="FORMULA")
    values_after = sheet.get(f"L2:L{last}", value_render_option="UNFORMATTED_VALUE")
    if formulas_after != replacements or values_after != values_before:
        raise RuntimeError("L formulas or results differ after direct F references; M/N retained")
    sheet.delete_columns(13, 14)
    sheet = book.worksheet("НТЦ списания")
    if sheet.col_count != 12 or sheet.get(f"L2:L{last}", value_render_option="UNFORMATTED_VALUE") != values_before:
        raise RuntimeError("L values changed after deleting M/N")
    if sheet.get(f"F2:F{last}", value_render_option="UNFORMATTED_VALUE") != f_before:
        raise RuntimeError("F changed after deleting M/N")
    print("NTC migration complete: M/N deleted, F and L values unchanged")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(args.apply)
