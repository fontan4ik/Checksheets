#!/usr/bin/env python3
"""Fill ETM codes in the ETM TR sheet from result.csv.

The source file has columns ``Код ЭТМ;Артикул;Производитель``.  Rows in the
``ETM TR`` worksheet are matched by the pair ``model + brand``.  The script is
read-only by default; pass ``--write`` to update only rows whose code changed.
Unmatched rows and existing values are preserved.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import gspread

import config
import gsheets_utils


SHEET_NAME = "ETM TR"
CSV_FIELDS = ("Код ЭТМ", "Артикул", "Производитель")
SHEET_SCHEMA = {
    "model": "model",
    "brand": "brand",
    "etm_code": "Коды ЭТМ",
}
LOG_PATH = Path(__file__).resolve().parent / "logs" / "sync_etm_codes.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)


@dataclass(frozen=True)
class Update:
    row: int
    code: str
    model: str
    brand: str


def normalize(value: object) -> str:
    """Normalize comparison values without changing article punctuation/zeros."""
    return " ".join(str(value or "").replace("\ufeff", "").replace("\xa0", " ").strip().casefold().split())


def resolve_csv_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def load_csv_mapping(path: str | Path) -> tuple[dict[tuple[str, str], str], dict[str, int]]:
    """Load a unique (article, manufacturer) -> ETM code mapping.

    Duplicate source rows with the same code are accepted.  Conflicting codes
    for the same pair are rejected because choosing one silently is unsafe.
    """
    path = resolve_csv_path(path)
    mapping: dict[tuple[str, str], str] = {}
    duplicate_rows = 0
    empty_rows = 0
    conflicts: dict[tuple[str, str], set[str]] = defaultdict(set)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise ValueError(
                f"Ожидались колонки {CSV_FIELDS}, получено: {reader.fieldnames!r}"
            )
        for line_number, row in enumerate(reader, start=2):
            article = normalize(row.get("Артикул"))
            manufacturer = normalize(row.get("Производитель"))
            code = str(row.get("Код ЭТМ") or "").strip()
            if not article or not manufacturer or not code:
                empty_rows += 1
                continue
            key = (article, manufacturer)
            previous = mapping.get(key)
            if previous is not None:
                if previous != code:
                    conflicts[key].update((previous, code))
                else:
                    duplicate_rows += 1
                continue
            mapping[key] = code

    if conflicts:
        examples = list(conflicts.items())[:5]
        raise ValueError(
            f"В {path.name} найдены конфликтующие коды для {len(conflicts)} пар "
            f"model+brand; примеры: {examples}"
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = max(sum(1 for _ in handle) - 1, 0)
    stats = {
        "source_rows": source_rows,
        "mapping_keys": len(mapping),
        "duplicate_rows": duplicate_rows,
        "empty_rows": empty_rows,
    }
    return mapping, stats


def plan_updates(
    sheet_rows: list[list[str]],
    columns: dict[str, int],
    mapping: dict[tuple[str, str], str],
) -> tuple[list[Update], dict[str, int]]:
    """Plan only changed matched rows; never plan writes for unmatched rows."""
    updates: list[Update] = []
    stats = {"sheet_rows": max(len(sheet_rows) - 1, 0), "matched": 0, "changed": 0, "unchanged": 0, "unmatched": 0, "missing_keys": 0}
    model_col = columns["model"]
    brand_col = columns["brand"]
    code_col = columns["etm_code"]

    for row_number, row in enumerate(sheet_rows[1:], start=2):
        model = str(row[model_col - 1]).strip() if len(row) >= model_col else ""
        brand = str(row[brand_col - 1]).strip() if len(row) >= brand_col else ""
        key = (normalize(model), normalize(brand))
        if not key[0] or not key[1]:
            stats["missing_keys"] += 1
            continue
        code = mapping.get(key)
        if code is None:
            stats["unmatched"] += 1
            continue
        stats["matched"] += 1
        current = str(row[code_col - 1]).strip() if len(row) >= code_col else ""
        if current == code:
            stats["unchanged"] += 1
            continue
        stats["changed"] += 1
        updates.append(Update(row_number, code, model, brand))

    return updates, stats


def a1_ranges(updates: Iterable[Update], column: int) -> list[tuple[str, list[list[str]]]]:
    """Group adjacent changed rows into minimal single-column update ranges."""
    ordered = sorted(updates, key=lambda item: item.row)
    if not ordered:
        return []
    groups: list[list[Update]] = [[ordered[0]]]
    for update in ordered[1:]:
        if update.row == groups[-1][-1].row + 1:
            groups[-1].append(update)
        else:
            groups.append([update])
    result = []
    for group in groups:
        start = group[0].row
        end = group[-1].row
        range_name = f"{gspread.utils.rowcol_to_a1(start, column)}:{gspread.utils.rowcol_to_a1(end, column)}"
        result.append((range_name, [[item.code] for item in group]))
    return result


def update_sheet(ws, updates: list[Update], code_column: int) -> int:
    ranges = a1_ranges(updates, code_column)
    for range_name, values in ranges:
        logging.info("Запись %s строк в диапазон %s", len(values), range_name)
        gsheets_utils._retry_gsheet_call(
            f"update ETM codes {range_name}",
            lambda range_name=range_name, values=values: ws.update(range_name=range_name, values=values),
        )
    return len(ranges)


def run(csv_path: str | Path, write: bool = False, sample_size: int = 10) -> int:
    mapping, source_stats = load_csv_mapping(csv_path)
    ws = gsheets_utils.get_worksheet(SHEET_NAME)
    sheet_rows = gsheets_utils._retry_gsheet_call(
        f"read all values from {SHEET_NAME}",
        ws.get_all_values,
    )
    if not sheet_rows:
        raise RuntimeError(f"Лист {SHEET_NAME!r} пустой")
    columns = gsheets_utils.resolve_header_columns(sheet_rows[0], SHEET_SCHEMA, SHEET_NAME)
    updates, sheet_stats = plan_updates(sheet_rows, columns, mapping)

    logging.info(
        "Источник: строк=%s, уникальных пар=%s, дубликатов=%s, пустых строк=%s",
        source_stats["source_rows"], source_stats["mapping_keys"], source_stats["duplicate_rows"], source_stats["empty_rows"],
    )
    logging.info(
        "ETM TR: строк=%s, совпало=%s, изменится=%s, уже заполнено=%s, без совпадения=%s, без model/brand=%s",
        sheet_stats["sheet_rows"], sheet_stats["matched"], sheet_stats["changed"], sheet_stats["unchanged"], sheet_stats["unmatched"], sheet_stats["missing_keys"],
    )
    for item in updates[:sample_size]:
        logging.info("Пример изменения: строка %s, model=%r, brand=%r -> код=%s", item.row, item.model, item.brand, item.code)

    if not write:
        logging.info("Dry-run: Google Sheets не изменялись. Для записи используйте --write.")
        return 0

    range_count = update_sheet(ws, updates, columns["etm_code"])
    logging.info("Запись завершена: изменено строк=%s, диапазонов=%s", len(updates), range_count)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Сопоставить result.csv с ETM TR по model + brand")
    parser.add_argument("--csv", default="result.csv", help="Путь к result.csv")
    parser.add_argument("--write", action="store_true", help="Записать изменившиеся коды в Google Sheets")
    parser.add_argument("--sample-size", type=int, default=10, help="Сколько примеров изменений вывести")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        raise SystemExit(run(args.csv, write=args.write, sample_size=max(args.sample_size, 0)))
    except Exception as exc:
        logging.exception("CRITICAL ERROR: %s", exc)
        raise SystemExit(1)
