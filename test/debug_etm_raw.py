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

def debug_raw(article, session_id):
    print(f"\n--- Raw JSON for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print(f"Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        # Test the base article for the first case
        debug_raw("13627", sid)
        # Test another one
        debug_raw("613100230", sid)
    else:
        print("Failed session")
