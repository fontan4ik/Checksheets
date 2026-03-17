import requests
import config

def get_etm_session():
    url = f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("data", {}).get("session")
    except: pass
    return None

def debug_stores(article, session_id):
    print(f"\n--- Stores for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        stores = response.json().get("data", {}).get("InfoStores", [])
        for s in stores:
            qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
            if qty > 0:
                print(f"  Qty: {qty} | Type: {s.get('StoreType')} | Name: {repr(s.get('StoreName'))}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_stores("13627", sid)
    else: print("No session")
