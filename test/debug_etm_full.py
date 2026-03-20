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

def debug_full(article, session_id):
    print(f"\n--- Full search for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        info_stores = data.get("data", {}).get("InfoStores", [])
        if info_stores:
            for s in info_stores:
                print(f"Type: {s.get('StoreType')} | Code: {s.get('StoreCode')} | Qty: {s.get('StoreQuantRem')}")
        else:
            print("No stores found for this exact article")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_full("13627-5", sid)
        debug_full("613100230-1", sid)
        debug_full("103801109-5", sid)
    else:
        print("No session")
