import time
import requests
import os
import re
import config
import gsheets_utils
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager


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
        "No active LAN/Wi-Fi interface found for Feron bypass. "
        "Set CHECKSHEETS_BYPASS_INTERFACE explicitly."
    )


def create_feron_session():
    interface, source_ip = get_active_interface_ip()
    session = requests.Session()
    adapter = SourceAddressAdapter(source_ip)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    print(f"Feron bypass interface: {interface} ({source_ip})")
    return session


def feron_post_with_retry(http, url, headers, payload, timeout, label, attempts=4):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = http.post(url, json=payload, headers=headers, timeout=timeout)
            if response.status_code == 429:
                wait_seconds = min(10 * attempt, 30)
                print(f"{label}: rate limit hit, retry {attempt}/{attempts} in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            return response
        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt == attempts:
                break
            wait_seconds = min(5 * attempt, 20)
            print(f"{label}: timeout, retry {attempt}/{attempts} in {wait_seconds}s...")
            time.sleep(wait_seconds)
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt == attempts:
                break
            wait_seconds = min(3 * attempt, 15)
            print(f"{label}: network error, retry {attempt}/{attempts} in {wait_seconds}s...")
            time.sleep(wait_seconds)

    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}")

def get_feron_session():
    """
    Returns the Feron API key from config.
    """
    return getattr(config, 'FERON_API_KEY', None)

def parse_feron_quantity(qty_data):
    """Parse Feron quantity payload.

    Feron `/quantities/search` may return `value.quantity = 0` while the
    currently visible stock is present in `value.text` (for example text `9`).
    Prefer numeric `text` when available; fall back to `quantity` otherwise.
    """
    if not isinstance(qty_data, dict):
        return 0

    raw_text = str(qty_data.get("text") or "").replace("\xa0", " ").strip()
    match = re.search(r"-?\d+(?:[,.]\d+)?", raw_text)
    if match:
        try:
            return max(0, int(float(match.group(0).replace(",", "."))))
        except (ValueError, TypeError):
            pass

    try:
        return max(0, int(float(qty_data.get("quantity", 0) or 0)))
    except (ValueError, TypeError):
        return 0


def fetch_all_feron_data(api_key):
    """
    Fetches all products and their quantities from Feron API in bulk.
    Returns: dict mapping vendor_code to warehouse stocks {vendor_code: {warehouse_id: qty}}
    Logic based on 1C module 'Модуль_Ферон_полный_код.txt' (lea addition 23.10.2025).
    """
    base_url = getattr(config, 'FERON_BASE_URL', "https://api.feron.ru")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": api_key,
    }
    http = create_feron_session()

    products_map = {} # product_id -> lookup keys from Feron catalog
    search_token = ""
    
    print("--- Fetching all products from Feron catalog ---")
    
    # Step 1: Search all products to get product_id -> lookup key mapping.
    # The sheet is keyed by model in column B, while Feron can expose both
    # vendor_code and model. Keep both aliases so rows like 52125-1 / 52125
    # resolve to the same stock record.
    # Using larger size (3000) as in 1C module for efficiency
    for i in range(100): # Safety limit for iterations to avoid infinite loops
        url = f"{base_url}/offers/products/search"
        if search_token:
            payload = {"search_token": search_token}
        else:
            payload = {"size": 3000}
            
        try:
            response = feron_post_with_retry(
                http=http,
                url=url,
                headers=headers,
                payload=payload,
                timeout=30,
                label="Product search",
            )

            if response.status_code != 200:
                print(f"Error fetching products: {response.status_code} {response.text}")
                break
                
            data = response.json()
            items = data.get("items", [])
            for item in items:
                p_id = item.get("product_id")
                v_code = item.get("vendor_code")
                model = item.get("model")
                lookup_keys = {
                    str(v_code).strip() for v_code in (v_code, model) if v_code
                }
                if p_id and lookup_keys:
                    products_map[p_id] = lookup_keys
            
            new_token = data.get("search_token")
            if not new_token or new_token == search_token:
                break
            search_token = new_token
            
            if len(items) == 0:
                break
                
        except Exception as e:
            print(f"Exception during product search: {e}")
            break
            
    print(f"Found {len(products_map)} unique products in Feron catalog.")
    if not products_map:
        raise RuntimeError(
            "Feron catalog returned 0 products. Aborting sync to avoid overwriting Google Sheets with zeros."
        )

    # Step 2: Get quantities for all product IDs
    all_stocks = {} # lookup key -> {warehouse_id: qty}
    all_warehouse_ids = set()  # Collect all unique warehouse IDs from API
    product_ids = list(products_map.keys())
    
    print("\n--- Fetching quantities for all products in bulk ---")
    # We chunk the product IDs to avoid extremely large request bodies
    chunk_size = 500  
    for i in range(0, len(product_ids), chunk_size):
        chunk = product_ids[i:i + chunk_size]
        url = f"{base_url}/quantities/search"
        payload = {"products_id": chunk}
        
        try:
            response = feron_post_with_retry(
                http=http,
                url=url,
                headers=headers,
                payload=payload,
                timeout=60,
                label=f"Quantity fetch chunk {i // chunk_size + 1}",
            )
            
            if response.status_code != 200:
                print(f"Error fetching quantities: {response.status_code}")
                continue
                
            data = response.json()
            items = data.get("items", [])
            for item in items:
                p_id = item.get("product_id")
                w_id = item.get("warehouse_id")
                qty_data = item.get("value", {})
                qty = parse_feron_quantity(qty_data)
                
                # Collect all unique warehouse IDs
                if w_id:
                    all_warehouse_ids.add(w_id)
                
                lookup_keys = products_map.get(p_id)
                if lookup_keys:
                    try:
                        val = int(float(qty))
                    except (ValueError, TypeError):
                        val = 0

                    for lookup_key in lookup_keys:
                        if lookup_key not in all_stocks:
                            all_stocks[lookup_key] = {}
                        # Sum duplicate matches when multiple Feron items share
                        # the same model key in the sheet.
                        all_stocks[lookup_key][w_id] = (
                            all_stocks[lookup_key].get(w_id, 0) + val
                        )
            
            print(f"  Progress: {min(i + chunk_size, len(product_ids))}/{len(product_ids)} articles processed")
            
        except Exception as e:
            print(f"Exception during quantity fetch at index {i}: {e}")
            
    print(f"\n--- All warehouses found in API: {sorted(all_warehouse_ids)} ---")
    if not all_warehouse_ids:
        raise RuntimeError(
            "Feron quantities API returned 0 warehouses. Aborting sync to avoid overwriting Google Sheets with zeros."
        )
    
    return all_stocks

