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

def debug_sums(article, session_id):
    print(f"\n--- Sums for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        info_stores = data.get("data", {}).get("InfoStores", [])
        total = 0
        for s in info_stores:
            name = s.get("StoreName") or "N/A"
            qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
            stype = s.get("StoreType") or "N/A"
            if stype != "all" and qty > 0:
                print(f"  {repr(name)} ({stype}) | Qty: {qty}")
                total += qty
        print(f"  Total (exc. 'all'): {total}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        # Strip suffixes manually for test
        debug_sums("13627", sid)
        debug_sums("613100230", sid)
        debug_sums("103801109", sid)
    else:
        print("No session")
