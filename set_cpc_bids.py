#!/usr/bin/env python3
"""Set bid=8₽ (8_000_000 microrubbles) on every campaign/SKU from the СРС sheet.

Использует PUT /api/client/campaign/{campaignId}/products — этот метод
перезаписывает список SKU с их ставками, поэтому перед записью читаем текущий
список товаров кампании и подменяем в нём bid.
"""

from __future__ import annotations

import argparse
import sys

import gsheets_utils
from ozon_cpc_cleanup import (
    BASE_URL,
    SHEET_NAME,
    create_session,
    find_column,
    get_token,
    normalize_id,
    request_json,
    request_bytes,
)


BID_MICRORUBLES = 8_000_000


def get_campaign_skus(session, token: str, campaign_id: str) -> list[dict]:
    data = request_json(
        session,
        "GET",
        f"/api/client/campaign/{campaign_id}/v2/products",
        token=token,
        params={"page": 1, "pageSize": 500},
        timeout=60,
    )
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        return []
    return [item for item in products if isinstance(item, dict)]


def set_campaign_bids(session, token: str, campaign_id: str, skus: list[str]) -> dict:
    payload = {"bids": [{"sku": sku, "bid": str(BID_MICRORUBLES)} for sku in skus]}
    return request_json(
        session,
        "PUT",
        f"/api/client/campaign/{campaign_id}/products",
        token=token,
        payload=payload,
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Не менять ставки, только план")
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
            print(f"  row={r} campaign={c} sku={s} -> bid=8000000")
        print(f"  ... и ещё {max(0, len(pairs) - 5)}")
        return 0

    session = create_session()
    token = get_token(session)

    ok = 0
    failed: list[tuple[int, str, str, str]] = []
    for index, (row_number, campaign_id, sku) in enumerate(pairs, start=1):
        try:
            products = get_campaign_skus(session, token, campaign_id)
            skus = [str(p.get("sku")) for p in products if p.get("sku") is not None]
            if not skus:
                raise RuntimeError("кампания не содержит SKU")
            if sku not in skus:
                skus.append(sku)
            set_campaign_bids(session, token, campaign_id, skus)
            ok += 1
            if index % 25 == 0 or index == len(pairs):
                print(f"[{index}/{len(pairs)}] ok={ok} failed={len(failed)}")
        except Exception as exc:
            failed.append((row_number, campaign_id, sku, f"{type(exc).__name__}: {exc}"))
            print(f"[{index}/{len(pairs)}] row={row_number} campaign={campaign_id} FAILED: {type(exc).__name__}: {exc}")

    print(f"\nГотово: ok={ok}, failed={len(failed)}")
    for row_number, campaign_id, sku, err in failed[:20]:
        print(f"  row={row_number} campaign={campaign_id} sku={sku}: {err}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
