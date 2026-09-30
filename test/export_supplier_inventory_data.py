"""Read supplier catalog and stock snapshots for a one-time XLSX export."""

from __future__ import annotations

import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import local
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import iek_stock_sync_local as iek
import rs_sync_local as rs


OUTPUT_PATH = Path(__file__).parent / "tmp" / "supplier_inventory_snapshot.json"
CATALOG_CATEGORIES = ("instock", "custom")
CATALOG_PAGE_SIZE = 1000
RS_WORKERS = 6
_thread_context = local()


def rs_worker_session():
    session = getattr(_thread_context, "session", None)
    if session is None:
        session = rs.create_rs_session()
        _thread_context.session = session
    return session


def fetch_rs_catalog_page(warehouse_id, category, page):
    url = (
        f"{config.RS_BASE_URL}/position/{warehouse_id}/{category}"
        f"?page={page}&rows={CATALOG_PAGE_SIZE}"
    )
    response = rs.rs_get_with_retry(
        rs_worker_session(),
        url,
        rs.get_rs_headers(),
        timeout=30,
        label=f"RS export catalog warehouse {warehouse_id} page {page}",
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"RS catalog HTTP {response.status_code} for warehouse {warehouse_id}, "
            f"category {category}, page {page}"
        )
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not isinstance(meta, dict):
        raise RuntimeError(
            f"RS catalog response is incomplete for warehouse {warehouse_id}, "
            f"category {category}, page {page}"
        )
    try:
        last_page = int(meta["last_page"])
        expected_rows = int(meta["rows_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("RS catalog response has invalid pagination metadata") from exc
    if last_page < 1 or expected_rows < 0:
        raise RuntimeError("RS catalog response has impossible pagination metadata")
    if page < last_page and not items:
        raise RuntimeError("RS catalog returned an empty intermediate page")
    time.sleep(rs.RS_API_MIN_PAGE_DELAY_SECONDS)
    return page, items, last_page, expected_rows


def fetch_rs_catalog(warehouse_id):
    by_code = {}
    category_counts = {}
    for category in CATALOG_CATEGORIES:
        first_page, first_items, last_page, expected_rows = fetch_rs_catalog_page(
            warehouse_id, category, 1
        )
        page_results = [(first_page, first_items)]
        with ThreadPoolExecutor(max_workers=RS_WORKERS) as executor:
            futures = {
                executor.submit(fetch_rs_catalog_page, warehouse_id, category, page): page
                for page in range(2, last_page + 1)
            }
            completed = 1
            for future in as_completed(futures):
                page, items, response_last_page, response_rows = future.result()
                if response_last_page != last_page or response_rows != expected_rows:
                    raise RuntimeError(
                        f"RS catalog pagination changed during read for warehouse {warehouse_id}, "
                        f"category {category}"
                    )
                page_results.append((page, items))
                completed += 1
                if completed % 100 == 0 or completed == last_page:
                    print(
                        f"RS {warehouse_id} {category}: {completed}/{last_page} pages",
                        flush=True,
                    )
        rows_read = 0
        for _, items in page_results:
            for item in items:
                if not isinstance(item, dict) or not str(item.get("CODE", "")).strip():
                    raise RuntimeError(
                        f"RS catalog has a product without CODE for warehouse {warehouse_id}"
                    )
                code = str(item["CODE"]).strip()
                if code in by_code and by_code[code] != item:
                    existing = by_code[code]
                    for key in ("VENDOR_CODE", "ARTICLE", "NAME", "BRAND"):
                        if existing.get(key) not in (None, "") and item.get(key) not in (None, ""):
                            if str(existing[key]).strip() != str(item[key]).strip():
                                raise RuntimeError(
                                    f"RS catalog has conflicting records for internal code {code}"
                                )
                    merged = dict(existing)
                    merged.update({k: v for k, v in item.items() if v not in (None, "")})
                    by_code[code] = merged
                else:
                    by_code[code] = item
            rows_read += len(items)
        if rows_read != expected_rows:
            raise RuntimeError(
                f"RS catalog was incomplete for warehouse {warehouse_id}, category {category}: "
                f"read {rows_read} of {expected_rows}"
            )
        category_counts[category] = rows_read
    if not by_code:
        raise RuntimeError(f"RS catalog was empty for warehouse {warehouse_id}")
    return list(by_code.values()), category_counts


def fetch_rs_residue_page(warehouse_id, page):
    url = f"{config.RS_BASE_URL}/residue/all/{warehouse_id}?page={page}&rows=200&category=all"
    response = rs.rs_get_with_retry(
        rs_worker_session(),
        url,
        rs.get_rs_headers(),
        timeout=30,
        label=f"RS export residue warehouse {warehouse_id} page {page}",
    )
    if response.status_code != 200:
        raise RuntimeError(f"RS residue HTTP {response.status_code} for warehouse {warehouse_id}, page {page}")
    payload = response.json()
    residues = payload.get("residues") if isinstance(payload, dict) else None
    if not isinstance(residues, list):
        raise RuntimeError(f"RS residue response is incomplete for warehouse {warehouse_id}, page {page}")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    header_pages = response.headers.get("x-pagination-page-count")
    try:
        last_page = int(header_pages or meta["last_page"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("RS residue response omitted page-count metadata") from exc
    raw_total = response.headers.get("x-pagination-total-count", meta.get("rows_count"))
    try:
        total_rows = int(raw_total) if raw_total is not None else None
    except (TypeError, ValueError) as exc:
        raise RuntimeError("RS residue response has invalid total-count metadata") from exc
    if last_page < 1 or (total_rows is not None and total_rows < 0):
        raise RuntimeError("RS residue response has impossible pagination metadata")
    if page < last_page and not residues:
        raise RuntimeError("RS residue returned an empty intermediate page")
    time.sleep(rs.RS_API_MIN_PAGE_DELAY_SECONDS)
    return page, residues, last_page, total_rows


def fetch_all_rs_stocks_concurrent(warehouse_id):
    snapshot = rs.RSStockSnapshot()
    first_page, first_rows, last_page, expected_total = fetch_rs_residue_page(warehouse_id, 1)
    page_results = [(first_page, first_rows)]
    with ThreadPoolExecutor(max_workers=RS_WORKERS) as executor:
        futures = {
            executor.submit(fetch_rs_residue_page, warehouse_id, page): page
            for page in range(2, last_page + 1)
        }
        completed = 1
        for future in as_completed(futures):
            page, items, response_last_page, total_rows = future.result()
            if response_last_page != last_page or (
                total_rows is not None and expected_total is not None and total_rows != expected_total
            ):
                raise RuntimeError(f"RS residue pagination changed during read for warehouse {warehouse_id}")
            page_results.append((page, items))
            completed += 1
            if completed % 50 == 0 or completed == last_page:
                print(f"RS {warehouse_id} residue: {completed}/{last_page} pages", flush=True)

    records_read = 0
    for _, items in page_results:
        records_read += len(items)
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or item.get("CODE") in (None, ""):
                snapshot.invalid_products += 1
                continue
            code = str(item["CODE"]).strip()
            if not code:
                snapshot.invalid_products += 1
                continue
            if "RESIDUE" not in item:
                snapshot.invalid_codes.add(code)
                snapshot.invalid_products += 1
                continue
            try:
                stock = float(item["RESIDUE"])
            except (TypeError, ValueError):
                snapshot.invalid_codes.add(code)
                snapshot.invalid_products += 1
                continue
            if stock < 0 or not math.isfinite(stock):
                snapshot.invalid_codes.add(code)
                snapshot.invalid_products += 1
                continue
            snapshot[code] = int(stock) if stock.is_integer() else stock
    if expected_total is not None and records_read != expected_total:
        raise RuntimeError(
            f"RS residue was incomplete for warehouse {warehouse_id}: "
            f"read {records_read} of {expected_total}"
        )
    return snapshot


def valid_optional_stock(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Non-numeric stock returned for {label}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise RuntimeError(f"Invalid stock returned for {label}")
    return int(number) if number.is_integer() else number


def fetch_iek_snapshot():
    session = iek.create_session()
    iek.login(session, iek.get_api_key())
    catalog = iek.request_json(session, "GET", iek.CATALOG_URL)
    categories = catalog.get("categories")
    if not isinstance(categories, list) or not categories:
        raise RuntimeError("IEK catalog has no categories")

    products_by_article = {}
    warehouses = {}
    snapshots = set()
    raw_product_count = 0
    category_counts = {}
    for category in categories:
        if not isinstance(category, dict) or not category.get("slug"):
            raise RuntimeError("IEK catalog contains a category without a slug")
        slug = str(category["slug"])
        name = str(category.get("name") or slug)
        url = iek.BALANCES_URL.format(slug=quote(slug, safe=""))
        payload = iek.request_json(session, "GET", url)
        products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(products, list):
            raise RuntimeError(f"IEK balance catalog is incomplete for category {slug}")
        snapshot_date = payload.get("date")
        if snapshot_date:
            snapshots.add(str(snapshot_date))
        category_counts[name] = len(products)
        raw_product_count += len(products)

        for product in products:
            if not isinstance(product, dict) or not str(product.get("article", "")).strip():
                raise RuntimeError(f"IEK category {slug} contains a product without article")
            article = str(product["article"]).strip()
            normalized = iek.normalize_article(article)
            available = iek.validate_stock(product.get("available"), article)
            warehouse_data = product.get("warehouseData")
            if not isinstance(warehouse_data, list):
                raise RuntimeError(f"IEK warehouse data is missing for article {article}")
            balances = {}
            for warehouse in warehouse_data:
                if not isinstance(warehouse, dict):
                    raise RuntimeError(f"IEK warehouse row is invalid for article {article}")
                warehouse_id = str(warehouse.get("warehouseId", "")).strip()
                warehouse_name = str(warehouse.get("warehouseName", "")).strip()
                if not warehouse_id or not warehouse_name:
                    raise RuntimeError(f"IEK warehouse identity is missing for article {article}")
                prior_name = warehouses.get(warehouse_id)
                if prior_name and prior_name != warehouse_name:
                    raise RuntimeError(f"IEK warehouse {warehouse_id} has conflicting names")
                warehouses[warehouse_id] = warehouse_name
                balances[warehouse_id] = valid_optional_stock(
                    warehouse.get("availableAmount"),
                    f"{article} / {warehouse_name}",
                )
            record = {
                "article": article,
                "name": str(product.get("name") or "").strip(),
                "units": product.get("units"),
                "available": available,
                "warehouse_balances": balances,
                "categories": [name],
            }
            if normalized in products_by_article:
                previous = products_by_article[normalized]
                if previous["available"] != available or previous["warehouse_balances"] != balances:
                    raise RuntimeError(f"IEK returned conflicting balances for article {article}")
                if name not in previous["categories"]:
                    previous["categories"].append(name)
                if not previous["name"] and record["name"]:
                    previous["name"] = record["name"]
            else:
                products_by_article[normalized] = record
        if iek.CATEGORY_REQUEST_INTERVAL:
            time.sleep(iek.CATEGORY_REQUEST_INTERVAL)

    if not products_by_article or not warehouses:
        raise RuntimeError("IEK API returned no products or no warehouse breakdown")
    return {
        "categories": category_counts,
        "raw_product_count": raw_product_count,
        "products": list(products_by_article.values()),
        "warehouses": [
            {"id": warehouse_id, "name": warehouse_name}
            for warehouse_id, warehouse_name in sorted(
                warehouses.items(), key=lambda item: (item[1].casefold(), item[0])
            )
        ],
        "snapshot_dates": sorted(snapshots),
    }


def main():
    output = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "russvet": {},
    }
    for warehouse_id, warehouse_name in (
        (config.RS_WAREHOUSE_ID, "Самара"),
        (config.RS_MSK_WAREHOUSE_ID, "Москва"),
    ):
        catalog, catalog_counts = fetch_rs_catalog(warehouse_id)
        print(
            f"RS {warehouse_name}: каталог получен ({len(catalog)} позиций), читаю остатки",
            flush=True,
        )
        stock_snapshot = fetch_all_rs_stocks_concurrent(warehouse_id)
        rows = []
        for item in catalog:
            code = str(item["CODE"]).strip()
            if code in stock_snapshot.invalid_codes:
                stock = None
            else:
                stock = stock_snapshot.get(code, 0)
            rows.append(
                {
                    "code": code,
                    "vendor_code": str(item.get("VENDOR_CODE") or "").strip(),
                    "article": str(item.get("ARTICLE") or "").strip(),
                    "name": str(item.get("NAME") or "").strip(),
                    "brand": str(item.get("BRAND") or "").strip(),
                    "category": str(item.get("CATEGORY") or "").strip(),
                    "unit": str(item.get("UOM") or "").strip(),
                    "unit_okei": str(item.get("UOM_OKEI") or "").strip(),
                    "stock": stock,
                }
            )
        output["russvet"][warehouse_name] = {
            "warehouse_id": warehouse_id,
            "catalog_counts": catalog_counts,
            "catalog_count": len(catalog),
            "catalog_without_article": sum(
                not row["vendor_code"] and not row["article"] for row in rows
            ),
            "invalid_stock_rows": stock_snapshot.invalid_products,
            "stock_codes_without_catalog": sum(
                code not in {row["code"] for row in rows} for code in stock_snapshot
            ),
            "rows": rows,
        }
        print(f"RS {warehouse_name}: срез готов ({len(rows)} позиций)", flush=True)
    output["iek"] = fetch_iek_snapshot()
    output["fetched_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print("Supplier data snapshot saved.")
    for warehouse_name, data in output["russvet"].items():
        print(
            f"РС {warehouse_name} warehouse={data['warehouse_id']} "
            f"products={data['catalog_count']} "
            f"instock={data['catalog_counts'].get('instock', 0)} "
            f"custom={data['catalog_counts'].get('custom', 0)} "
            f"stock_rows_invalid={data['invalid_stock_rows']} "
            f"catalog_without_article={data['catalog_without_article']}"
        )
    iek_data = output["iek"]
    print(
        f"IEK products={len(iek_data['products'])} "
        f"category_records={iek_data['raw_product_count']} "
        f"warehouses={len(iek_data['warehouses'])} "
        f"snapshot_dates={','.join(iek_data['snapshot_dates'])}"
    )
    for warehouse in iek_data["warehouses"]:
        print(f"IEK warehouse: {warehouse['name']}")


if __name__ == "__main__":
    main()
