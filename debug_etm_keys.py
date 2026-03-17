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

def debug_keys(article, session_id):
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        info_stores = data.get("data", {}).get("InfoStores", [])
        if info_stores:
            print(f"Keys in a store object: {info_stores[0].keys()}")
            # Print values for one store
            for k, v in info_stores[0].items():
                print(f"  {k}: {v}")
        else:
            print("No stores found")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_keys("13627", sid)
