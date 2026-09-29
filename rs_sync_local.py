import requests
import base64
import time
import os
import re
import config
import gsheets_utils
from network_bypass import SourceAddressAdapter
from telegram_notifier import send_telegram_alert


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

def fetch_rs_code_map(warehouse_id):
    """
    Получаем карту соответствий артикулов и RS-кодов
    """
    print(f"Fetching RS catalog for warehouse {warehouse_id}...")
    http = create_rs_session()
    headers = get_rs_headers()
    code_map = {}

    def fetch_category(category, include_name=False):
        page = 1
        expected_pages = None
        expected_rows = None
        rows_read = 0
        while expected_pages is None or page <= expected_pages:
            url = f"{config.RS_BASE_URL}/position/{warehouse_id}/{category}?page={page}&rows=1000"
            response = http.get(url, headers=headers, timeout=30)
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
            for item in items:
                if not isinstance(item, dict) or not item.get("CODE"):
                    raise RuntimeError(
                        f"RS catalog contains an incomplete product at warehouse {warehouse_id}, "
                        f"category {category}, page {page}"
                    )
                vendor_code = str(item.get("VENDOR_CODE", "")).strip()
                article = str(item.get("ARTICLE", "")).strip()
                name = str(item.get("NAME", "")).strip()
                code = item["CODE"]

                if vendor_code:
                    code_map[vendor_code] = code
                    clean_vendor_code = ''.join(c for c in vendor_code if c.isalnum() or c in '-_').upper()
                    if clean_vendor_code != vendor_code.upper():
                        code_map[clean_vendor_code] = code
                if article and article != vendor_code:
                    code_map[article] = code
                    clean_article = ''.join(c for c in article if c.isalnum() or c in '-_').upper()
                    if clean_article != article.upper():
                        code_map[clean_article] = code
                if include_name and name:
                    clean_name = ''.join(c for c in name if c.isalnum() or c in '-_').upper()
                    if clean_name != name.upper():
                        code_map[clean_name] = code

            rows_read += len(items)
            page += 1
            time.sleep(0.1)

        if rows_read != expected_rows:
            raise RuntimeError(
                f"RS catalog was incomplete at warehouse {warehouse_id}, category {category}: "
                f"read {rows_read} of {expected_rows} rows across {expected_pages} pages"
            )

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
    stock_data = {}
    page = 1
    last_page = None
    expected_records = None
    records_read = 0

    while last_page is None or page <= last_page:
        url = f"{config.RS_BASE_URL}/residue/all/{warehouse_id}?page={page}&rows=200&category=all"
        try:
            response = http.get(url, headers=headers, timeout=30)
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
            for item in items:
                if not isinstance(item, dict) or not item.get("CODE") or "RESIDUE" not in item:
                    raise RuntimeError(
                        f"RS residue contains an incomplete product at warehouse {warehouse_id}, page {page}"
                    )
                code = item["CODE"]
                try:
                    residue = float(item["RESIDUE"])
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"RS residue is non-numeric for code {code} at warehouse {warehouse_id}"
                    ) from exc
                if residue < 0 or residue != residue or residue in (float("inf"), float("-inf")):
                    raise RuntimeError(
                        f"RS residue is invalid for code {code} at warehouse {warehouse_id}: {residue}"
                    )
                residue = int(residue) if residue.is_integer() else residue
                stock_data[code] = residue
            records_read += len(items)

            if page == 1:
                print(f"   Total stock pages: {last_page}")

            if page % 10 == 0:
                print(f"   Processed stock page {page}/{last_page}...")

            page += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"   RS stock load failed; no sheet update will be made: {e}")
            raise

    if expected_records is not None and records_read != expected_records:
        raise RuntimeError(
            f"RS residue was incomplete at warehouse {warehouse_id}: "
            f"read {records_read} of {expected_records} records across {last_page} pages"
        )

    print(f"Stock data loaded. Items with stock: {len(stock_data)}")
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

    # Подготовим результаты
    results_stock = []
    results_msk_stock = []
    write_stock_mask = []
    write_msk_mask = []

    # Счетчики для отладки
    total_processed = 0
    found_with_stock = 0
    found_zero_stock = 0
    not_found = 0

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
        if msk_code is None:
            results_msk_stock.append([""])
            write_msk_mask.append(False)
        else:
            results_msk_stock.append([msk_stocks.get(msk_code, 0)])
            write_msk_mask.append(True)

        if rs_code:
            stock = all_stocks.get(rs_code, 0)

            if model in ['61950', '71650']:
                print(f"DEBUG: Model '{model}' found RS code '{rs_code}', stock: {stock}")

            if stock > 0:
                found_with_stock += 1
            else:
                found_zero_stock += 1
        else:
            not_found += 1

            if model in ['61950', '71650']:
                print(f"DEBUG: Model '{model}' not found in code_map. Looking for partial matches...")
                similar_keys = [k for k in code_map.keys() if model in k or k.startswith(model)]
                if similar_keys:
                    print(f"DEBUG: Found similar keys: {similar_keys[:5]}")
                    first_similar = similar_keys[0]
                    rs_code = code_map[first_similar]
                    stock = all_stocks.get(rs_code, 0)
                    print(f"DEBUG: Using similar key '{first_similar}' -> RS code '{rs_code}', stock: {stock}")

        results_stock.append([stock if rs_code is not None else ""])
        write_stock_mask.append(rs_code is not None)
        total_processed += 1

    print(f"\nSync Statistics:")
    print(f"  - Total processed: {total_processed}")
    print(f"  - Found with stock > 0: {found_with_stock}")
    print(f"  - Found with zero stock: {found_zero_stock}")
    print(f"  - Not found: {not_found}")

    if total_processed > 0 and found_with_stock == 0:
        err = f"Аномалия RS: обработано {total_processed} артикулов, но найдено 0 товаров с остатком > 0!"
        print(f"ERROR: {err}")
        send_telegram_alert("rs_sync (Аномалия остатков)", err)
        raise RuntimeError(err)

    print(f"Updating Google Sheet '{config.RS_SHEET_NAME}'...")

    update_errors = []

    # Обновляем сырой остаток RS. Производные колонки StreamSupps «РЕЗЕРВ» и
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

if __name__ == "__main__":
    try:
        sync_rs()
    except Exception as exc:
        print(f"CRITICAL ERROR: {exc}")
        try:
            send_telegram_alert("rs_sync", exc)
        except Exception:
            pass
        raise SystemExit(1)
