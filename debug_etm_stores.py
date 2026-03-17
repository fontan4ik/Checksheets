import requests
import json
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
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            info_stores = data.get("data", {}).get("InfoStores", [])
            for store in info_stores:
                name = store.get("StoreName", "N/A")
                stype = store.get("StoreType", "N/A")
                quant = store.get("StoreQuantRem") or store.get("StockRem") or 0
                # Filter for interesting stores
                # We'll print ALL to see what we are missing
                print(f"Name: {name} | Type: {stype} | Qty: {quant}")
        else:
            print(f"Error {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        # User said 13627-5 is 147.
        # My previous test showed 13627-5 returned nothing (No InfoStores).
        # So it MUST be just 13627.
        debug_stores("13627", sid)
    else:
        print("Failed session")
