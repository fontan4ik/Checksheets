# -*- coding: utf-8 -*-
"""Recover ETM TR stock candidates from an old ETM sync log and bulk remains.

This script intentionally does not import etm_sync_multi_store.py because that
module configures logging with mode="w" and would truncate the live sync log.

Default mode is read-only: it writes CSV reports under test/. Use --write to
push the combined candidate values to ETM TR stocks columns.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

import gspread
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import gsheets_utils  # noqa: E402


ETM_TR_ETM_CODE_COL = 20
DIRECT_REQUEST_DELAY = float(os.getenv("ETM_RECOVERY_DIRECT_DELAY", "1.2"))


class SourceAddressAdapter(HTTPAdapter):
    def __init__(self, source_ip, **kwargs):
        self._source_address = (source_ip, 0)
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["source_address"] = self._source_address
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


def normalize(value):
    if not value:
        return ""
    value = str(value).strip()
    value = re.sub(r"\.0+$", "", value)
    value = re.sub(r"\(.*\)", "", value)
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def normalize_etm_code(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\.0+$", "", raw)
    raw = re.sub(r"^ETM", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\D", "", raw)


def enumerate_local_ipv4s():
    ips = []
    seen = set()

    def add_many(values):
        for value in values:
            if not value or value == "127.0.0.1" or value in seen:
                continue
            seen.add(value)
            ips.append(value)

    host = socket.gethostname()
    try:
        add_many(socket.gethostbyname_ex(host)[2])
    except OSError:
        pass
    try:
        add_many(addr[4][0] for addr in socket.getaddrinfo(host, None, socket.AF_INET))
    except OSError:
        pass
    return ips


def choose_bypass_source():
    override_ip = os.getenv("CHECKSHEETS_BYPASS_IP", "").strip()
    if override_ip:
        return os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "override").strip() or "override", override_ip

    candidates = enumerate_local_ipv4s()

    def rank(ip):
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            return (3, ip)
        if parsed.is_private:
            return (0, ip)
        if parsed.is_link_local:
            return (1, ip)
        return (2, ip)

    candidates.sort(key=rank)
    if not candidates:
        raise RuntimeError("No usable IPv4 source found. Set CHECKSHEETS_BYPASS_IP.")
    return os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "auto").strip() or "auto", candidates[0]


def create_etm_session():
    label, source_ip = choose_bypass_source()
    session = requests.Session()
    session.trust_env = False
    adapter = SourceAddressAdapter(source_ip)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    print(f"ETM bypass source: {label} ({source_ip})")
    return session


def login_etm(http, headers):
    response = http.post(
        "https://ipro.etm.ru/api/v1/user/login",
        params={"log": config.ETM_LOGIN, "pwd": config.ETM_PASSWORD},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", {})
    if status.get("code") != 200:
        raise RuntimeError(f"ETM login failed: {status}")
    return payload["data"]["session"]


def fetch_bulk_gds_lookup(http, headers, session_id, store_id, label):
    url = f"https://ipro.etm.ru/api/v1/goods/remains?store={store_id}&session-id={session_id}"
    print(f"Fetching remains for {label} store {store_id}...")
    response = http.get(url, headers=headers, timeout=120)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", {})
    if status.get("code") != 200:
        raise RuntimeError(f"ETM remains failed for {label}: {status}")

    rows = payload.get("data", {}).get("rows", [])
    gds_lookup = {}
    positive_rows = 0
    for item in rows:
        gds = normalize(item.get("GdsCode"))
        if not gds:
            continue
        try:
            stock = int(float(item.get("RemInfo", 0)))
        except Exception:
            stock = 0
        if stock <= 0:
            continue
        positive_rows += 1
        gds_lookup[gds] = gds_lookup.get(gds, 0) + stock

    print(f"  Got {len(rows)} rows for {label}; positive rows={positive_rows}; unique gds={len(gds_lookup)}")
    return gds_lookup


def normalize_brand(brand_name):
    brand = str(brand_name or "").strip().upper()
    if brand in ("ФЕРОН", "FERON"):
        return {"FERON", "ФЕРОН"}
    if brand in ("СТЕККЕР", "STEKKER"):
        return {"STEKKER", "СТЕККЕР"}
    if brand in ("САФФИТ", "SAFFIT"):
        return {"SAFFIT", "САФФИТ"}
    return {brand}


def check_brand_match(gs_brand, etm_brand):
    gs_set = normalize_brand(gs_brand)
    etm_set = normalize_brand(etm_brand)
    for gs_item in gs_set:
        for etm_item in etm_set:
            if gs_item and etm_item and (gs_item in etm_item or etm_item in gs_item):
                return True
    return False


def extract_rc_stocks(info_stores, store_ids):
    stock_by_store = {}
    store_ids_set = set(int(store_id) for store_id in store_ids)
    for store in info_stores or []:
        if (store.get("StoreType") or "").lower() != "rc":
            continue
        try:
            store_code = int(store.get("StoreCode"))
        except (TypeError, ValueError):
            continue
        if store_code not in store_ids_set or store_code in stock_by_store:
            continue
        try:
            qty = int(store.get("StoreQuantRem") or 0)
        except (TypeError, ValueError):
            qty = 0
        stock_by_store[store_code] = max(qty, 0)
    return stock_by_store


def fetch_direct_store_stocks(http, headers, session_id, item_id, request_type, store_ids):
    url = (
        f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(str(item_id))}/remains"
        f"?type={request_type}&session-id={session_id}"
    )
    last_kind = "network"
    for attempt in range(1, 4):
        try:
            response = http.get(url, headers=headers, timeout=30)
            if response.status_code == 429:
                last_kind = "rate_limited"
                time.sleep(DIRECT_REQUEST_DELAY * attempt * 2)
                continue
            if not response.text.strip():
                raise ValueError("Empty response body")
            payload = response.json()
        except json.JSONDecodeError:
            last_kind = "invalid_json"
            time.sleep(DIRECT_REQUEST_DELAY * attempt * 2)
            continue
        except Exception:
            last_kind = "network"
            time.sleep(DIRECT_REQUEST_DELAY * attempt * 2)
            continue

        status = payload.get("status", {})
        if response.status_code != 200 or status.get("code") != 200:
            return {}, None, "miss"

        data = payload.get("data", {})
        gdscode = data.get("gdscode") or data.get("id")
        if gdscode and "-" in str(gdscode):
            gdscode = str(gdscode).split("-", 1)[0]
        return extract_rc_stocks(data.get("InfoStores", []), store_ids), gdscode, "ok"

    return {}, None, last_kind


def fetch_etm_brand(http, session_id, gds_code, brand_cache):
    gds_code = str(gds_code or "").strip()
    if not gds_code:
        return ""
    if gds_code in brand_cache:
        return brand_cache[gds_code]

    url = f"https://ipro.etm.ru/api/v1/goods/{gds_code}?type=etm&session-id={session_id}"
    try:
        time.sleep(DIRECT_REQUEST_DELAY)
        response = http.get(url, headers={"Accept": "application/json"}, timeout=30)
        if response.status_code != 200:
            brand_cache[gds_code] = ""
            return ""
        payload = response.json()
        data = payload.get("data", {})
        brand = ""
        if "gdsMnfName" in data:
            brand = str(data.get("gdsMnfName") or "")
        elif data.get("rows") and isinstance(data["rows"], list):
            brand = str(data["rows"][0].get("mnf_name") or "")
        brand_cache[gds_code] = brand.strip().upper()
        return brand_cache[gds_code]
    except Exception:
        brand_cache[gds_code] = ""
        return ""


def parse_manual_resolves(log_path):
    pattern = re.compile(
        r"ETM TR resolved model=(?P<model>.+?) via (?P<rtype>\w+) "
        r"gds=(?P<gds>\d+): (?P<stocks>\{.*\})"
    )
    manual = {}
    events = []
    for line in Path(log_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.search(line)
        if not match:
            continue

        stock_by_store = {}
        for store, value in re.findall(r"(\d+):\s*(\d+)", match.group("stocks")):
            stock_by_store[int(store)] = int(value)

        model = match.group("model").strip()
        item = {
            "model": model,
            "model_norm": normalize(model),
            "request_type": match.group("rtype"),
            "gds": match.group("gds"),
            "stock_smr": stock_by_store.get(13, 0),
            "stock_msk": stock_by_store.get(14, 0),
            "line": line,
        }
        events.append(item)
        manual.setdefault(item["model_norm"], item)
    return manual, events


def get_stock_columns(headers):
    lowered = [str(h).strip().lower() for h in headers]
    return lowered.index("stocks msk") + 1, lowered.index("stocks smr") + 1


def build_reports(log_path, output_prefix):
    manual_by_model, manual_events = parse_manual_resolves(log_path)

    ws = gsheets_utils.get_worksheet("ETM TR")
    data = ws.get_all_values()
    col_stock_msk, col_stock_smr = get_stock_columns(data[0])

    http = create_etm_session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    session_id = login_etm(http, headers)
    samara_gds = fetch_bulk_gds_lookup(http, headers, session_id, 13, "Samara")
    moscow_gds = fetch_bulk_gds_lookup(http, headers, session_id, 14, "Moscow")

    combined_rows = []
    manual_row_count = 0
    bulk_smr_count = 0
    bulk_msk_count = 0

    for row_number, row in enumerate(data[1:], start=2):
        offer = row[0].strip() if len(row) > 0 else ""
        model = row[1].strip() if len(row) > 1 else ""
        brand = row[2].strip() if len(row) > 2 else ""
        etm_code = normalize_etm_code(row[ETM_TR_ETM_CODE_COL - 1] if len(row) >= ETM_TR_ETM_CODE_COL else "")
        model_norm = normalize(model)

        manual = manual_by_model.get(model_norm)
        manual_smr = manual["stock_smr"] if manual else 0
        manual_msk = manual["stock_msk"] if manual else 0
        bulk_smr = samara_gds.get(normalize(etm_code), 0)
        bulk_msk = moscow_gds.get(normalize(etm_code), 0)

        if manual_smr or manual_msk:
            manual_row_count += 1
        if bulk_smr > 0:
            bulk_smr_count += 1
        if bulk_msk > 0:
            bulk_msk_count += 1

        combined_smr = manual_smr if manual_smr > 0 else bulk_smr
        combined_msk = manual_msk if manual_msk > 0 else bulk_msk
        source_smr = "manual_log" if manual_smr > 0 else ("bulk_remains" if bulk_smr > 0 else "")
        source_msk = "manual_log" if manual_msk > 0 else ("bulk_remains" if bulk_msk > 0 else "")

        combined_rows.append(
            {
                "row": row_number,
                "offer": offer,
                "model": model,
                "brand": brand,
                "etm_code_t": etm_code,
                "manual_smr": manual_smr,
                "manual_msk": manual_msk,
                "manual_gds": manual["gds"] if manual else "",
                "manual_request_type": manual["request_type"] if manual else "",
                "bulk_smr": bulk_smr,
                "bulk_msk": bulk_msk,
                "combined_smr": combined_smr,
                "combined_msk": combined_msk,
                "source_smr": source_smr,
                "source_msk": source_msk,
            }
        )

    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    combined_path = prefix.with_name(prefix.name + "_combined.csv")
    manual_path = prefix.with_name(prefix.name + "_manual_events.csv")

    with manual_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["model", "request_type", "gds", "stock_smr", "stock_msk", "line"],
        )
        writer.writeheader()
        for item in manual_events:
            writer.writerow(
                {
                    "model": item["model"],
                    "request_type": item["request_type"],
                    "gds": item["gds"],
                    "stock_smr": item["stock_smr"],
                    "stock_msk": item["stock_msk"],
                    "line": item["line"],
                }
            )

    with combined_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(combined_rows[0].keys()))
        writer.writeheader()
        writer.writerows(combined_rows)

    stats = {
        "sheet_rows": len(combined_rows),
        "manual_events": len(manual_events),
        "manual_matched_sheet_rows": manual_row_count,
        "bulk_smr_positive_rows": bulk_smr_count,
        "bulk_msk_positive_rows": bulk_msk_count,
        "combined_smr_positive_rows": sum(1 for row in combined_rows if row["combined_smr"] > 0),
        "combined_msk_positive_rows": sum(1 for row in combined_rows if row["combined_msk"] > 0),
        "col_stock_msk": col_stock_msk,
        "col_stock_smr": col_stock_smr,
        "combined_path": str(combined_path),
        "manual_path": str(manual_path),
    }
    return ws, combined_rows, stats


def verify_bulk_candidates(rows, output_prefix, limit=0):
    candidates = [
        row for row in rows
        if row["etm_code_t"] and (row["bulk_smr"] > 0 or row["bulk_msk"] > 0)
    ]
    if limit:
        candidates = candidates[:limit]

    http = create_etm_session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    session_id = login_etm(http, headers)
    brand_cache = {}
    direct_cache = {}
    verified_rows = []

    for index, row in enumerate(candidates, start=1):
        cache_key = (row["etm_code_t"], row["brand"])
        if cache_key in direct_cache:
            direct = direct_cache[cache_key]
        else:
            stock_by_store, gdscode, result_kind = fetch_direct_store_stocks(
                http,
                headers,
                session_id,
                row["etm_code_t"],
                "etm",
                [14, 13],
            )
            brand_ok = True
            etm_brand = ""
            if result_kind == "ok" and any(stock_by_store.values()) and row["brand"]:
                etm_brand = fetch_etm_brand(http, session_id, gdscode or row["etm_code_t"], brand_cache)
                brand_ok = check_brand_match(row["brand"], etm_brand) if etm_brand else True
            direct = {
                "result_kind": result_kind,
                "gdscode": gdscode or "",
                "stock_smr": stock_by_store.get(13, 0) if brand_ok else 0,
                "stock_msk": stock_by_store.get(14, 0) if brand_ok else 0,
                "brand_ok": brand_ok,
                "etm_brand": etm_brand,
            }
            direct_cache[cache_key] = direct
            time.sleep(DIRECT_REQUEST_DELAY)

        verified = dict(row)
        verified.update(
            {
                "direct_kind": direct["result_kind"],
                "direct_gdscode": direct["gdscode"],
                "direct_etm_brand": direct["etm_brand"],
                "direct_brand_ok": direct["brand_ok"],
                "direct_smr": direct["stock_smr"],
                "direct_msk": direct["stock_msk"],
                "direct_or_manual_smr": row["manual_smr"] if row["manual_smr"] > 0 else direct["stock_smr"],
                "direct_or_manual_msk": row["manual_msk"] if row["manual_msk"] > 0 else direct["stock_msk"],
            }
        )
        verified_rows.append(verified)

        if index % 100 == 0 or index == len(candidates):
            print(f"verified_candidates: {index}/{len(candidates)}")

    path = Path(output_prefix).with_name(Path(output_prefix).name + "_bulk_direct_verified.csv")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(verified_rows[0].keys()) if verified_rows else [])
        if verified_rows:
            writer.writeheader()
            writer.writerows(verified_rows)

    stats = {
        "bulk_candidate_rows": len(candidates),
        "direct_verified_path": str(path),
        "direct_smr_positive_rows": sum(1 for row in verified_rows if row["direct_smr"] > 0),
        "direct_msk_positive_rows": sum(1 for row in verified_rows if row["direct_msk"] > 0),
        "direct_or_manual_smr_positive_rows": sum(1 for row in verified_rows if row["direct_or_manual_smr"] > 0),
        "direct_or_manual_msk_positive_rows": sum(1 for row in verified_rows if row["direct_or_manual_msk"] > 0),
    }
    return verified_rows, stats


def load_combined_rows(path):
    int_fields = {
        "row",
        "manual_smr",
        "manual_msk",
        "bulk_smr",
        "bulk_msk",
        "combined_smr",
        "combined_msk",
    }
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = dict(raw)
            for field in int_fields:
                try:
                    row[field] = int(row.get(field) or 0)
                except ValueError:
                    row[field] = 0
            rows.append(row)
    return rows


def get_sheet_and_stock_columns():
    ws = gsheets_utils.get_worksheet("ETM TR")
    headers = ws.row_values(1)
    col_stock_msk, col_stock_smr = get_stock_columns(headers)
    return ws, col_stock_msk, col_stock_smr


def load_verified_rows(path):
    int_fields = {
        "row",
        "direct_or_manual_smr",
        "direct_or_manual_msk",
    }
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = dict(raw)
            for field in int_fields:
                try:
                    row[field] = int(row.get(field) or 0)
                except ValueError:
                    row[field] = 0
            rows.append(row)
    return rows


def write_combined(ws, rows, col_stock_msk, col_stock_smr):
    msk_values = [[row["combined_msk"]] for row in rows]
    smr_values = [[row["combined_smr"]] for row in rows]
    msk_range = f"{gspread.utils.rowcol_to_a1(2, col_stock_msk)}:{gspread.utils.rowcol_to_a1(1 + len(rows), col_stock_msk)}"
    smr_range = f"{gspread.utils.rowcol_to_a1(2, col_stock_smr)}:{gspread.utils.rowcol_to_a1(1 + len(rows), col_stock_smr)}"
    print(f"Writing MSK range {msk_range} and SMR range {smr_range}...")
    ws.update(values=msk_values, range_name=msk_range)
    ws.update(values=smr_values, range_name=smr_range)


def write_verified_overlay(ws, all_rows, verified_rows, col_stock_msk, col_stock_smr):
    by_sheet_row = {row["row"]: row for row in verified_rows}
    msk_values = []
    smr_values = []
    for row in all_rows:
        verified = by_sheet_row.get(row["row"])
        if verified:
            msk_values.append([verified["direct_or_manual_msk"]])
            smr_values.append([verified["direct_or_manual_smr"]])
        elif row.get("manual_smr", 0) > 0 or row.get("manual_msk", 0) > 0:
            msk_values.append([row.get("manual_msk", 0)])
            smr_values.append([row.get("manual_smr", 0)])
        else:
            msk_values.append([0])
            smr_values.append([0])

    msk_range = f"{gspread.utils.rowcol_to_a1(2, col_stock_msk)}:{gspread.utils.rowcol_to_a1(1 + len(all_rows), col_stock_msk)}"
    smr_range = f"{gspread.utils.rowcol_to_a1(2, col_stock_smr)}:{gspread.utils.rowcol_to_a1(1 + len(all_rows), col_stock_smr)}"
    print(f"Writing verified overlay MSK range {msk_range} and SMR range {smr_range}...")
    ws.update(values=msk_values, range_name=msk_range)
    ws.update(values=smr_values, range_name=smr_range)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log",
        default=str(ROOT / "logs" / "etm_sync_multi.before_lldb_20260610_2014.log"),
        help="Old ETM sync log with ETM TR resolved lines.",
    )
    parser.add_argument(
        "--output-prefix",
        default=str(ROOT / "test" / "etm_tr_recovery_20260610"),
    )
    parser.add_argument("--write", action="store_true", help="Write combined candidates to ETM TR stocks columns.")
    parser.add_argument(
        "--verify-bulk-direct",
        action="store_true",
        help="Direct-check only rows that were positive in bulk remains.",
    )
    parser.add_argument(
        "--verify-limit",
        type=int,
        default=0,
        help="Limit direct bulk verification rows for testing.",
    )
    parser.add_argument(
        "--combined-csv",
        default="",
        help="Use an existing combined CSV instead of re-fetching bulk remains.",
    )
    parser.add_argument(
        "--write-verified",
        action="store_true",
        help="Write direct-verified bulk/manual overlay to ETM TR stocks columns.",
    )
    parser.add_argument(
        "--write-existing-verified-csv",
        default="",
        help="Write an existing *_bulk_direct_verified.csv without re-running direct checks.",
    )
    args = parser.parse_args()

    if args.write_existing_verified_csv:
        ws, col_stock_msk, col_stock_smr = get_sheet_and_stock_columns()
        all_rows = load_combined_rows(args.combined_csv)
        verified_rows = load_verified_rows(args.write_existing_verified_csv)
        write_verified_overlay(ws, all_rows, verified_rows, col_stock_msk, col_stock_smr)
        print(f"written_existing_verified_csv: {args.write_existing_verified_csv}")
        print(f"verified_rows: {len(verified_rows)}")
        print(f"verified_smr_positive_rows: {sum(1 for row in verified_rows if row['direct_or_manual_smr'] > 0)}")
        print(f"verified_msk_positive_rows: {sum(1 for row in verified_rows if row['direct_or_manual_msk'] > 0)}")
        return

    if args.combined_csv:
        ws, col_stock_msk, col_stock_smr = get_sheet_and_stock_columns()
        rows = load_combined_rows(args.combined_csv)
        stats = {
            "sheet_rows": len(rows),
            "col_stock_msk": col_stock_msk,
            "col_stock_smr": col_stock_smr,
            "combined_path": args.combined_csv,
            "combined_smr_positive_rows": sum(1 for row in rows if row["combined_smr"] > 0),
            "combined_msk_positive_rows": sum(1 for row in rows if row["combined_msk"] > 0),
        }
    else:
        ws, rows, stats = build_reports(args.log, args.output_prefix)

    for key, value in stats.items():
        print(f"{key}: {value}")

    if args.write:
        write_combined(ws, rows, stats["col_stock_msk"], stats["col_stock_smr"])
        print("write_complete: true")
    else:
        print("write_complete: false")

    if args.verify_bulk_direct:
        verified_rows, verify_stats = verify_bulk_candidates(
            rows,
            args.output_prefix,
            limit=args.verify_limit,
        )
        for key, value in verify_stats.items():
            print(f"{key}: {value}")
        if args.write_verified:
            write_verified_overlay(
                ws,
                rows,
                verified_rows,
                stats["col_stock_msk"],
                stats["col_stock_smr"],
            )
            print("write_verified_complete: true")
        else:
            print("write_verified_complete: false")


if __name__ == "__main__":
    main()
