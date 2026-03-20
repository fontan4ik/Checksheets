import requests
import json
import time
import config
import gsheets_utils

def get_etm_session():
    url = f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            session_id = data.get("data", {}).get("session")
            if session_id:
                return session_id
    except: pass
    return None

def fetch_etm_stock(article, session_id):
    etm_article = article[:-2] if article.endswith("-1") else article
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(etm_article)}/remains?type=mnf&session-id={session_id}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            info_stores = data.get("data", {}).get("InfoStores", [])
            stock = 0
            for store in info_stores:
                if "стройкерамика" in (store.get("StoreName") or "").lower() and store.get("StoreType") == "rc":
                    stock += (store.get("StoreQuantRem") or store.get("StockRem") or 0)
            return stock
    except: pass
    return 0

def test():
    print("Testing ETM sync for 5 articles...")
    session_id = get_etm_session()
    if not session_id:
        print("Login failed")
        return
    
    ws = gsheets_utils.get_worksheet(config.ETM_SHEET_NAME)
    articles = ws.col_values(1)[1:6]
    print(f"Test articles: {articles}")
    
    results = []
    for art in articles:
        s = fetch_etm_stock(art, session_id)
        print(f"  {art}: {s}")
        results.append([s])
    
    # Optional: don't actually update the sheet in the test to be safe, 
    # or just update the first 5 rows.
    print("Test finished successfully")

if __name__ == "__main__":
    test()
