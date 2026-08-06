#!/usr/bin/env python3
"""Set bid=8₽ (8_000_000 microrubbles) on every campaign/SKU from the СРС sheet.

Использует PUT /api/client/campaign/{campaignId}/products. SKU берём прямо из
таблицы (только что сами положили туда), дополнительный GET списка товаров
не делаем — это лишний запрос на каждую кампанию.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import gsheets_utils
from ozon_cpc_cleanup import (
    BASE_URL,
    SHEET_NAME,
    create_session,
    find_column,
    get_token,
    normalize_id,
    request_json,
)


BID_MICRORUBLES = 8_000_000
DEFAULT_WORKERS = 8


def set_campaign_bid(token: str, campaign_id: str, sku: str) -> None:
    request_json(
        requests.Session(),  # placeholder, заменяется ниже
        "PUT",
        f"/api/client/campaign/{campaign_id}/products",
        token=token,
        payload={"bids": [{"sku": sku, "bid": str(BID_MICRORUBLES)}]},
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Не менять ставки, только план")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Параллельных запросов")
    args = parser.parse_args()

    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    headers = values[0] if values else []
    sku_index = find_column(headers, ["sku ozon", "sku"])
    campaign_index = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    if sku_index < 0 or campaign_index < 0:
        raise RuntimeError("В СРС нужны колонки 'SKU OZON' и 'CAMPAIN ID'")

    pairs: list[tuple[int, str, str]] = []
    for row_number, row in enumerate(values[1:], start=2):
        padded = list(row) + [""] * (len(headers) - len(row))
        sku = normalize_id(padded[sku_index])
        cid = normalize_id(padded[campaign_index])
        if sku and cid:
            pairs.append((row_number, cid, sku))

    print(f"Пар (campaign, sku) в СРС: {len(pairs)}")
    if not pairs:
        return 0

    if args.dry_run:
        for r, c, s in pairs[:5]:
            print(f"  row={r} campaign={c} sku={s} -> bid={BID_MICRORUBLES}")
        print(f"  ... и ещё {max(0, len(pairs) - 5)}")
        return 0

    # Один токен и пул сессий на воркер (Session непотокобезопасна, делаем по сессии на поток).
    main_session = create_session()
    token = get_token(main_session)
    workers = max(1, args.workers)

    def worker_init():
        return create_session(), token

    sessions: dict[int, tuple] = {}

    def call_one(args_tuple):
        idx, (row_number, campaign_id, sku) = args_tuple
        sess, tok = sessions[idx % workers]
        try:
            request_json(
                sess, "PUT",
                f"/api/client/campaign/{campaign_id}/products",
                token=tok,
                payload={"bids": [{"sku": sku, "bid": str(BID_MICRORUBLES)}]},
                timeout=60,
            )
            return row_number, campaign_id, sku, None
        except Exception as exc:
            return row_number, campaign_id, sku, f"{type(exc).__name__}: {exc}"

    for i in range(workers):
        sessions[i] = worker_init()

    ok = 0
    failed: list[tuple[int, str, str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(call_one, (i, p)) for i, p in enumerate(pairs)]
        for done, fut in enumerate(as_completed(futures), start=1):
            row_number, campaign_id, sku, err = fut.result()
            if err is None:
                ok += 1
            else:
                failed.append((row_number, campaign_id, sku, err))
            if done % 50 == 0 or done == len(pairs):
                print(f"[{done}/{len(pairs)}] ok={ok} failed={len(failed)}", flush=True)

    print(f"\nГотово: ok={ok}, failed={len(failed)}")
    for row_number, campaign_id, sku, err in failed[:20]:
        print(f"  row={row_number} campaign={campaign_id} sku={sku}: {err}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
