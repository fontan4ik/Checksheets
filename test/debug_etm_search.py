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
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        items = data.get("data", {}).get("rows", [])
        if items:
            for item in items:
                print(f"  Found: {item.get('Name')} | ETM Code: {item.get('Code')} | MNF Code: {item.get('CodeManuf')}")
                # Get remains for this ETM code
                rem_url = f"https://ipro.etm.ru/api/v1/goods/{item.get('Code')}/remains?type=etm&session-id={session_id}"
                rem_r = requests.get(rem_url, headers=headers)
                if rem_r.status_code == 200:
                    stores = rem_r.json().get("data", {}).get("InfoStores", [])
                    total = 0
                    for s in stores:
                        qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
                        stype = s.get("StoreType")
                        name = s.get("StoreName") or ""
                        if qty > 0 and stype != "all":
                            print(f"    - Store: {repr(name)} ({stype}) | Qty: {qty}")
                            if "стройкерамика" in name.lower() or "самарская" in name.lower():
                                total += qty
                    print(f"    Total Stroy/Samara: {total}")
        else:
            print("  Nothing found in catalog search")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        search_article("13627-5", sid)
        search_article("613100230-1", sid)
    else: print("No session")
