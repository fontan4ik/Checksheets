import time
import requests
import config
import gsheets_utils

def get_feron_session():
    """
    Returns the Feron API key from config.
    """
    return getattr(config, 'FERON_API_KEY', None)

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

    products_map = {} # product_id -> vendor_code
    search_token = ""
    
    print("--- Fetching all products from Feron catalog ---")
    
    # Step 1: Search all products to get product_id -> vendor_code mapping
    # Using larger size (3000) as in 1C module for efficiency
    for i in range(100): # Safety limit for iterations to avoid infinite loops
        url = f"{base_url}/offers/products/search"
        if search_token:
            payload = {"search_token": search_token}
        else:
            payload = {"size": 3000}
            
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 429:
                print("Rate limit hit during search, waiting 10s...")
                time.sleep(10)
                response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code != 200:
                print(f"Error fetching products: {response.status_code} {response.text}")
                break
                
            data = response.json()
            items = data.get("items", [])
            for item in items:
                p_id = item.get("product_id")
                v_code = item.get("vendor_code")
                if p_id and v_code:
                    # Strip and normalize vendor_code for reliable matching
                    products_map[p_id] = str(v_code).strip()
            
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

    # Step 2: Get quantities for all product IDs
    all_stocks = {} # vendor_code -> {warehouse_id: qty}
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
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code == 429:
                print(f"Rate limit hit during quantity fetch (index {i}), waiting 10s...")
                time.sleep(10)
                response = requests.post(url, json=payload, headers=headers, timeout=60)
            
            if response.status_code != 200:
                print(f"Error fetching quantities: {response.status_code}")
                continue
                
            data = response.json()
            items = data.get("items", [])
            for item in items:
                p_id = item.get("product_id")
                w_id = item.get("warehouse_id")
                qty_data = item.get("value", {})
                qty = qty_data.get("quantity", 0)
                
                # Collect all unique warehouse IDs
                if w_id:
                    all_warehouse_ids.add(w_id)
                
                v_code = products_map.get(p_id)
                if v_code:
                    if v_code not in all_stocks:
                        all_stocks[v_code] = {}
                    try:
                        # Ensure we store as integer
                        val = int(float(qty))
                        all_stocks[v_code][w_id] = val
                    except (ValueError, TypeError):
                        all_stocks[v_code][w_id] = 0
            
            print(f"  Progress: {min(i + chunk_size, len(product_ids))}/{len(product_ids)} articles processed")
            
        except Exception as e:
            print(f"Exception during quantity fetch at index {i}: {e}")
            
    print(f"\n--- All warehouses found in API: {sorted(all_warehouse_ids)} ---")
    
    return all_stocks

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
    all_feron_stocks = fetch_all_feron_data(api_key)
    
    # Warehouse ID mapping (confirmed via diagnostics)
    warehouse_ids = {
        "Самара": "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7",
        "Внуково": "de099cee-372a-11ef-96b6-a4bf0186f0c7",
        "Новосибирск": "ab50cafe-6e27-11ef-96b6-a4bf0186f0c7",
    }
    
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
