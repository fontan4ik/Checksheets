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

def debug_full_object(article, session_id):
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        print(f"\n--- {article} ---")
        # Print the first few stores completely
        stores = data.get("data", {}).get("InfoStores", [])
        for i, s in enumerate(stores[:5]):
            print(f"Store {i}: {s}")
        # Also let's check if there's a global store list
        print(f"Other data keys: {data.get('data', {}).keys()}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_full_object("13627", sid)
    else:
        print("No session")