def update_feron_stock_columns(ws, sheet_label, key_column, warehouse_ids, sheet_columns, all_feron_stocks):
    """Update Feron stock columns in a Google Sheet by lookup key column."""
    try:
        vendor_codes_raw = ws.col_values(key_column)[1:]  # Skip row 1 (header)
        print(f"Successfully loaded {len(vendor_codes_raw)} articles from column {key_column} in '{sheet_label}'")
    except Exception as e:
        print(f"ERROR: Could not read articles from Sheet '{sheet_label}': {e}")
        return

    for wh_name, wh_id in warehouse_ids.items():
        col_num = sheet_columns.get(wh_name)
        if not col_num:
            continue

        print(f"\nProcessing sheet '{sheet_label}' warehouse: {wh_name} (ID: {wh_id})")

        formatted_results = []
        stats = {"matched": 0, "not_found": 0, "non_zero": 0}

        for code in vendor_codes_raw:
            code_str = str(code).strip()
            if not code_str:
                formatted_results.append([0])
                continue

            stocks_for_code = all_feron_stocks.get(code_str)
            if stocks_for_code is not None:
                stats["matched"] += 1
                qty = stocks_for_code.get(wh_id, 0)
                formatted_results.append([qty])
                if qty > 0:
                    stats["non_zero"] += 1
            else:
                stats["not_found"] += 1
                formatted_results.append([0])

        print(f"  - Match Rate: {stats['matched']}/{len(vendor_codes_raw)} articles found in API")
        print(f"  - Inventory: {stats['non_zero']} articles have stock > 0")

        try:
            print(f"  - Updating Google Sheet '{sheet_label}' column {col_num} ({wh_name})...")
            gsheets_utils.clear_column(ws, col_num)
            gsheets_utils.update_column(ws, col_num, formatted_results)
            print(f"  - OK: Sheet '{sheet_label}' warehouse {wh_name} updated successfully.")
        except Exception as e:
            print(f"  - ERROR: Failed to update '{sheet_label}' {wh_name}: {e}")


