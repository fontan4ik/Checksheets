import requests
import base64
import time
import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
import config
import gsheets_utils
from network_bypass import SourceAddressAdapter
from telegram_notifier import send_telegram_alert


RS_RETRYABLE_HTTP_STATUSES = {404, 408, 425, 429, 500, 502, 503, 504}
RS_MAX_REQUEST_ATTEMPTS = 7
RS_API_MIN_PAGE_DELAY_SECONDS = 0.2
RS_CATALOG_SNAPSHOT_ATTEMPTS = 3

# These Ozon offers sell complete 305 m coils; RS reports metres and cut lots.
# Only RS SMR is converted. RS MSK retains its existing source units.
RS_305M_COIL_MODELS = frozenset({
    "LC1-C5E04-121-T-R",
    "LC1-C5E04-121-T-P-R",
    "LC1-C5E04-321-T-P-R",
    "LC1-C5E04-311",
    "LC1-C5E04-111-T-R",
})


def parse_rs_coil_quantity(residue):
    """Count complete 305 m sections in each own-stock lot, excluding partners.

    Invalid or incomplete supplier evidence raises before any sheet write.
    Cut pieces must never be combined into an imaginary complete coil.
    """
    if not isinstance(residue, dict) or str(residue.get("UOM_OKEI", "")).strip() != "006":
        raise ValueError("RS coil stock requires metre unit UOM_OKEI=006")

    def quantity(value):
        if isinstance(value, bool):
            raise ValueError("Invalid RS coil quantity")
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Invalid RS coil quantity") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("RS coil quantity must be finite and nonnegative")
        return parsed

    total = quantity(residue.get("Residue"))
    raw_lots = residue.get("qtyLots")
    # A validated zero own-stock balance cannot contain a sellable coil.
    if total == 0 and (raw_lots is None or (isinstance(raw_lots, str) and not raw_lots.strip())):
        return 0
    if not isinstance(raw_lots, str) or not raw_lots.strip():
        raise ValueError("RS coil stock requires explicit qtyLots")
    lots = [quantity(piece) for piece in raw_lots.split(";")]
    if abs(sum(lots, Decimal(0)) - total) > Decimal("0.000001"):
        raise ValueError("RS coil qtyLots do not match Residue")
    return sum(int(piece // Decimal(305)) for piece in lots)


class RSCoilQuantities(dict):
    """Validated coil counts plus models whose previous cells must be retained."""

    def __init__(self):
        super().__init__()
        self.invalid_models = set()


def fetch_rs_coil_quantities(models, code_map, warehouse_id, quarantine_invalid=False):
    """Fetch coil counts, optionally quarantining invalid models independently."""
    quantities = RSCoilQuantities()
    selected = sorted({str(model).strip().upper() for model in models} & RS_305M_COIL_MODELS)
    if not selected:
        return quantities
    http = create_rs_session()
    headers = get_rs_headers()
    try:
        for model in selected:
            try:
                code = code_map.get(model)
                if code in (None, ""):
                    raise ValueError("no verified RS code")
                url = f"{config.RS_BASE_URL}/residue/{warehouse_id}/{quote(str(code), safe='')}"
                for detail_attempt in range(2):
                    response = rs_get_with_retry(http, url, headers, label=f"RS coil residue {model}")
                    if response.status_code != 200:
                        raise ValueError(f"RS coil residue HTTP {response.status_code}")
                    try:
                        quantities[model] = parse_rs_coil_quantity(response.json())
                        break
                    except ValueError as exc:
                        if detail_attempt == 0 and "qtyLots do not match Residue" in str(exc):
                            time.sleep(2)
                            continue
                        raise
            except (ValueError, RuntimeError, requests.exceptions.RequestException) as exc:
                if not quarantine_invalid:
                    raise RuntimeError(f"Invalid RS coil residue for {model}; sheet was not updated: {exc}") from exc
                quantities.invalid_models.add(model)
                print(f"   Quarantined RS SMR coil {model}; previous cell is not fresh: {exc}")
            time.sleep(RS_API_MIN_PAGE_DELAY_SECONDS)
    finally:
        http.close()
    return quantities


class RSStockSnapshot(dict):
    """Valid stock rows plus RS codes whose product data must be left untouched."""

    def __init__(self):
        super().__init__()
        self.invalid_codes = set()
        self.invalid_products = 0


def get_active_interface_ip():
    preferred_interface = os.getenv("CHECKSHEETS_BYPASS_INTERFACE", "").strip()

    if preferred_interface:
        output = os.popen(f"ifconfig {preferred_interface}").read()
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if match:
            return preferred_interface, match.group(1)

    for interface in ("en1", "en0"):
        output = os.popen(f"ifconfig {interface}").read()
        if "status: active" not in output:
            continue
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", output)
        if match:
            return interface, match.group(1)

    raise RuntimeError(
        "No active LAN/Wi-Fi interface found for RS bypass. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


def create_rs_session():
    interface, source_ip = get_active_interface_ip()
    session = requests.Session()
    adapter = SourceAddressAdapter(source_ip, interface_name=interface)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    print(f"RS bypass interface: {interface} ({source_ip})")
    return session

def get_rs_headers():
    auth_str = f"{config.RS_LOGIN}:{config.RS_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
    return {
        "Authorization": f"Basic {encoded_auth}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }


def rs_get_with_retry(http, url, headers, timeout=30, label="RS API"):
    """Retry transient supplier API responses without accepting partial pages."""
    for attempt in range(1, RS_MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = http.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            if attempt == RS_MAX_REQUEST_ATTEMPTS:
                raise
            delay = 2 ** (attempt - 1)
            print(
                f"   Temporary {label} transport failure "
                f"({attempt}/{RS_MAX_REQUEST_ATTEMPTS - 1}); retrying in {delay}s: {exc}"
            )
            time.sleep(delay)
            continue

        if response.status_code in RS_RETRYABLE_HTTP_STATUSES and attempt < RS_MAX_REQUEST_ATTEMPTS:
            delay = 2 ** (attempt - 1)
            print(
                f"   Temporary {label} HTTP {response.status_code} "
                f"({attempt}/{RS_MAX_REQUEST_ATTEMPTS - 1}); retrying in {delay}s"
            )
            time.sleep(delay)
            continue
        return response

    raise RuntimeError(f"{label} request did not produce a response")


def fetch_rs_code_map(warehouse_id):
    """
    Получаем карту соответствий артикулов и RS-кодов
    """
    print(f"Fetching RS catalog for warehouse {warehouse_id}...")
    http = create_rs_session()
    headers = get_rs_headers()
    code_map = {}
    invalid_products = 0

    def fetch_category_snapshot(category, include_name=False):
        page = 1
        expected_pages = None
        expected_rows = None
        rows_read = 0
        category_code_map = {}
        category_invalid_products = 0
        while expected_pages is None or page <= expected_pages:
            url = f"{config.RS_BASE_URL}/position/{warehouse_id}/{category}?page={page}&rows=1000"
            response = rs_get_with_retry(
                http,
                url,
                headers,
                timeout=30,
                label=f"RS catalog warehouse {warehouse_id} page {page}",
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"RS catalog HTTP {response.status_code} at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                )
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise RuntimeError(
                    f"RS catalog returned an incomplete page at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                )
            meta = data.get("meta")
            if not isinstance(meta, dict):
                raise RuntimeError(
                    f"RS catalog omitted pagination metadata at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                )
            try:
                response_pages = int(meta["last_page"])
                response_rows = int(meta["rows_count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"RS catalog returned invalid pagination metadata at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                ) from exc
            if response_pages < 1 or response_rows < 0:
                raise RuntimeError(
                    f"RS catalog returned impossible pagination metadata at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                )
            if expected_pages is None:
                expected_pages = response_pages
                expected_rows = response_rows
                print(f"   Category {category}: ~{expected_rows} items, {expected_pages} pages")
            elif response_pages != expected_pages or response_rows != expected_rows:
                raise RuntimeError(
                    f"RS catalog pagination changed during read at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                )

            items = data["items"]
            if page < expected_pages and not items:
                raise RuntimeError(
                    f"RS catalog returned an empty intermediate page at warehouse {warehouse_id}, "
                    f"category {category}, page {page}"
                )
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict) or item.get("CODE") in (None, ""):
                    category_invalid_products += 1
                    if invalid_products + category_invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS catalog product "
                            f"at warehouse {warehouse_id}, category {category}, "
                            f"page {page}, row {item_index}: missing CODE"
                        )
                    continue
                vendor_code = str(item.get("VENDOR_CODE", "")).strip()
                article = str(item.get("ARTICLE", "")).strip()
                name = str(item.get("NAME", "")).strip()
                code = str(item["CODE"]).strip()
                if not vendor_code and not article and not (include_name and name):
                    category_invalid_products += 1
                    if invalid_products + category_invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS catalog product "
                            f"at warehouse {warehouse_id}, category {category}, "
                            f"page {page}, row {item_index}: no article or usable name"
                        )
                    continue

                if vendor_code:
                    category_code_map[vendor_code] = code
                    clean_vendor_code = ''.join(c for c in vendor_code if c.isalnum() or c in '-_').upper()
                    if clean_vendor_code != vendor_code.upper():
                        category_code_map[clean_vendor_code] = code
                if article and article != vendor_code:
                    category_code_map[article] = code
                    clean_article = ''.join(c for c in article if c.isalnum() or c in '-_').upper()
                    if clean_article != article.upper():
                        category_code_map[clean_article] = code
                if include_name and name:
                    clean_name = ''.join(c for c in name if c.isalnum() or c in '-_').upper()
                    if clean_name != name.upper():
                        category_code_map[clean_name] = code

            rows_read += len(items)
            page += 1
            time.sleep(RS_API_MIN_PAGE_DELAY_SECONDS)

        if rows_read != expected_rows:
            raise RuntimeError(
                f"RS catalog was incomplete at warehouse {warehouse_id}, category {category}: "
                f"read {rows_read} of {expected_rows} rows across {expected_pages} pages"
            )
        return category_code_map, category_invalid_products

    def fetch_category(category, include_name=False):
        nonlocal invalid_products
        for attempt in range(1, RS_CATALOG_SNAPSHOT_ATTEMPTS + 1):
            try:
                category_code_map, category_invalid_products = fetch_category_snapshot(
                    category,
                    include_name=include_name,
                )
                code_map.update(category_code_map)
                invalid_products += category_invalid_products
                if invalid_products:
                    print(f"   Quarantined incomplete RS catalog products so far: {invalid_products}")
                return
            except RuntimeError as exc:
                message = str(exc)
                snapshot_changed = any(marker in message for marker in (
                    "pagination changed during read",
                    "empty intermediate page",
                    "catalog was incomplete",
                ))
                if not snapshot_changed or attempt == RS_CATALOG_SNAPSHOT_ATTEMPTS:
                    raise
                delay = 2 ** (attempt - 1)
                print(
                    f"   RS catalog changed while reading {category}; "
                    f"restarting category ({attempt}/{RS_CATALOG_SNAPSHOT_ATTEMPTS - 1}) in {delay}s"
                )
                time.sleep(delay)

    try:
        fetch_category("instock", include_name=True)
        if len(code_map) < 1000:
            print("Main category has few items, also checking 'custom' category...")
            fetch_category("custom")
    except Exception as exc:
        print(f"   RS catalog load failed; no sheet update will be made: {exc}")
        raise

    if not code_map:
        raise RuntimeError(f"RS catalog returned no products for warehouse {warehouse_id}")
    print(f"Catalog loaded. Unique articles: {len(code_map)}")
    return code_map

def fetch_all_rs_stocks(warehouse_id):
    """
    Получаем все остатки по складу
    """
    print(f"Fetching all RS stocks for warehouse {warehouse_id}...")
    http = create_rs_session()
    headers = get_rs_headers()
    stock_data = RSStockSnapshot()
    page = 1
    last_page = None
    expected_records = None
    records_read = 0

    while last_page is None or page <= last_page:
        url = f"{config.RS_BASE_URL}/residue/all/{warehouse_id}?page={page}&rows=200&category=all"
        try:
            response = rs_get_with_retry(
                http,
                url,
                headers,
                timeout=30,
                label=f"RS residue warehouse {warehouse_id} page {page}",
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"RS residue HTTP {response.status_code} at warehouse {warehouse_id}, page {page}"
                )

            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("residues"), list):
                raise RuntimeError(
                    f"RS residue returned an incomplete page at warehouse {warehouse_id}, page {page}"
                )
            header_pages = response.headers.get("x-pagination-page-count")
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            try:
                response_pages = int(header_pages or meta["last_page"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"RS residue omitted pagination metadata at warehouse {warehouse_id}, page {page}"
                ) from exc
            raw_total = meta.get("rows_count")
            response_total = int(raw_total) if raw_total is not None else None
            if response_pages < 1 or (response_total is not None and response_total < 0):
                raise RuntimeError(
                    f"RS residue returned impossible pagination metadata at warehouse {warehouse_id}, page {page}"
                )
            if last_page is None:
                last_page = response_pages
                expected_records = response_total
            elif response_pages != last_page or (
                response_total is not None and expected_records is not None and response_total != expected_records
            ):
                raise RuntimeError(
                    f"RS residue pagination changed during read at warehouse {warehouse_id}, page {page}"
                )

            items = data["residues"]
            if page < last_page and not items:
                raise RuntimeError(
                    f"RS residue returned an empty intermediate page at warehouse {warehouse_id}, page {page}"
                )
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict) or item.get("CODE") in (None, ""):
                    stock_data.invalid_products += 1
                    if stock_data.invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS residue product "
                            f"at warehouse {warehouse_id}, page {page}, row {item_index}: missing CODE"
                        )
                    continue
                code = str(item["CODE"]).strip()
                if not code:
                    stock_data.invalid_products += 1
                    if stock_data.invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS residue product "
                            f"at warehouse {warehouse_id}, page {page}, row {item_index}: blank CODE"
                        )
                    continue
                if "RESIDUE" not in item:
                    stock_data.invalid_codes.add(code)
                    stock_data.invalid_products += 1
                    if stock_data.invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS residue product code {code} "
                            f"at warehouse {warehouse_id}, page {page}: missing RESIDUE"
                        )
                    continue
                try:
                    residue = float(item["RESIDUE"])
                except (TypeError, ValueError):
                    stock_data.invalid_codes.add(code)
                    stock_data.invalid_products += 1
                    if stock_data.invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS residue product code {code} "
                            f"at warehouse {warehouse_id}: non-numeric RESIDUE"
                        )
                    continue
                if residue < 0 or residue != residue or residue in (float("inf"), float("-inf")):
                    stock_data.invalid_codes.add(code)
                    stock_data.invalid_products += 1
                    if stock_data.invalid_products <= 10:
                        print(
                            f"   Skipping incomplete RS residue product code {code} "
                            f"at warehouse {warehouse_id}: invalid RESIDUE {residue}"
                        )
                    continue
                residue = int(residue) if residue.is_integer() else residue
                stock_data[code] = residue
            records_read += len(items)

            if page == 1:
                print(f"   Total stock pages: {last_page}")

            if page % 10 == 0:
                print(f"   Processed stock page {page}/{last_page}...")

            page += 1
            time.sleep(RS_API_MIN_PAGE_DELAY_SECONDS)
        except Exception as e:
            print(f"   RS stock load failed; no sheet update will be made: {e}")
            raise

    if expected_records is not None and records_read != expected_records:
        raise RuntimeError(
            f"RS residue was incomplete at warehouse {warehouse_id}: "
            f"read {records_read} of {expected_records} records across {last_page} pages"
        )

    print(
        f"Stock data loaded. Items with stock: {len(stock_data)}; "
        f"quarantined incomplete products: {stock_data.invalid_products}"
    )
    return stock_data

def fetch_rs_prices(rs_codes):
    """
    Получаем цены для списка RS-кодов батчами по 50
    """
    print(f"Fetching prices for {len(rs_codes)} RS codes...")
    http = create_rs_session()
    headers = get_rs_headers()
    
    prices = {}
    
    # Исключим дубликаты и пустые значения, отсортируем для стабильности
    unique_codes = sorted(list(set(str(c) for c in rs_codes if c)))
    total_batches = (len(unique_codes) - 1) // 50 + 1
    
    for i in range(0, len(unique_codes), 50):
        batch = unique_codes[i:i+50]
        url = f"{config.RS_BASE_URL}/massprice"
        batch_num = i // 50 + 1
        try:
            response = http.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json={"items": batch},
                timeout=30
            )
            if response.status_code != 200:
                print(f"   Error fetching prices (batch {batch_num}/{total_batches}): {response.status_code}")
                continue
                
            data = response.json()
            if isinstance(data, list):
                for item in data:
                    rs_code = item.get("RSCode")
                    price_info = item.get("Price", {})
                    # Согласно RS_API_PRICES.md берем Personal_w_VAT, если его нет - Personal.
                    personal_w_vat = price_info.get("Personal_w_VAT")
                    if personal_w_vat is None:
                        personal_w_vat = price_info.get("Personal")
                        
                    if rs_code and personal_w_vat is not None:
                        try:
                            prices[str(rs_code)] = float(personal_w_vat)
                        except (TypeError, ValueError):
                            pass
            
            if batch_num % 10 == 0 or batch_num == total_batches:
                print(f"   Processed price batch {batch_num}/{total_batches}...")
                
            time.sleep(0.15)
        except Exception as e:
            print(f"   Network error during price fetch: {e}")
            break
            
    print(f"Loaded prices for {len(prices)} RS codes.")
    return prices

def sync_rs():
    """
    Основная функция синхронизации
    """
    print("Starting RS Local Sync (StreamSupps raw stock)...")

    try:
        ws = gsheets_utils.get_worksheet(config.RS_SHEET_NAME)
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return

    # Найдем колонки
    try:
        columns = gsheets_utils.get_header_columns(
            ws,
            {
                "model": "Артикул производителя",
                "stock_api": "RS SMR",
                "stock_msk": "RS MSK",
            },
            config.RS_SHEET_NAME,
        )
    except ValueError as e:
        print(f"Sheet schema error: {e}")
        return

    models = ws.col_values(columns["model"])[1:]  # Пропускаем заголовок
    print(f"Found {len(models)} models in header 'Артикул производителя'")

    # Покажем несколько первых моделей для понимания формата
    print(f"First 10 models: {models[:10]}")

    # Получаем карту кодов и остатки
    code_map = fetch_rs_code_map(config.RS_WAREHOUSE_ID)
    all_stocks = fetch_all_rs_stocks(config.RS_WAREHOUSE_ID)
    msk_code_map = fetch_rs_code_map(config.RS_MSK_WAREHOUSE_ID)
    msk_stocks = fetch_all_rs_stocks(config.RS_MSK_WAREHOUSE_ID)

    if not code_map or not all_stocks or not msk_code_map or not msk_stocks:
        raise RuntimeError("RS API returned an empty catalog or stock response; sheet was not updated")

    coil_quantities = fetch_rs_coil_quantities(
        models, code_map, config.RS_WAREHOUSE_ID, quarantine_invalid=True
    )
    invalid_coil_models = getattr(coil_quantities, "invalid_models", set())

    # Подготовим результаты
    results_stock = []
    results_msk_stock = []
    write_stock_mask = []
    write_msk_mask = []

    # Счетчики для отладки
    total_processed = 0
    found_with_stock = 0
    found_zero_stock = 0
    missing_stock_smr = 0
    missing_stock_msk = 0
    not_found = 0
    skipped_invalid_smr = 0
    skipped_invalid_msk = 0

    for i, model in enumerate(models):
        model = str(model).strip()

        if not model:
            results_stock.append([""])
            results_msk_stock.append([""])
            write_stock_mask.append(False)
            write_msk_mask.append(False)
            continue

        stock = 0
        price = ""
        rs_code = None

        # Множественные попытки найти соответствие
        search_variants = [
            model,
            model.upper(),
            model.lower(),
            model.strip().upper(),
            ''.join(c for c in model if c.isalnum() or c in '-_').upper(),
            ''.join(c for c in model if c.isalnum()).upper(),
        ]

        for variant in search_variants:
            if variant in code_map:
                rs_code = code_map[variant]
                break

        msk_code = next((msk_code_map[variant] for variant in search_variants if variant in msk_code_map), None)
        if msk_code is not None and str(msk_code) in msk_stocks.invalid_codes:
            results_msk_stock.append([""])
            write_msk_mask.append(False)
            if msk_code is not None:
                skipped_invalid_msk += 1
        else:
            # Missing products/residue rows have zero stock in the sheet.
            results_msk_stock.append([msk_stocks.get(msk_code, 0)])
            write_msk_mask.append(True)
            if msk_code not in msk_stocks:
                missing_stock_msk += 1

        if (model.upper() not in invalid_coil_models
                and rs_code is not None and str(rs_code) not in all_stocks.invalid_codes):
            stock = coil_quantities.get(model.upper(), all_stocks.get(rs_code, 0))

            if model in ['61950', '71650']:
                print(f"DEBUG: Model '{model}' found RS code '{rs_code}', stock: {stock}")

            if rs_code not in all_stocks:
                missing_stock_smr += 1
            if stock > 0:
                found_with_stock += 1
            else:
                found_zero_stock += 1
        elif rs_code is None:
            not_found += 1

            if model in ['61950', '71650']:
                print(f"DEBUG: Model '{model}' not found in code_map. Looking for partial matches...")
                similar_keys = [k for k in code_map.keys() if model in k or k.startswith(model)]
                if similar_keys:
                    print(f"DEBUG: Found similar keys: {similar_keys[:5]}")
                    first_similar = similar_keys[0]
                    rs_code = code_map[first_similar]
                    stock = all_stocks.get(rs_code, 0)
                    if rs_code not in all_stocks:
                        missing_stock_smr += 1
                    print(f"DEBUG: Using similar key '{first_similar}' -> RS code '{rs_code}', stock: {stock}")

        rs_stock_valid = (model.upper() not in invalid_coil_models
                          and (rs_code is None or str(rs_code) not in all_stocks.invalid_codes))
        if not rs_stock_valid:
            skipped_invalid_smr += 1

        results_stock.append([stock if rs_stock_valid else ""])
        write_stock_mask.append(rs_stock_valid)
        total_processed += 1

    print(f"\nSync Statistics:")
    print(f"  - Total processed: {total_processed}")
    print(f"  - Found with stock > 0: {found_with_stock}")
    print(f"  - Found with zero stock: {found_zero_stock}")
    print(f"  - Missing stock entries written as zero: Samara={missing_stock_smr + not_found}, Moscow={missing_stock_msk}")
    print(f"  - Not found: {not_found}")
    print(f"  - Skipped incomplete stock rows: Samara={skipped_invalid_smr}, Moscow={skipped_invalid_msk}")

    if total_processed > 0 and found_with_stock == 0:
        err = f"Аномалия RS: обработано {total_processed} артикулов, но найдено 0 товаров с остатком > 0!"
        print(f"ERROR: {err}")
        send_telegram_alert("rs_sync (Аномалия остатков)", err)
        raise RuntimeError(err)

    print(f"Updating Google Sheet '{config.RS_SHEET_NAME}'...")

    update_errors = []

    # RS SMR stores own stock, converted to complete 305 m coils only for the
    # five explicit RS_305M_COIL_MODELS; RS MSK remains in source units.
    # Производные колонки StreamSupps «РЕЗЕРВ» и
    # маркетплейсные трансляции заполняются отдельным контуром.
    try:
        written_smr = gsheets_utils.update_column_by_header_masked(
            ws, "RS SMR", results_stock, write_stock_mask
        )
        written_msk = gsheets_utils.update_column_by_header_masked(
            ws, "RS MSK", results_msk_stock, write_msk_mask
        )
        print(f"RS SMR and RS MSK updated successfully! written={written_smr}/{written_msk}")
    except Exception as e:
        update_errors.append(f"stock column: {e}")
        print(f"Error updating stock column after retries: {e}")

    if update_errors:
        err_text = "Google Sheet update failed: " + "; ".join(update_errors)
        send_telegram_alert("rs_sync (Google Sheets)", err_text)
        raise RuntimeError(err_text)

    print("RS Sync completed successfully!")
    # The CLI publishes this receipt only after both source columns succeeded.
    # Masked invalid rows may retain an old numeric value and are not fresh.
    return {
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "warehouse": config.RS_WAREHOUSE_ID,
        "quarantinedModels": sorted({str(model).strip().upper()
            for model, writable in zip(models, write_stock_mask)
            if str(model).strip() and not writable}),
        "writtenSamara": written_smr,
        "writtenMoscow": written_msk,
    }


def write_rs_source_report(report):
    if not isinstance(report, dict):
        raise RuntimeError("RS source did not finish with a write receipt")
    target = Path(__file__).resolve().parent / "logs" / "rs-source-last.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)

if __name__ == "__main__":
    try:
        write_rs_source_report(sync_rs())
    except Exception as exc:
        print(f"CRITICAL ERROR: {exc}")
        try:
            send_telegram_alert("rs_sync", exc)
        except Exception:
            pass
        raise SystemExit(1)
