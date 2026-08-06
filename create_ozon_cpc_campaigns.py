#!/usr/bin/env python3
"""Create Ozon Performance CPC campaigns for every article in ``СРС``.

For each row of the ``СРС`` sheet that has both ``art`` and ``SKU OZON`` the
script creates a new CPC promotion campaign with title ``"я {art}"``, the
standard placement (``PLACEMENT_SEARCH_AND_CATEGORY``) and autopilot strategy
(``TARGET_BIDS``), and a weekly budget of 2000₽. The SKU from the row is added
to the new campaign and the campaign is activated. The new campaign ID is
written back to the ``CAMPAIN ID`` column of the same row.

After the creation step the script invokes ``ozon_cpc_cleanup.run`` in dry-run
mode (no sheet writes, no destructive actions) to display day/week/month
metrics and the filter-based candidate plan for the freshly created campaigns.
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
    BASE_URL,
    SHEET_NAME,
    column_letter,
    create_session,
    find_column,
    get_token,
    normalize,
    normalize_id,
    parse_number,
    request_json,
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


CAMPAIGN_BUDGET_MICRORUBLES = 2000 * 1_000_000
PLACEMENT = "PLACEMENT_SEARCH_AND_CATEGORY"
AUTOPILOT_STRATEGY = "TARGET_BIDS"


def create_cpc_campaign(
    session,
    token: str,
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


def add_sku_to_campaign(session, token: str, campaign_id: str, sku: str) -> Any:
    return request_json(
        session,
        "POST",
        f"/api/client/campaign/{campaign_id}/products",
        token=token,
        payload={"bids": [{"sku": sku, "bid": "0"}]},
        timeout=60,
    )


def activate_campaign(session, token: str, campaign_id: str) -> Any:
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
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    rows = read_creation_rows(values)
    headers = values[0] if values else []
    campaign_column = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    if campaign_column < 0:
        raise RuntimeError("В листе СРС нет колонки 'CAMPAIN ID'")
    campaign_col_letter = column_letter(campaign_column + 1)

    print(f"Лист {SHEET_NAME}: строк с art+SKU={len(rows)}")
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
        print(f"--limit={args.limit}: обрабатываем первые {len(rows)} строк")
    if not rows:
        print("Нет строк для обработки")
        return 0

    session = create_session()
    token = get_token(session)

    created: list[tuple[CreationRow, str]] = []
    failed: list[tuple[CreationRow, str]] = []
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

    print(f"\nСоздано: {len(created)}; ошибок: {len(failed)}")

    if created and not args.skip_sheet_write:
        for row, new_id in created:
            worksheet.update(values=[[new_id]], range_name=f"{campaign_col_letter}{row.row_number}")
        last_row = max(row.row_number for row, _ in created)
        print(f"Записаны новые CAMPAIN ID для {len(created)} строк ({campaign_col_letter}2:{campaign_col_letter}{last_row})")
    elif created:
        print("--skip-sheet-write: новые CAMPAIN ID НЕ записаны в СРС")

    if args.skip_analytics:
        return 0

    print("\n=== Аналитика по новым кампаниям (ozon_cpc_cleanup dry-run) ===\n")
    analytics_args = argparse.Namespace(batch_size=10, write_sheet=False, apply=False)
    return ozon_cpc_cleanup.run(analytics_args)


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
