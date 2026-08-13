#!/usr/bin/env python3
"""Mass activate/deactivate CPC campaigns based on column Z toggle.

Читает колонку Z "Включение/отключение компании" из листа ``СРС``:
- ``1`` → ``POST /api/client/campaign/{id}/activate``
- ``0`` → ``POST /api/client/campaign/{id}/deactivate``
- пусто/прочее → пропуск

Защитный флаг ``OZON_CPC_CONFIRM_TOGGLE=YES`` обязателен для боевого
режима. Без него скрипт работает в ``--dry-run``.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import gsheets_utils
from ozon_cpc_cleanup import (
    SHEET_NAME,
    create_session,
    find_column,
    get_token,
    normalize_id,
    parse_number,
    request_json,
)


def activation_filter_reason(
    clicks_day: str,
    filter_clicks_day: str,
    drr_month: str,
    filter_drr_month: str,
) -> str | None:
    """Return the filter that forbids activation, if a threshold is reached."""
    clicks = parse_number(clicks_day)
    clicks_threshold = parse_number(filter_clicks_day)
    if clicks_threshold > 0 and clicks >= clicks_threshold:
        return f"клики день={clicks:g} >= фильтр={clicks_threshold:g}"

    drr = parse_number(drr_month)
    drr_threshold = parse_number(filter_drr_month)
    if drr_threshold > 0 and drr >= drr_threshold:
        return f"ДРР месяц={drr:g} >= фильтр={drr_threshold:g}"
    return None


def _request_with_retry(session, method: str, path: str, token: str, max_attempts: int = 5) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            request_json(session, method, path, token=token, payload={}, timeout=60)
            return
        except Exception as exc:
            last_exc = exc
            if "429" not in str(exc):
                raise
            time.sleep(min(2 ** attempt, 15))
    raise last_exc  # type: ignore[misc]


def activate_campaign(token: str, session, campaign_id: str) -> None:
    _request_with_retry(session, "POST", f"/api/client/campaign/{campaign_id}/activate", token)


def deactivate_campaign(token: str, session, campaign_id: str) -> None:
    _request_with_retry(session, "POST", f"/api/client/campaign/{campaign_id}/deactivate", token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально дёргать activate/deactivate (по умолчанию dry-run).",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="Работать только с 09:00 до 20:00 по локальному времени.",
    )
    args = parser.parse_args()

    if args.scheduled and not (9 <= datetime.now().hour <= 20):
        print("Вне окна CPC-переключателя (09:00–20:00), запуск пропущен")
        return 0

    if args.apply and os.getenv("OZON_CPC_CONFIRM_TOGGLE", "") != "YES":
        raise RuntimeError(
            "Для боевого режима установите OZON_CPC_CONFIRM_TOGGLE=YES вместе с --apply"
        )

    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    headers = values[0] if values else []
    sku_index = find_column(headers, ["sku ozon", "sku"])
    campaign_index = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    toggle_index = find_column(headers, ["включение/отключение компании", "включение отключение компании"])
    clicks_day_index = find_column(headers, ["клики день"])
    drr_month_index = find_column(headers, ["дрр в продвижении месяц"])
    filter_clicks_index = find_column(headers, ["фильтр клики день"])
    filter_drr_index = find_column(headers, ["фильтр дрр месяц"])
    if campaign_index < 0 or sku_index < 0 or toggle_index < 0:
        raise RuntimeError("В СРС нужны колонки 'SKU OZON', 'CAMPAIN ID' и 'Включение/отключение компании'")

    plan_on: list[tuple[int, str, str]] = []
    plan_off: list[tuple[int, str, str]] = []
    skipped: list[tuple[int, str, str]] = []
    forced_off_reasons: dict[str, str] = {}
    for row_number, row in enumerate(values[1:], start=2):
        padded = list(row) + [""] * (len(headers) - len(row))
        sku = normalize_id(padded[sku_index])
        cid = normalize_id(padded[campaign_index])
        raw = padded[toggle_index].strip()
        if not sku or not cid:
            continue
        if raw in ("1", "1.0"):
            reason = activation_filter_reason(
                padded[clicks_day_index] if clicks_day_index >= 0 else "",
                padded[filter_clicks_index] if filter_clicks_index >= 0 else "",
                padded[drr_month_index] if drr_month_index >= 0 else "",
                padded[filter_drr_index] if filter_drr_index >= 0 else "",
            )
            if reason:
                plan_off.append((row_number, cid, sku))
                forced_off_reasons[cid] = reason
            else:
                plan_on.append((row_number, cid, sku))
        elif raw in ("0", "0.0"):
            plan_off.append((row_number, cid, sku))
        else:
            skipped.append((row_number, cid, sku))

    # A filter stop has priority over a manual ``1``.  This also prevents a
    # campaign with multiple SKU rows from receiving activate and deactivate
    # requests in the same run.
    blocked_campaigns = {cid for _, cid, _ in plan_off}
    plan_on = [item for item in plan_on if item[1] not in blocked_campaigns]

    print(f"Включить ({len(plan_on)}), выключить ({len(plan_off)}), пропущено ({len(skipped)})")
    for cid, reason in forced_off_reasons.items():
        print(f"  [filter-off] campaign={cid}: {reason}")
    if not plan_on and not plan_off:
        return 0

    if not args.apply:
        for r, c, s in plan_on[:5]:
            print(f"  [on ] row={r} campaign={c} sku={s}")
        for r, c, s in plan_off[:5]:
            print(f"  [off] row={r} campaign={c} sku={s}")
        if len(plan_on) > 5:
            print(f"  ... и ещё {len(plan_on) - 5} на включение")
        if len(plan_off) > 5:
            print(f"  ... и ещё {len(plan_off) - 5} на выключение")
        return 0

    main_session = create_session()
    token = get_token(main_session)
    workers = max(1, args.workers)

    def worker_init():
        return create_session(), token

    sessions: dict[int, tuple] = {i: worker_init() for i in range(workers)}

    def call_one(item: tuple[int, tuple[int, str, str, str]]):
        idx, (row_number, cid, sku, action) = item
        sess, tok = sessions[idx % workers]
        if action == "on":
            try:
                activate_campaign(tok, sess, cid)
                return row_number, cid, sku, "on", None
            except Exception as exc:
                return row_number, cid, sku, "on", f"{type(exc).__name__}: {exc}"
        else:
            try:
                deactivate_campaign(tok, sess, cid)
                return row_number, cid, sku, "off", None
            except Exception as exc:
                return row_number, cid, sku, "off", f"{type(exc).__name__}: {exc}"

    tasks = [
        (i, (*item, "on")) for i, item in enumerate(plan_on)
    ] + [
        (len(plan_on) + i, (*item, "off")) for i, item in enumerate(plan_off)
    ]
    ok = 0
    failed: list[tuple[int, str, str, str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(call_one, t) for t in tasks]
        for done, fut in enumerate(as_completed(futures), start=1):
            row_number, cid, sku, action, err = fut.result()
            if err is None:
                ok += 1
            else:
                failed.append((row_number, cid, sku, action, err))
            if done % 50 == 0 or done == len(tasks):
                print(f"[{done}/{len(tasks)}] ok={ok} failed={len(failed)}", flush=True)

    print(f"\nГотово: ok={ok}, failed={len(failed)}")
    for row_number, cid, sku, action, err in failed[:20]:
        print(f"  row={row_number} campaign={cid} sku={sku} [{action}]: {err}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
