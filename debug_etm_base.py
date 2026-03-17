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

def search_article(article, session_id):
    print(f"\n--- Searching Catalog for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/search?str={requests.utils.quote(article)}&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        items = data.get("data", {}).get("rows", [])
        for item in items:
            print(f"  Found: {item.get('Name')} | MNF: {item.get('CodeManuf')}")

if __name__ == "__main__":
    sid = get_etm_session()
    search_article("13627", sid)
    search_article("613100230", sid)
