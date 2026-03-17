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

def debug_types(article, session_id):
    print(f"\n--- Testing types for: {article} ---")
    for t in ["mnf", "etm", "cli"]:
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type={t}&session-id={session_id}"
        headers = {"Accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            info_stores = data.get("data", {}).get("InfoStores", [])
            if info_stores:
                print(f"  [Type: {t}] Found {len(info_stores)} stores")
                for s in info_stores:
                    if (s.get("StoreQuantRem") or 0) > 0:
                         print(f"    Code: {s.get('StoreCode')} | Type: {s.get('StoreType')} | Qty: {s.get('StoreQuantRem')}")
            else:
                print(f"  [Type: {t}] No stores found")
        else:
            print(f"  [Type: {t}] Status {response.status_code}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_types("13627-5", sid)
        debug_types("13627", sid)
        debug_types("613100230-1", sid)
    else:
        print("No session")