def sync_feron():
    """
    Main entry point for Feron stock synchronization.
    This function implements a robust bulk-sync logic to avoid 'zeros' issue
    and excessive API calls.
    """
    print("=" * 60)
    print("STARTING FERON STOCK SYNCHRONIZATION (BULK MODE)")
    print("=" * 60)
    
    api_key = get_feron_session()
    if not api_key:
        print("ERROR: Feron API key not found in config.py. Please check FERON_API_KEY.")
        return

    # Phase 1: Fetch ALL data from Feron API
    # This is much faster than per-article lookups and bypasses the 100-item limit
    try:
        all_feron_stocks = fetch_all_feron_data(api_key)
    except Exception as e:
        print(f"ERROR: Could not fetch Feron bulk data safely: {e}")
        return
    
    # Warehouse ID mapping (confirmed via diagnostics)
    warehouse_ids = {
        "Самара": "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7",
        "Внуково": "de099cee-372a-11ef-96b6-a4bf0186f0c7",
        "Новосибирск": "ab50cafe-6e27-11ef-96b6-a4bf0186f0c7",
    }

    main_sheet_name = getattr(config, 'FERON_SHEET_NAME', None)
    if main_sheet_name:
        try:
            print(f"\nAccessing Google Sheet: '{main_sheet_name}'...")
            main_ws = gsheets_utils.get_worksheet(main_sheet_name)
            update_feron_stock_columns(
                ws=main_ws,
                sheet_label=main_sheet_name,
                key_column=2,  # B - МОДЕЛЬ
                warehouse_ids=warehouse_ids,
                sheet_columns={
                    "Самара": 35,       # AI - Ферон Самара
                    "Внуково": 36,      # AJ - Ферон Внуково
                    "Новосибирск": 37,  # AK - Ферон Новосибирск
                },
                all_feron_stocks=all_feron_stocks,
            )
        except Exception as e:
            print(f"ERROR: Could not update main Feron sheet '{main_sheet_name}': {e}")
    
    # Column mapping in Google Sheet (J=10, K=11, L=12)
    sheet_columns = {
        "Самара": 10,   # Column J - stocks smr
        "Внуково": 11,  # Column K - stocks msk
        "Новосибирск": 12, # Column L - stocks nsb
    }

    # Phase 2: Update Google Sheet
    try:
        sheet_name = getattr(config, 'FERON_SHEET_NAME_FBS', 'FERON TR')
        print(f"\nAccessing Google Sheet: '{sheet_name}'...")
        ws = gsheets_utils.get_worksheet(sheet_name)
    except Exception as e:
        print(f"ERROR: Could not access Google Sheet: {e}")
        return

    # Get vendor codes from column B (Models/Articles)
    try:
        # col_values(2) gets all non-empty values in column B
        vendor_codes_raw = ws.col_values(2)[1:] # Skip row 1 (header)
        print(f"Successfully loaded {len(vendor_codes_raw)} articles from column B")
    except Exception as e:
        print(f"ERROR: Could not read articles from Sheet: {e}")
        return

    # Phase 3: Match and Upload for each warehouse
    for wh_name, wh_id in warehouse_ids.items():
        col_num = sheet_columns.get(wh_name)
        if not col_num:
            continue
            
        print(f"\nProcessing warehouse: {wh_name} (ID: {wh_id})")
        
        formatted_results = []
        stats = {"matched": 0, "not_found": 0, "non_zero": 0}
        
        for code in vendor_codes_raw:
            code_str = str(code).strip()
            if not code_str:
                formatted_results.append([0])
                continue
                
            stocks_for_code = all_feron_stocks.get(code_str)
            if stocks_for_code is not None:
                stats["matched"] += 1
                qty = stocks_for_code.get(wh_id, 0)
                formatted_results.append([qty])
                if qty > 0:
                    stats["non_zero"] += 1
            else:
                stats["not_found"] += 1
                formatted_results.append([0])
        
        print(f"  - Match Rate: {stats['matched']}/{len(vendor_codes_raw)} articles found in API")
        print(f"  - Inventory: {stats['non_zero']} articles have stock > 0")
        
        try:
            print(f"  - Updating Google Sheet column {col_num} ({wh_name})...")
            gsheets_utils.clear_column(ws, col_num)
            gsheets_utils.update_column(ws, col_num, formatted_results)
            print(f"  - OK: Warehouse {wh_name} updated successfully.")
        except Exception as e:
            print(f"  - ERROR: Failed to update {wh_name}: {e}")

    print("\n" + "=" * 60)
    print("FERON STOCK SYNCHRONIZATION COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    sync_feron()
