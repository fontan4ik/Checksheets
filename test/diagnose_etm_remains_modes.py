import sys
import time
from typing import Dict, List, Optional

import requests

sys.path.insert(0, "/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets")

from etm_sync_local import create_etm_session, get_etm_session, _build_article_variants
from etm_sync_multi_store import add_stock_to_lookup, resolve_stock_loose, resolve_gds_code_loose


HEADERS = {"Accept": "application/json"}
SAMARA_STORE_ID = 13
MOSCOW_STORE_ID = 14
REQUEST_DELAY = 1.2


def sleep_after_request():
    time.sleep(REQUEST_DELAY)


def rc_rows(info_stores: List[dict]) -> List[dict]:
    rows = []
    for store in info_stores or []:
        if (store.get("StoreType") or "").lower() != "rc":
            continue
        qty = store.get("StoreQuantRem")
        try:
            qty = int(qty or 0)
        except (TypeError, ValueError):
            qty = 0
        rows.append(
            {
                "code": store.get("StoreCode"),
                "name": store.get("StoreName"),
                "qty": qty,
            }
        )
    return rows


def bulk_lookup(http, session_id: str, store_id: int, article: str):
    url = f"https://ipro.etm.ru/api/v1/goods/remains?store={store_id}&session-id={session_id}"
    response = http.get(url, headers=HEADERS, timeout=120)
    sleep_after_request()
    try:
        payload = response.json()
    except ValueError:
        print(
            f"bulk_store_{store_id}_invalid_json http={response.status_code} "
            f"body_head={response.text[:300]!r}"
        )
        return [], []
    rows = payload.get("data", {}).get("rows", [])

    article_upper = article.upper()
    matches = []
    lookup = {}
    tails = {}
    article_to_gds = {}
    tail_to_gds = {}
    loose_entries = []
    for row in rows:
        add_stock_to_lookup(lookup, tails, article_to_gds, tail_to_gds, loose_entries, row)
        current = str(row.get("Article") or "").upper().strip()
        if not current:
            continue
        dotted_base = current.split(".", 1)[0]
        if current == article_upper or dotted_base == article_upper:
            matches.append(
                {
                    "Article": row.get("Article"),
                    "GdsCode": row.get("GdsCode"),
                    "RemInfo": row.get("RemInfo"),
                    "StoreCode": row.get("StoreCode"),
                }
            )
    return matches, loose_entries


def direct_lookup(http, session_id: str, item_id: str, request_type: str) -> Dict:
    url = (
        f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(str(item_id))}/remains"
        f"?type={request_type}&session-id={session_id}"
    )
    response = http.get(url, headers=HEADERS, timeout=30)
    sleep_after_request()

    result: Dict[str, object] = {
        "http_status": response.status_code,
        "body_code": None,
        "gdscode": None,
        "rc_rows": [],
    }

    try:
        payload = response.json()
    except ValueError:
        return result

    result["body_code"] = payload.get("status", {}).get("code")
    result["gdscode"] = payload.get("data", {}).get("gdscode")
    result["rc_rows"] = rc_rows(payload.get("data", {}).get("InfoStores", []))
    return result


def print_direct(label: str, data: Dict):
    print(
        f"{label}: http={data['http_status']} body={data['body_code']} "
        f"gdscode={data['gdscode']} rc={data['rc_rows']}"
    )


def inspect_article(http, session_id: str, article: str):
    print(f"\n=== ARTICLE {article} ===")
    print(f"variants={_build_article_variants(article)}")

    samara_bulk, samara_loose_entries = bulk_lookup(http, session_id, SAMARA_STORE_ID, article)
    moscow_bulk, moscow_loose_entries = bulk_lookup(http, session_id, MOSCOW_STORE_ID, article)
    print(f"bulk_samara={samara_bulk[:10]}")
    print(f"bulk_moscow={moscow_bulk[:10]}")
    print(
        f"bulk_samara_loose_stock={resolve_stock_loose(article, samara_loose_entries)} "
        f"bulk_samara_loose_gds={resolve_gds_code_loose(article, samara_loose_entries)}"
    )
    print(
        f"bulk_moscow_loose_stock={resolve_stock_loose(article, moscow_loose_entries)} "
        f"bulk_moscow_loose_gds={resolve_gds_code_loose(article, moscow_loose_entries)}"
    )

    tried = set()
    for variant in _build_article_variants(article):
        for request_type in ("cli", "mnf", "etm"):
            key = (variant, request_type)
            if key in tried:
                continue
            tried.add(key)
            data = direct_lookup(http, session_id, variant, request_type)
            print_direct(f"direct {variant} {request_type}", data)

    moscow_gds: Optional[str] = None
    for row in moscow_bulk:
        gds = row.get("GdsCode")
        if gds:
            moscow_gds = str(gds)
            break

    if moscow_gds:
        gds_data = direct_lookup(http, session_id, moscow_gds, "etm")
        print_direct(f"direct gds {moscow_gds} etm", gds_data)


def main(argv: List[str]):
    articles = argv[1:] or ["33126", "53220", "53238", "23230"]
    http = create_etm_session()
    session_id = get_etm_session(http)
    if not session_id:
        raise SystemExit("Failed to obtain ETM session")

    for article in articles:
        inspect_article(http, session_id, article)


if __name__ == "__main__":
    main(sys.argv)
