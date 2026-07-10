# -*- coding: utf-8 -*-
"""Export IEK articles from ETM client nomenclature with ETM stock to XLSX.

This is a diagnostic/export script. It does not read or write Google Sheets.
It creates local report files under test/.
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
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


REPORT_ID = "40029846"
DEFAULT_STORES = [13, 14]
DEFAULT_BRAND = "IEK"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


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


def create_http_session():
    label, source_ip = choose_bypass_source()
    http = requests.Session()
    http.trust_env = False
    adapter = SourceAddressAdapter(source_ip)
    http.mount("http://", adapter)
    http.mount("https://", adapter)
    print(f"ETM bypass source: {label} ({source_ip})")
    return http


def login_etm(http):
    response = http.post(
        "https://ipro.etm.ru/api/v1/user/login",
        params={"log": config.ETM_LOGIN, "pwd": config.ETM_PASSWORD},
        headers={"Accept": "application/json", "User-Agent": "Checksheets IEK export"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", {})
    if status.get("code") != 200:
        raise RuntimeError(f"ETM login failed: {status}")
    return payload["data"]["session"]


def normalize_code(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\.0+$", "", raw)
    raw = re.sub(r"^ETM", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\D", "", raw)


def normalize_article(value):
    return re.sub(r"[^A-ZА-ЯЁ0-9]", "", str(value or "").upper())


def parse_int(value):
    try:
        return int(float(str(value or "0").replace(",", ".")))
    except Exception:
        return 0


def create_nomenclature_job(http, session_id):
    url = f"https://ipro.etm.ru/api/v1/job/create/{REPORT_ID}?session-id={session_id}"
    response = http.post(url, headers={"Accept": "application/json"}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", {})
    if status.get("code") != 200:
        raise RuntimeError(f"ETM job create failed: {status}")
    uuid = payload.get("data", {}).get("uuid")
    if not uuid:
        raise RuntimeError(f"ETM job create returned no uuid: {payload}")
    return uuid


def poll_nomenclature_job(http, session_id, uuid, poll_seconds, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last_payload = None
    while time.time() < deadline:
        url = f"https://ipro.etm.ru/api/v1/job/{uuid}?session-id={session_id}"
        response = http.get(url, headers={"Accept": "application/json"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        status = payload.get("status", {})
        if status.get("code") != 200:
            raise RuntimeError(f"ETM job poll failed: {status}")

        rows = payload.get("data", {}).get("rows", [])
        row = rows[0] if rows else {}
        state = str(row.get("state", ""))
        print(f"ETM nomenclature job {uuid}: state={state or '?'} msg={row.get('msg', '')}")
        if state == "1":
            urls = row.get("urls") or []
            if not urls:
                raise RuntimeError(f"ETM job completed without urls: {payload}")
            first_url = urls[0]
            if isinstance(first_url, dict):
                first_url = first_url.get("url") or first_url.get("href") or ""
            if not first_url:
                raise RuntimeError(f"ETM job completed with unusable urls: {payload}")
            return first_url
        if state == "2":
            raise RuntimeError(f"ETM job failed: {row}")

        time.sleep(poll_seconds)

    raise TimeoutError(f"ETM job was not ready in {timeout_seconds}s. uuid={uuid}; last={last_payload}")


def download_json_report(http, report_url, output_path):
    url = urljoin("https://ipro.etm.ru", str(report_url))
    response = http.get(url, timeout=180)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return json.loads(response.content.decode("utf-8-sig"))


def iter_dict_rows(value):
    if isinstance(value, dict):
        rows = value.get("rows")
        if isinstance(rows, list):
            for item in rows:
                yield from iter_dict_rows(item)
            return
        data = value.get("data")
        if isinstance(data, (dict, list)):
            yield from iter_dict_rows(data)
            return
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_dict_rows(item)


def first_value(row, names):
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, ""):
            return lowered[name.lower()]
    return ""


def is_brand_match(row, brand):
    wanted = brand.strip().upper()
    values = [
        first_value(row, ["brand", "manuf", "mnfName", "mnf_name", "gdsMnfName", "manufacturer"]),
        first_value(row, ["brand_code", "mnf_code", "gdsMnfCode"]),
    ]
    return any(wanted in str(value).strip().upper() for value in values if value not in (None, ""))


def extract_goods_row(row):
    etm_code = normalize_code(first_value(row, ["id", "gdsCode", "gdscode", "code", "etm_code", "ETM"]))
    raw_id = first_value(row, ["id", "gdsCode", "gdscode", "code", "etm_code", "ETM"])
    if not etm_code and str(raw_id).strip().lower().startswith("0x"):
        try:
            etm_code = str(int(str(raw_id).strip(), 16))
        except ValueError:
            etm_code = ""

    article = str(first_value(row, ["article", "gdsArt", "art", "mnf_art", "mnfArticle"])).strip()
    name = str(first_value(row, ["name", "gdsName", "gdsNameTitle"])).strip()
    brand = str(first_value(row, ["brand", "manuf", "mnfName", "mnf_name", "gdsMnfName"])).strip()
    brand_code = str(first_value(row, ["brand_code", "mnf_code", "gdsMnfCode"])).strip()
    class_name = str(first_value(row, ["class", "class_name", "gdsInfoClass81"])).strip()

    return {
        "etm_code": etm_code,
        "article": article,
        "brand": brand,
        "brand_code": brand_code,
        "name": name,
        "class": class_name,
    }


def fetch_store_remains(http, session_id, store_id):
    url = f"https://ipro.etm.ru/api/v1/goods/remains?store={store_id}&session-id={session_id}"
    response = http.get(url, headers={"Accept": "application/json"}, timeout=180)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", {})
    if status.get("code") != 200:
        raise RuntimeError(f"ETM remains failed for store={store_id}: {status}")

    by_gds = {}
    by_article = {}
    rows = payload.get("data", {}).get("rows", [])
    for item in rows:
        stock = parse_int(item.get("RemInfo"))
        if stock <= 0:
            continue
        gds = normalize_code(item.get("GdsCode"))
        article = normalize_article(item.get("Article"))
        if gds:
            by_gds[gds] = by_gds.get(gds, 0) + stock
        if article:
            by_article[article] = by_article.get(article, 0) + stock

    print(f"store={store_id}: rows={len(rows)}, positive_gds={len(by_gds)}")
    return by_gds, by_article


def collect_iek_rows(goods_rows, stock_by_store):
    output = []
    seen = set()
    for goods in goods_rows:
        key = (goods["etm_code"], goods["article"], goods["name"])
        if key in seen:
            continue
        seen.add(key)

        row = dict(goods)
        total = 0
        article_norm = normalize_article(goods["article"])
        for store_id, lookups in stock_by_store.items():
            by_gds, by_article = lookups
            stock = by_gds.get(goods["etm_code"], 0) if goods["etm_code"] else 0
            if stock <= 0 and article_norm:
                stock = by_article.get(article_norm, 0)
            row[f"stock_{store_id}"] = stock
            total += stock
        row["stock_total"] = total
        output.append(row)
    return output


def write_csv(path, rows, headers):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def xlsx_col_name(index):
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def inline_string_cell(ref, value):
    value = "" if value is None else str(value)
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def number_cell(ref, value):
    return f'<c r="{ref}"><v>{parse_int(value)}</v></c>'


def write_minimal_xlsx(path, rows, headers):
    path.parent.mkdir(parents=True, exist_ok=True)
    numeric_headers = {h for h in headers if h.startswith("stock_")}
    sheet_rows = []
    all_rows = [dict(zip(headers, headers))] + rows
    for row_idx, row in enumerate(all_rows, start=1):
        cells = []
        for col_idx, header in enumerate(headers):
            ref = f"{xlsx_col_name(col_idx)}{row_idx}"
            value = row.get(header, "")
            if row_idx > 1 and header in numeric_headers:
                cells.append(number_cell(ref, value))
            else:
                cells.append(inline_string_cell(ref, value))
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="IEK stock" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", default=DEFAULT_BRAND, help="Brand filter, default IEK")
    parser.add_argument("--stores", default=",".join(map(str, DEFAULT_STORES)), help="Comma-separated ETM store ids")
    parser.add_argument("--job-uuid", default="", help="Poll an existing ETM nomenclature job uuid")
    parser.add_argument("--client-goods-json", default="", help="Use already downloaded ETM nomenclature JSON")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=10800)
    parser.add_argument("--limit", type=int, default=0, help="Limit exported rows for a smoke test")
    parser.add_argument("--output-prefix", default="")
    args = parser.parse_args()

    stores = [int(x.strip()) for x in args.stores.split(",") if x.strip()]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = Path(args.output_prefix or f"test/etm_iek_stock_{timestamp}")

    http = create_http_session()
    session_id = login_etm(http)

    if args.client_goods_json:
        goods_payload = json.loads(Path(args.client_goods_json).read_text(encoding="utf-8-sig"))
    else:
        uuid = args.job_uuid or create_nomenclature_job(http, session_id)
        print(f"ETM nomenclature uuid: {uuid}")
        report_url = poll_nomenclature_job(http, session_id, uuid, args.poll_seconds, args.timeout_seconds)
        raw_report_path = prefix.with_suffix(".client_goods.json")
        goods_payload = download_json_report(http, report_url, raw_report_path)
        print(f"Downloaded nomenclature report: {raw_report_path}")

    goods_rows = [
        extract_goods_row(row)
        for row in iter_dict_rows(goods_payload)
        if is_brand_match(row, args.brand)
    ]
    if args.limit:
        goods_rows = goods_rows[:args.limit]

    print(f"{args.brand} rows in nomenclature: {len(goods_rows)}")

    stock_by_store = {}
    for store_id in stores:
        stock_by_store[store_id] = fetch_store_remains(http, session_id, store_id)

    rows = collect_iek_rows(goods_rows, stock_by_store)
    headers = ["etm_code", "article", "brand", "brand_code", "name", "class"]
    headers.extend([f"stock_{store_id}" for store_id in stores])
    headers.append("stock_total")

    csv_path = prefix.with_suffix(".csv")
    xlsx_path = prefix.with_suffix(".xlsx")
    write_csv(csv_path, rows, headers)
    write_minimal_xlsx(xlsx_path, rows, headers)

    print(f"CSV:  {csv_path}")
    print(f"XLSX: {xlsx_path}")
    print(f"Rows: {len(rows)}; positive stock rows: {sum(1 for row in rows if parse_int(row.get('stock_total')) > 0)}")


if __name__ == "__main__":
    main()
