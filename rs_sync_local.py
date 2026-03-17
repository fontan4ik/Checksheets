import requests
import base64
import time
import config
import gsheets_utils

def get_rs_headers():
    auth_str = f"{config.RS_LOGIN}:{config.RS_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
    return {
        "Authorization": f"Basic {encoded_auth}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

def fetch_rs_code_map(warehouse_id):
    print(f"Fetching RS catalog for warehouse {warehouse_id}...")
    headers = get_rs_headers()
    code_map = {}
    categories = ["instock", "custom"]
    
    for cat in categories:
        page = 1
        last_page = 1
        while page <= last_page:
            url = f"{config.RS_BASE_URL}/position/{warehouse_id}/{cat}?page={page}&rows=1000"
            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    print(f"   Error fetching page {page} of {cat}: {response.status_code}")
                    break
                
                data = response.json()
                items = data.get("items", [])
                for item in items:
                    v_code = str(item.get("VENDOR_CODE", "")).strip()
                    if v_code:
                        code_map[v_code] = item.get("CODE")
                
                last_page = data.get("meta", {}).get("last_page", 1)
                if page == 1:
                    print(f"   Category {cat}: ~{data.get('meta', {}).get('rows_count')} items, {last_page} pages")
                
                page += 1
                time.sleep(0.1) 
            except Exception as e:
                print(f"   Network error: {e}")
                break
                
    print(f"Catalog loaded. Unique articles: {len(code_map)}")
    return code_map

def fetch_all_rs_stocks(warehouse_id):
    print(f"Fetching all RS stocks for warehouse {warehouse_id}...")
    headers = get_rs_headers()
    stock_data = {}
    page = 1
    last_page = 1
    
    while page <= last_page:
        url = f"{config.RS_BASE_URL}/residue/all/{warehouse_id}?page={page}&rows=200&category=all"
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"   Error fetching stocks page {page}: {response.status_code}")
                break
            
            # Get last page from headers or meta if present
            # Doc says x-pagination-page-count header
            if 'x-pagination-page-count' in response.headers:
                last_page = int(response.headers['x-pagination-page-count'])
            
            data = response.json()
            items = data.get("residues", [])
            for item in items:
                code = item.get("CODE")
                if code:
                    stock_data[code] = item.get("RESIDUE", 0)
            
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

def sync_rs():
    print("Starting RS Local Sync (Optimized)...")
    
    try:
        ws = gsheets_utils.get_worksheet(config.RS_SHEET_NAME)
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return

    # Find columns dynamically
    headers = ws.row_values(1)
    try:
        col_model = headers.index("Модель") + 1
        col_stock_api = headers.index("Остаток АПИ") + 1
        col_cooling = headers.index("Охлад") + 1
        col_rounded = headers.index("Округление") + 1
    except ValueError as e:
        print(f"Column not found: {e}")
        return

    models = ws.col_values(col_model)[1:]
    print(f"Found {len(models)} models in column '{headers[col_model-1]}'")

    # 1. Fetch code map (Vendor -> RS Code)
    code_map = fetch_rs_code_map(config.RS_WAREHOUSE_ID)
    
    # 2. Fetch all stocks (RS Code -> Residue)
    all_stocks = fetch_all_rs_stocks(config.RS_WAREHOUSE_ID)
    
    results_stock = []
    results_cooling = []
    results_rounded = []

    for i, model in enumerate(models):
        model = str(model).strip()
        stock = 0
        if model:
            rs_code = code_map.get(model)
            if rs_code:
                stock = all_stocks.get(rs_code, 0)
        
        cooling = stock / 4
        rounded = int(cooling + 0.99) # Math.ceil
        
        results_stock.append([stock])
        results_cooling.append([cooling])
        results_rounded.append([rounded])

    print(f"Updating Google Sheet '{config.RS_SHEET_NAME}'...")
    
    # Batch update everything
    try:
        # Clear old data
        gsheets_utils.clear_column(ws, "Остаток АПИ")
        gsheets_utils.clear_column(ws, "Охлад")
        gsheets_utils.clear_column(ws, "Округление")
        
        # Update new data
        gsheets_utils.update_column_by_header(ws, "Остаток АПИ", results_stock)
        gsheets_utils.update_column_by_header(ws, "Охлад", results_cooling)
        gsheets_utils.update_column_by_header(ws, "Округление", results_rounded)
        print("RS Sync completed successfully!")
    except Exception as e:
        print(f"Error updating sheet: {e}")

if __name__ == "__main__":
    sync_rs()
