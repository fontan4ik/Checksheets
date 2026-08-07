"""Check how much real data landed in the СРС sheet after syncs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gsheets_utils
from ozon_cpc_cleanup import SHEET_NAME


def num(value) -> float:
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return 0.0


def main() -> None:
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    headers = values[0]
    print(f"Колонки: {headers}")

    data_cols = {
        "показы день": 0,
        "клики день": 0,
        "расход день": 0,
        "расход неделя": 0,
        "расход месяц": 0,
        "продано месяц": 0,
    }
    for header in data_cols:
        idx = None
        for i, h in enumerate(headers):
            if h.strip().lower().startswith(header):
                idx = i
                break
        data_cols[header] = idx

    nonzero = {k: 0 for k in data_cols}
    samples = {k: [] for k in data_cols}
    rows_with_any = 0
    for row in values[1:]:
        has = False
        for k, idx in data_cols.items():
            if idx is None:
                continue
            v = row[idx] if idx < len(row) else ""
            if v not in ("", "0", "0.0", None):
                nonzero[k] += 1
                if len(samples[k]) < 5:
                    samples[k].append(v)
                has = True
        if has:
            rows_with_any += 1

    print(f"\nСтрок в листе: {len(values) - 1}")
    print(f"Строк с хотя бы одним ненулевым значением: {rows_with_any}")
    for k, idx in data_cols.items():
        print(f"  {k} (кол. {idx+1 if idx is not None else '?'}): ненулевых={nonzero[k]}")
        if samples[k]:
            print(f"    примеры: {samples[k]}")


if __name__ == "__main__":
    main()