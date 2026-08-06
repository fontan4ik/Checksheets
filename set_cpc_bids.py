#!/usr/bin/env python3
"""Set bid=8₽ (8_000_000 microrubbles) with retry on 429/5xx and verification.

После каждой записи делает GET /v2/products и проверяет, что наш SKU имеет
bid=8_000_000. Если нет — ретрай.
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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


BID_MICRORUBLES = 8_000_000
MAX_ATTEMPTS = 5


def get_bid(session, token: str, campaign_id: str, sku: str) -> str | None:
    r = session.get(
        f"{BASE_URL}/api/client/campaign/{campaign_id}/v2/products",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    for p in data.get("products", []):
        if str(p.get("sku")) == sku:
            return p.get("bid")
    return None


def put_bid(session, token: str, campaign_id: str, sku: str) -> tuple[bool, int]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r = session.put(
            f"{BASE_URL}/api/client/campaign/{campaign_id}/products",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"bids": [{"sku": sku, "bid": str(BID_MICRORUBLES)}]},
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
    args = parser.parse_args()

    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    headers = values[0] if values else []
    sku_i = find_column(headers, ["sku ozon", "sku"])
    camp_i = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    pairs = []
    for r in values[1:]:
        pad = list(r) + [""] * (len(headers) - len(r))
        sku = normalize_id(pad[sku_i])
        cid = normalize_id(pad[camp_i])
        if sku and cid:
            pairs.append((cid, sku))
    print(f"Пар: {len(pairs)}")

    workers = max(1, args.workers)
    pool = [create_session() for _ in range(workers)]
    tokens = [get_token(s) for s in pool]

    def process(item):
        idx, (cid, sku) = item
        sess = pool[idx % workers]
        tok = tokens[idx % workers]
        bid = get_bid(sess, tok, cid, sku)
        if bid == str(BID_MICRORUBLES):
            return cid, sku, "ok", 0
        ok, attempts = put_bid(sess, tok, cid, sku)
        if not ok:
            return cid, sku, "put_failed", attempts
        # верифицируем
        time.sleep(0.2)
        new_bid = get_bid(sess, tok, cid, sku)
        if new_bid == str(BID_MICRORUBLES):
            return cid, sku, "ok", attempts
        return cid, sku, f"verify_mismatch(bid={new_bid})", attempts

    ok = 0
    already = 0
    failed: list[tuple[str, str, str, int]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(process, (i, p)) for i, p in enumerate(pairs)]
        done = 0
        for f in as_completed(futs):
            cid, sku, status, attempts = f.result()
            if status == "ok":
                if attempts == 0:
                    already += 1
                else:
                    ok += 1
            else:
                failed.append((cid, sku, status, attempts))
            done += 1
            if done % 50 == 0 or done == len(pairs):
                print(f"[{done}/{len(pairs)}] ok={ok} already={already} failed={len(failed)}", flush=True)

    print(f"\nГотово: ok={ok}, already_correct={already}, failed={len(failed)}")
    for cid, sku, status, attempts in failed[:20]:
        print(f"  campaign={cid} sku={sku}: {status} (attempts={attempts})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
