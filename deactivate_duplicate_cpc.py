#!/usr/bin/env python3
"""Деактивировать дублирующиеся CPC кампании.

Для каждого названия 'я {art}' оставляем ровно одну кампанию — ту, чей ID
лежит в колонке F (CAMPAIN ID) соответствующей строки листа СРС. Остальные
кампании с тем же названием деактивируем.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
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


def deactivate(session, token, campaign_id):
    import time
    for attempt in range(1, 8):
        r = session.post(
            f"{BASE_URL}/api/client/campaign/{campaign_id}/deactivate",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={}, timeout=60,
        )
        if r.status_code == 200:
            return 200, "ok"
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 8:
            time.sleep(min(2 ** attempt, 30))
            continue
        return r.status_code, r.text[:200]
    return 429, "retries exhausted"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    if args.apply and os.getenv("OZON_CPC_CONFIRM_DEACTIVATE", "") != "YES":
        raise RuntimeError("Для боевого режима: OZON_CPC_CONFIRM_DEACTIVATE=YES --apply")

    # 1) читаем СРС — какая кампания для каждого art считается "главной"
    worksheet = gsheets_utils.get_worksheet(SHEET_NAME)
    values = worksheet.get_all_values()
    headers = values[0] if values else []
    art_i = find_column(headers, ["art", "артикул"])
    camp_i = find_column(headers, ["campain id", "campaign id", "campaign_id"])
    keep_by_title: dict[str, str] = {}
    for r in values[1:]:
        pad = list(r) + [""] * (len(headers) - len(r))
        art = pad[art_i].strip() if art_i >= 0 else ""
        cid = normalize_id(pad[camp_i])
        if not art or not cid:
            continue
        keep_by_title[f"я {art}"] = cid
    print(f"Главных ID по art: {len(keep_by_title)}")

    # 2) тянем все наши кампании
    main_sess = create_session()
    tok = get_token(main_sess)
    r = main_sess.get(
        f"{BASE_URL}/api/client/campaign?advObjectType=SKU",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    data = r.json()
    by_title: dict[str, list[dict]] = defaultdict(list)
    for c in data.get("list", []):
        title = c.get("title", "")
        if title.startswith("я "):
            by_title[title].append(c)
    print(f"Кампаний 'я ...' в Ozon: {sum(len(v) for v in by_title.values())} "
          f"(уникальных названий: {len(by_title)})")

    # 3) определяем кандидатов на деактивацию
    to_deactivate: list[tuple[str, str, str, str]] = []  # (title, id, state, reason)
    for title, camps in by_title.items():
        if len(camps) < 2:
            continue
        keep_id = keep_by_title.get(title)
        for c in camps:
            cid = str(c.get("id"))
            state = c.get("state", "")
            if state in ("CAMPAIGN_STATE_ARCHIVED", "CAMPAIGN_STATE_FINISHED"):
                continue
            if cid == keep_id:
                continue
            reason = "duplicate" if state == "CAMPAIGN_STATE_RUNNING" else f"duplicate_{state}"
            to_deactivate.append((title, cid, state, reason))

    print(f"К деактивации: {len(to_deactivate)}")
    for t, cid, st, rsn in to_deactivate[:15]:
        keep = keep_by_title.get(t, "?")
        print(f"  {t!r}  {cid} ({st}) — keep={keep}")
    if len(to_deactivate) > 15:
        print(f"  ... и ещё {len(to_deactivate) - 15}")

    if not args.apply or not to_deactivate:
        return 0

    pool = [create_session() for _ in range(args.workers)]
    tokens = [get_token(s) for s in pool]

    def call(item):
        idx, (title, cid, state, reason) = item
        s = pool[idx % args.workers]
        t = tokens[idx % args.workers]
        try:
            code, body = deactivate(s, t, cid)
            ok = code == 200
            return title, cid, state, ok, f"HTTP {code}: {body[:120]}" if not ok else "ok"
        except Exception as exc:
            return title, cid, state, False, f"{type(exc).__name__}: {exc}"

    ok = 0
    failed: list[tuple[str, str, str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(call, (i, x)) for i, x in enumerate(to_deactivate)]
        done = 0
        for f in as_completed(futs):
            title, cid, state, success, info = f.result()
            if success:
                ok += 1
            else:
                failed.append((title, cid, info))
            done += 1
            if done % 20 == 0 or done == len(to_deactivate):
                print(f"[{done}/{len(to_deactivate)}] ok={ok} failed={len(failed)}", flush=True)

    print(f"\nГотово: ok={ok}, failed={len(failed)}")
    for title, cid, info in failed[:20]:
        print(f"  {title!r} {cid}: {info}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
