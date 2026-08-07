"""Diagnose why toggle (column Z) reports all-skipped.

Reads the current sheet Z values and the actual campaign state in Ozon,
then reports the mismatch distribution.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gsheets_utils
from ozon_cpc_cleanup import (
    SHEET_NAME,
    create_session,
    get_campaigns,
    get_token,
    is_cpc_campaign,
    normalize,
    normalize_id,
    rows_from_values,
)


def main() -> None:
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    headers, rows = rows_from_values(worksheet.get_all_values())
    toggle_col = headers.index("Включение/отключение компании") + 1 if "Включение/отключение компании" in headers else None
    print(f"Лист {SHEET_NAME}: строк={len(rows)}")
    print(f"Колонка Z (индекс={toggle_col-1 if toggle_col else None})")

    toggle_counts = Counter()
    for row in rows:
        toggle_counts[(row.toggle or "").strip()] += 1
    print("Распределение значений toggle (Z):")
    for value, count in sorted(toggle_counts.items(), key=lambda kv: (kv[0], kv[1])):
        label = value if value else "<пусто>"
        print(f"  {label!r}: {count}")

    session = create_session()
    token = get_token(session)
    campaigns_by_id = {normalize_id(c.get("id")): c for c in get_campaigns(session, token)}
    print(f"Кампаний в Ozon: {len(campaigns_by_id)}")

    state_counter = Counter()
    for row in rows:
        cid = row.campaign_id
        camp = campaigns_by_id.get(cid)
        if not camp:
            state_counter[("нет_в_озон", row.toggle)] += 1
            continue
        running = normalize(camp.get("state", "")) == "campaign_state_running"
        cpc = is_cpc_campaign(camp)
        state_counter[(state if state else "?", row.toggle) if not cpc else (normalize(camp.get("state")), row.toggle)] += 1

    print("Состояние (Ozon state, Z) — кампании:")

    for (state, toggle), count in state_counter.items():
        print(f"  state={state!r} toggle={toggle!r}: {count}")


if __name__ == "__main__":
    main()