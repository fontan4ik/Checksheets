import requests
import json
import time
import config
import gsheets_utils
from concurrent.futures import ThreadPoolExecutor

def get_etm_session():
    url = f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            session_id = data.get("data", {}).get("session")
            if session_id:
                print(f"ETM Session obtained: {session_id}")
                return session_id
        print(f"ETM Login failed: {response.status_code} {response.text}")
    except Exception as e:
        print(f"ETM Login error: {e}")
    return None

def fetch_etm_stock(article, session_id):
    import re
    article = str(article).strip()
    if not article:
        return 0
        
    # ETM often expects base article without suffixes like -1, -5
    # Some articles in the sheet have -1, -2, -5 suffixes which should be stripped
    etm_article = re.sub(r'-\d+$', '', article)
    
    # Try variants: stripped article first, then original
    variants = [etm_article]
    if etm_article != article:
        variants.append(article)
        
    for variant in variants:
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"
        headers = {"Accept": "application/json"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                continue
                
            data = response.json()
            info_stores = data.get("data", {}).get("InfoStores", [])
            
            stock = 0
            found_any = False
            for store in info_stores:
                store_name = (store.get("StoreName") or "").lower()
                store_type = store.get("StoreType") or ""
                
                # Broaden matching: Stroykeramika or Samara
                # User reported that some items are in warehouses like "Самарская область..."
                is_stroy = any(k in store_name for k in ["стройкерамика", "самар"])
                
                # Include RC (Regional Center) and OP (Operational) stores
                if is_stroy and store_type in ["rc", "op"]:
                    qty = store.get("StoreQuantRem") or store.get("StockRem") or 0
                    stock += qty
                    found_any = True
                # Fallback: if StoreName is missing but it's a known Samara code (e.g. 24121, 8809)
                # But names are usually present for working articles.
            
            if found_any:
                return stock
        except Exception:
            continue
            
    return 0

def sync_etm():
    print("Starting ETM Local Sync (Parallelized)...")
    session_id = get_etm_session()
    if not session_id:
        return

    try:
        ws = gsheets_utils.get_worksheet(config.ETM_SHEET_NAME)
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return

    articles = ws.col_values(1)[1:] # Skip header
    print(f"Found {len(articles)} articles in column A")

    stock_results = [0] * len(articles)
    
    # Process in chunks to avoid overwhelming the server and show progress
    chunk_size = 50
    for i in range(0, len(articles), chunk_size):
        chunk = articles[i:i + chunk_size]
        print(f"   Processing chunk {i//chunk_size + 1}/{(len(articles)-1)//chunk_size + 1} ({i}/{len(articles)})...")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fetch_etm_stock, art, session_id) for art in chunk]
            for j, future in enumerate(futures):
                stock_results[i + j] = [future.result()]
        
        # Small sleep between chunks to stay safe
        time.sleep(0.5)

    print(f"Updating Google Sheet '{config.ETM_SHEET_NAME}' column AL...")
    try:
        gsheets_utils.clear_column(ws, "ЭТМ Стройкерамика")
        gsheets_utils.update_column_by_header(ws, "ЭТМ Стройкерамика", stock_results)
        print("ETM Sync completed successfully!")
    except Exception as e:
        print(f"Error updating sheet: {e}")

if __name__ == "__main__":
    sync_etm()
