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

def debug_all_stores(article, session_id):
    print(f"\n--- Searching stores for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        info_stores = data.get("data", {}).get("InfoStores", [])
        for s in info_stores:
            name = s.get("StoreName", "N/A")
            qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
            stype = s.get("StoreType", "N/A")
            code = s.get("StoreCode", "N/A")
            print(f"Name: {repr(name)} | Type: {stype} | Code: {code} | Qty: {qty}")
    else:
        print(f"Error {response.status_code}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        for a in ["13627", "13627-5", "613100230", "613100230-1"]:
            debug_all_stores(a, sid)
    else:
        print("No session")
