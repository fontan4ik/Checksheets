#!/usr/bin/env python3
"""Synchronize Ozon CPC bids from the ``Размер ставки`` column of ``СРС``.

Each non-empty bid is read as rubles (``8``, ``16`` or ``8,50``), converted to
microrubles, sent to the matching campaign/SKU only if it differs, and then
verified with ``GET /v2/products``. The default mode only prints the plan;
``--apply`` is required to change Ozon.
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import gsheets_utils
import requests
from ozon_cpc_cleanup import (
    BASE_URL,
    SHEET_NAME,
    create_session,
    find_column,
    get_token,
    normalize_id,
)


MAX_ATTEMPTS = 5


class BidReadError(RuntimeError):
    """The current Ozon bid could not be read reliably."""


@dataclass(frozen=True)
class BidRow:
    row_number: int
    campaign_id: str
    sku: str
    bid_microrubles: int


def parse_bid_microrubles(value: object) -> int | None:
    """Parse a user-entered ruble amount without floating-point rounding."""
    normalized = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not normalized:
        return None
    try:
        bid = Decimal(normalized.replace(",", "."))
    except InvalidOperation:
        return None
    microrubles = bid * Decimal(1_000_000)
    if bid <= 0 or microrubles != microrubles.to_integral_value():
        return None
    return int(microrubles)


def read_bid_rows(values: list[list[str]]) -> tuple[list[BidRow], list[tuple[int, str]]]:
    """Read valid bid requests and report rows with malformed non-empty AD."""
    if not values:
        raise RuntimeError(f"Лист {SHEET_NAME} пуст")
    headers = values[0]
    sku_index = find_column(headers, ["sku ozon", "sku"])
    campaign_index = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    bid_index = find_column(headers, ["размер ставки"])
    if min(sku_index, campaign_index, bid_index) < 0:
        raise RuntimeError(
            "В СРС нужны колонки 'SKU OZON', 'CAMPAIN ID' и 'Размер ставки'"
        )

    rows: list[BidRow] = []
    invalid: list[tuple[int, str]] = []
    for row_number, values_row in enumerate(values[1:], start=2):
        padded = list(values_row) + [""] * (len(headers) - len(values_row))
        raw_bid = padded[bid_index].strip()
        if not raw_bid:
            continue
        bid_microrubles = parse_bid_microrubles(raw_bid)
        if bid_microrubles is None:
            invalid.append((row_number, raw_bid))
            continue
        sku = normalize_id(padded[sku_index])
        campaign_id = normalize_id(padded[campaign_index])
        if sku and campaign_id:
            rows.append(BidRow(row_number, campaign_id, sku, bid_microrubles))
    return rows, invalid


def get_bid(session, token: str, campaign_id: str, sku: str) -> str | None:
    """Return the current bid, or None only when the SKU is truly absent."""
    last_error = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(
                f"{BASE_URL}/api/client/campaign/{campaign_id}/v2/products",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    last_error = f"invalid JSON: {exc}"
                else:
                    for product in data.get("products", []):
                        if str(product.get("sku")) == sku:
                            return str(product.get("bid"))
                    return None
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise BidReadError(last_error)
        if attempt < MAX_ATTEMPTS:
            time.sleep(min(2 ** attempt, 15))
    raise BidReadError(last_error)


def put_bid(
    session, token: str, campaign_id: str, sku: str, bid_microrubles: int
) -> tuple[bool, int]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r = session.put(
            f"{BASE_URL}/api/client/campaign/{campaign_id}/products",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"bids": [{"sku": sku, "bid": str(bid_microrubles)}]},
            timeout=60,
        )
        if r.status_code == 200:
            return True, attempt
        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
            time.sleep(min(2 ** attempt, 15))
            continue
        return False, attempt
    return False, MAX_ATTEMPTS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать ставки в Ozon. Без флага только показать план.",
    )
    args = parser.parse_args()

    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    rows, invalid = read_bid_rows(values)
    print(f"Строк со ставкой в AD: {len(rows)}; некорректных: {len(invalid)}")
    for row_number, raw_bid in invalid[:20]:
        print(f"  row={row_number}: некорректная ставка AD={raw_bid!r}")
    if invalid:
        return 2
    if not rows:
        print("Нет ставок для синхронизации")
        return 0

    workers = max(1, args.workers)
    pool = [create_session() for _ in range(workers)]
    tokens = [get_token(s) for s in pool]

    def process(item: tuple[int, BidRow]):
        idx, row = item
        sess = pool[idx % workers]
        tok = tokens[idx % workers]
        try:
            bid = get_bid(sess, tok, row.campaign_id, row.sku)
        except BidReadError as exc:
            return row, f"read_failed({exc})", 0, None
        if bid is None:
            return row, "sku_not_in_campaign", 0, None
        if bid == str(row.bid_microrubles):
            return row, "ok", 0, bid
        if not args.apply:
            return row, "planned", 0, bid
        ok, attempts = put_bid(sess, tok, row.campaign_id, row.sku, row.bid_microrubles)
        if not ok:
            return row, "put_failed", attempts, bid
        # верифицируем
        time.sleep(0.2)
        new_bid = get_bid(sess, tok, row.campaign_id, row.sku)
        if new_bid == str(row.bid_microrubles):
            return row, "ok", attempts, new_bid
        return row, f"verify_mismatch(bid={new_bid})", attempts, new_bid

    ok = 0
    already = 0
    planned = 0
    failed: list[tuple[BidRow, str, int]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(process, (i, row)) for i, row in enumerate(rows)]
        done = 0
        for f in as_completed(futs):
            row, status, attempts, _ = f.result()
            if status == "ok":
                if attempts == 0:
                    already += 1
                else:
                    ok += 1
            elif status == "planned":
                planned += 1
            else:
                failed.append((row, status, attempts))
            done += 1
            if done % 50 == 0 or done == len(rows):
                print(
                    f"[{done}/{len(rows)}] updated={ok} already={already} "
                    f"planned={planned} failed={len(failed)}",
                    flush=True,
                )

    mode = "применено" if args.apply else "dry-run"
    print(
        f"\n{mode}: updated={ok}, already_correct={already}, "
        f"planned={planned}, failed={len(failed)}"
    )
    for row, status, attempts in failed[:20]:
        print(
            f"  row={row.row_number} campaign={row.campaign_id} sku={row.sku}: "
            f"{status} (attempts={attempts})"
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
