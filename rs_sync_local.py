import requests
import base64
import time
import os
import re
import config
import gsheets_utils
from network_bypass import SourceAddressAdapter


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
    categories = ["instock"]  # Сначала проверяем только в наличии

    for cat in categories:
        page = 1
        last_page = 1
        while page <= last_page:
            url = f"{config.RS_BASE_URL}/position/{warehouse_id}/{cat}?page={page}&rows=1000"
            try:
                response = http.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    print(f"   Error fetching page {page} of {cat}: {response.status_code}")
                    break

                data = response.json()
                items = data.get("items", [])

                for item in items:
                    # Проверяем несколько возможных полей для артикула
                    vendor_code = str(item.get("VENDOR_CODE", "")).strip()
                    article = str(item.get("ARTICLE", "")).strip()
                    name = str(item.get("NAME", "")).strip()
                    code = item.get("CODE")

                    # Сохраняем все возможные значения артикулов
                    if vendor_code:
                        code_map[vendor_code] = code
                        # Также добавляем без пробелов и специальных символов
                        clean_vendor_code = ''.join(c for c in vendor_code if c.isalnum() or c in '-_').upper()
                        if clean_vendor_code != vendor_code.upper():
                            code_map[clean_vendor_code] = code

                    if article and article != vendor_code:
                        code_map[article] = code
                        clean_article = ''.join(c for c in article if c.isalnum() or c in '-_').upper()
                        if clean_article != article.upper():
                            code_map[clean_article] = code

                    # Иногда имя товара может содержать артикул
                    if name:
                        clean_name = ''.join(c for c in name if c.isalnum() or c in '-_').upper()
                        if clean_name != name.upper():
                            code_map[clean_name] = code

                last_page = data.get("meta", {}).get("last_page", 1)
                if page == 1:
                    print(f"   Category {cat}: ~{data.get('meta', {}).get('rows_count')} items, {last_page} pages")

                page += 1
                time.sleep(0.1)
            except Exception as e:
                print(f"   Network error: {e}")
                break

    # Если основная категория пуста или мало данных, пробуем custom
    if len(code_map) < 1000:
        print("Main category has few items, also checking 'custom' category...")
        for cat in ["custom"]:
            page = 1
            last_page = 1
            while page <= last_page:
                url = f"{config.RS_BASE_URL}/position/{warehouse_id}/{cat}?page={page}&rows=1000"
                try:
                    response = http.get(url, headers=headers, timeout=30)
                    if response.status_code != 200:
                        print(f"   Error fetching page {page} of {cat}: {response.status_code}")
                        break

                    data = response.json()
                    items = data.get("items", [])

                    for item in items:
                        vendor_code = str(item.get("VENDOR_CODE", "")).strip()
                        article = str(item.get("ARTICLE", "")).strip()
                        code = item.get("CODE")

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

                    last_page = data.get("meta", {}).get("last_page", 1)
                    if page == 1:
                        print(f"   Category {cat}: ~{data.get('meta', {}).get('rows_count')} items, {last_page} pages")

                    page += 1
                    time.sleep(0.1)
                except Exception as e:
                    print(f"   Network error in {cat}: {e}")
                    break

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
    last_page = 1

    while page <= last_page:
        url = f"{config.RS_BASE_URL}/residue/all/{warehouse_id}?page={page}&rows=200&category=all"
        try:
            response = http.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"   Error fetching stocks page {page}: {response.status_code}")
                break

            # Получаем последнюю страницу из заголовков или метаданных
            if 'x-pagination-page-count' in response.headers:
                last_page = int(response.headers['x-pagination-page-count'])
            else:
                data = response.json()
                last_page = data.get("meta", {}).get("last_page", 1)

            data = response.json()
            items = data.get("residues", [])
            for item in items:
                code = item.get("CODE")
                if code:
                    # Убедимся, что остаток корректно обрабатывается как число
                    residue = item.get("RESIDUE", 0)
                    try:
                        residue = float(residue) if residue is not None else 0
                        residue = int(residue) if residue == int(residue) else residue
                    except (TypeError, ValueError):
                        residue = 0
                    stock_data[code] = residue

            if page == 1:
                print(f"   Total stock pages: {last_page}")

            if page % 10 == 0:
                print(f"   Processed stock page {page}/{last_page}...")

            page += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"   Network error during stock fetch: {e}")
            break

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
            },
            config.RS_SHEET_NAME,
        )
    except ValueError as e:
        print(f"Sheet schema error: {e}")
        return

    models = ws.col_values(columns["model"])[1:]  # Пропускаем заголовок
    print(f"Found {len(models)} models in header 'Модель'")

    # Покажем несколько первых моделей для понимания формата
    print(f"First 10 models: {models[:10]}")

    # Получаем карту кодов и остатки
    code_map = fetch_rs_code_map(config.RS_WAREHOUSE_ID)
    all_stocks = fetch_all_rs_stocks(config.RS_WAREHOUSE_ID)

    # Подготовим результаты
    results_stock = []

    # Счетчики для отладки
    total_processed = 0
    found_with_stock = 0
    found_zero_stock = 0
    not_found = 0

    for i, model in enumerate(models):
        model = str(model).strip()

        if not model:
            results_stock.append([0])
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

        results_stock.append([stock])
        total_processed += 1

    print(f"\nSync Statistics:")
    print(f"  - Total processed: {total_processed}")
    print(f"  - Found with stock > 0: {found_with_stock}")
    print(f"  - Found with zero stock: {found_zero_stock}")
    print(f"  - Not found: {not_found}")

    print(f"Updating Google Sheet '{config.RS_SHEET_NAME}'...")

    update_errors = []

    # Обновляем сырой остаток RS. Производные колонки StreamSupps!V и
    # маркетплейсные трансляции заполняются отдельным контуром.
    try:
        gsheets_utils.clear_column_at_index(ws, columns["stock_api"])
        gsheets_utils.update_column(ws, columns["stock_api"], results_stock)
        print("Stock API updated successfully!")
    except Exception as e:
        update_errors.append(f"stock column: {e}")
        print(f"Error updating stock column after retries: {e}")

    if update_errors:
        raise RuntimeError("Google Sheet update failed: " + "; ".join(update_errors))

    print("RS Sync completed successfully!")

if __name__ == "__main__":
    sync_rs()
