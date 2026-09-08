#!/usr/bin/env python3
"""Create Ozon Performance CPC campaigns for every article in ``СРС``.

For each row of the ``СРС`` sheet that has both ``art`` and ``SKU OZON`` the
script creates a new CPC promotion campaign with title ``"я {art}"``, the
standard placement (``PLACEMENT_SEARCH_AND_CATEGORY``) and autopilot strategy
(``TARGET_BIDS``), and a weekly budget of 2000₽. The SKU from the row is added
to the new campaign and the campaign is activated. The new campaign ID is
written back to the ``CAMPAIN ID`` column of the same row.

After the creation step the script invokes ``ozon_cpc_cleanup.run``. By
default it is a dry-run; scheduled mode can also write analytics and apply the
existing daily-click stop rule.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

import config
import gsheets_utils
import ozon_cpc_cleanup
from ozon_cpc_cleanup import (
    SHEET_NAME,
    TokenManager,
    batch_update_with_retry,
    column_letter,
    create_session,
    find_column,
    normalize_id,
    request_json,
    run_lock,
)


@dataclass(frozen=True)
class CreationRow:
    row_number: int
    article: str
    sku: str


def read_creation_rows(values: list[list[str]]) -> list[CreationRow]:
    if not values:
        return []
    headers = values[0]
    article_index = find_column(headers, ["art", "артикул"])
    sku_index = find_column(headers, ["sku ozon", "sku"])
    rows: list[CreationRow] = []
    for row_number, values_row in enumerate(values[1:], start=2):
        padded = list(values_row) + [""] * (len(headers) - len(values_row))
        article = str(padded[article_index]).strip() if article_index >= 0 else ""
        sku = normalize_id(padded[sku_index]) if sku_index >= 0 else ""
        if not article or not sku:
            continue
        rows.append(CreationRow(row_number=row_number, article=article, sku=sku))
    return rows


def pending_creation_rows(values: list[list[str]]) -> tuple[list[CreationRow], int]:
    """Return rows with art/SKU and an empty campaign ID plus its column index."""
    if not values:
        raise RuntimeError(f"Лист {SHEET_NAME} пуст")
    campaign_column = find_column(
        values[0], ["campain id", "campaign id", "campaign_id"]
    )
    if campaign_column < 0:
        raise RuntimeError(f"В листе {SHEET_NAME} нет колонки 'CAMPAIN ID'")

    rows = []
    for row in read_creation_rows(values):
        source_row = values[row.row_number - 1]
        campaign_id = (
            str(source_row[campaign_column]).strip()
            if campaign_column < len(source_row)
            else ""
        )
        if not campaign_id:
            rows.append(row)
    return rows, campaign_column


def write_created_campaign_ids(
    worksheet: Any,
    campaign_col_letter: str,
    created: list[tuple[CreationRow, str]],
) -> None:
    """Write sparse campaign IDs to their exact rows in one Sheets request."""
    updates = [
        {"range": f"{campaign_col_letter}{row.row_number}", "values": [[campaign_id]]}
        for row, campaign_id in sorted(created, key=lambda item: item[0].row_number)
    ]
    if updates:
        batch_update_with_retry(worksheet, updates, "CPC campaign ID batch update")


CAMPAIGN_BUDGET_MICRORUBLES = 2000 * 1_000_000
PLACEMENT = "PLACEMENT_SEARCH_AND_CATEGORY"
AUTOPILOT_STRATEGY = "TARGET_BIDS"


def create_cpc_campaign(
    session,
    token: str | TokenManager,
    title: str,
    weekly_budget_microrubbles: int = CAMPAIGN_BUDGET_MICRORUBLES,
) -> dict[str, Any]:
    payload = {
        "title": title,
        "weeklyBudget": str(weekly_budget_microrubbles),
        "placement": PLACEMENT,
        "productAutopilotStrategy": AUTOPILOT_STRATEGY,
    }
    return request_json(
        session,
        "POST",
        "/api/client/campaign/cpc/v2/product",
        token=token,
        payload=payload,
        timeout=60,
    )


def add_sku_to_campaign(
    session, token: str | TokenManager, campaign_id: str, sku: str
) -> Any:
    return request_json(
        session,
        "POST",
        f"/api/client/campaign/{campaign_id}/products",
        token=token,
        payload={"bids": [{"sku": sku, "bid": "8000000"}]},
        timeout=60,
    )


def activate_campaign(
    session, token: str | TokenManager, campaign_id: str
) -> Any:
    return request_json(
        session,
        "POST",
        f"/api/client/campaign/{campaign_id}/activate",
        token=token,
        payload={},
        timeout=60,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Обработать только первые N строк (0 = все).",
    )
    parser.add_argument(
        "--skip-sheet-write",
        action="store_true",
        help="Не записывать новые CAMPAIN ID в СРС (только в консоль).",
    )
    parser.add_argument(
        "--skip-analytics",
        action="store_true",
        help="Не запускать аналитику по новым кампаниям после создания.",
    )
    parser.add_argument(
        "--analytics-write-sheet",
        action="store_true",
        help="Записать дневную/недельную/месячную аналитику после создания.",
    )
    parser.add_argument(
        "--analytics-stop-on-filter",
        action="store_true",
        help="Применить существующий дневной фильтр кликов после создания.",
    )
    parser.add_argument(
        "--analytics-rotation-batches",
        type=int,
        default=0,
        help="Количество батчей week/month аналитики после создания (0 = все).",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=0,
        help="Секунд ждать общий CPC lock (0 = не ждать).",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    all_rows = read_creation_rows(values)
    rows, campaign_column = pending_creation_rows(values)
    campaign_col_letter = column_letter(campaign_column + 1)

    print(
        f"Лист {SHEET_NAME}: строк с art+SKU={len(all_rows)}; "
        f"новых без CAMPAIN ID={len(rows)}"
    )
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
        print(f"--limit={args.limit}: обрабатываем первые {len(rows)} строк")
    created: list[tuple[CreationRow, str]] = []
    failed: list[tuple[CreationRow, str]] = []
    if rows:
        session = create_session()
        token = TokenManager(session)
        for index, row in enumerate(rows, start=1):
            title = f"я {row.article}"
            try:
                data = create_cpc_campaign(session, token, title)
                new_id = normalize_id(data.get("campaignId") if isinstance(data, dict) else None)
                if not new_id:
                    raise RuntimeError(f"Создание кампании не вернуло campaignId: {data!r}")
                add_sku_to_campaign(session, token, new_id, row.sku)
                activate_campaign(session, token, new_id)
            except Exception as exc:
                failed.append((row, f"{type(exc).__name__}: {exc}"))
                print(f"[{index}/{len(rows)}] row={row.row_number} art={row.article} FAILED: {type(exc).__name__}: {exc}")
                continue
            created.append((row, new_id))
            print(f"[{index}/{len(rows)}] row={row.row_number} art={row.article} sku={row.sku} -> campaign {new_id} ({title})")
    else:
        print("Нет новых строк для создания")

    print(f"\nСоздано: {len(created)}; ошибок: {len(failed)}")

    if created and not args.skip_sheet_write:
        write_created_campaign_ids(worksheet, campaign_col_letter, created)
        exact_rows = ", ".join(str(row.row_number) for row, _ in created)
        print(f"Записаны новые CAMPAIN ID для {len(created)} строк: {exact_rows}")
    elif created:
        print("--skip-sheet-write: новые CAMPAIN ID НЕ записаны в СРС")

    if args.skip_analytics:
        return 0

    mode = "с записью в СРС" if args.analytics_write_sheet else "dry-run"
    print(f"\n=== CPC-аналитика после создания ({mode}) ===\n")
    analytics_args = argparse.Namespace(
        batch_size=10,
        rotation_batches=max(0, args.analytics_rotation_batches),
        write_sheet=args.analytics_write_sheet,
        apply=False,
        apply_toggle=False,
        stop_on_filter=args.analytics_stop_on_filter,
        limit_rows=0,
    )
    return ozon_cpc_cleanup.run(analytics_args)


def main() -> int:
    args = parse_args()
    with run_lock(args.lock_timeout) as acquired:
        if not acquired:
            print("Другой CPC-процесс уже выполняется; запуск создания пропущен")
            return 0
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
