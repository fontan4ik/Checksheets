"""Restore only missing tail stock formulas using existing sheet templates."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gsheets_utils as sheets

TAIL_START = 20032
SCHEMA = {
    "offer": "Артикул продавца", "model": "Артикул производителя",
    "brand": "brand", "pack": "Х",
    "moscow": "ПОДОРОЖНИК ФБС", "samara": "ФЕРОН ФБС",
    "etm": "ЭТМ САМАРА", "rs": "РЕЗЕРВ",
    "rs_moscow": {"header": "РУССКИЙ СВЕТ МОСКВА", "occurrence": 1},
    "wb_moscow": "ФБС ФЕРОН МОСКВА",
}


def cell(rows, row, column):
    values = rows[row - 1] if row <= len(rows) else []
    return values[column - 1] if column <= len(values) else ""


def valid_pack(value):
    try:
        return float(str(value).replace(",", ".")) > 0
    except (TypeError, ValueError):
        return False


def segments(rows):
    result = []
    for row in rows:
        if result and row == result[-1][1] + 1:
            result[-1][1] = row
        else:
            result.append([row, row])
    return result


def plan(formulas, values, columns):
    targets = {}
    templates = {}
    for field in ("moscow", "samara", "wb_moscow"):
        column = columns[field]
        template = cell(formulas, TAIL_START - 1, column)
        if not isinstance(template, str) or not template.startswith("="):
            raise RuntimeError(f"Missing existing template for {field}")
        templates[field] = TAIL_START - 1
        targets[field] = [
            row for row in range(TAIL_START, len(values) + 1)
            if cell(values, row, columns["offer"])
            and valid_pack(cell(values, row, columns["pack"]))
            and cell(formulas, row, column) == ""
        ]
    # Tail IEK/ITK/Generica/ONI rows consistently use /1.5 for S/V and /2 for X.
    patterns = {"etm": "=round(q#/f#/1,5;0)", "rs": "=round(u#/f#/1,5;0)",
                "rs_moscow": "=round(w#/f#/2;0)"}
    for field, pattern in patterns.items():
        column = columns[field]
        candidates = []
        targets[field] = []
        for row in range(TAIL_START, len(values) + 1):
            brand = str(cell(values, row, columns["brand"])).casefold()
            if brand not in {"iek", "itk", "generica", "oni"}:
                continue
            if not valid_pack(cell(values, row, columns["pack"])):
                continue
            formula = cell(formulas, row, column)
            if formula == "":
                targets[field].append(row)
            elif isinstance(formula, str) and formula.startswith("="):
                normalized = re.sub(r"([a-z]+)\d+", r"\1#", formula.lower().replace(" ", ""))
                if normalized != pattern:
                    raise RuntimeError(f"Unexpected existing tail rule at row {row}, {field}: {formula}")
                candidates.append(row)
        if targets[field] and not candidates:
            raise RuntimeError(f"No verified template for {field}")
        templates[field] = candidates[0] if candidates else None
    return targets, templates


def main(apply=False):
    ws = sheets.get_worksheet("StreamSupps")
    columns = sheets.get_header_columns(ws, SCHEMA)
    formulas = ws.get(f"A1:AC{ws.row_count}", value_render_option="FORMULA")
    values = ws.get(f"A1:AC{ws.row_count}", value_render_option="UNFORMATTED_VALUE")
    targets, templates = plan(formulas, values, columns)
    print("Planned missing formula repairs:", {key: len(rows) for key, rows in targets.items()})
    if not apply:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "test" / f"stream_formula_repair_before_{stamp}.json"
    backup.write_text(json.dumps({"headers": ws.row_values(1), "columns": columns,
                                 "targets": targets, "formulas": formulas,
                                 "values": values}, ensure_ascii=False))
    requests = []
    for field, rows in targets.items():
        column = columns[field] - 1
        template = templates[field] - 1 if templates[field] else None
        for start, end in segments(rows):
            requests.append({"copyPaste": {
                "source": {"sheetId": ws.id, "startRowIndex": template,
                           "endRowIndex": template + 1, "startColumnIndex": column,
                           "endColumnIndex": column + 1},
                "destination": {"sheetId": ws.id, "startRowIndex": start - 1,
                                "endRowIndex": end, "startColumnIndex": column,
                                "endColumnIndex": column + 1},
                "pasteType": "PASTE_FORMULA", "pasteOrientation": "NORMAL",
            }})
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})
    after = ws.get(f"A1:AC{ws.row_count}", value_render_option="FORMULA")
    output = ws.get(f"A1:AC{ws.row_count}", value_render_option="UNFORMATTED_VALUE")
    for field, repaired_rows in targets.items():
        column = columns[field]
        repaired = set(repaired_rows)
        for row in range(2, len(formulas) + 1):
            formula = cell(after, row, column)
            if row in repaired:
                actual = cell(output, row, column)
                if not str(formula).startswith("=") or actual == "" or str(actual).startswith("#"):
                    raise RuntimeError(f"Formula readback failed at row {row}, {field}: {actual}")
            elif formula != cell(formulas, row, column):
                raise RuntimeError(f"Existing formula changed unexpectedly at row {row}, {field}")
    print(f"Restored and verified {sum(map(len, targets.values()))} formulas; backup={backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    main(parser.parse_args().apply)
