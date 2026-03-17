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

def debug_article(article, session_id):
    print(f"\n--- Debugging: {article} ---")
    
    # Try different variants of the article
    variants = [article]
    if "-" in article:
        variants.append(article.split("-")[0])
    
    for variant in variants:
        print(f"  Trying variant: {variant}")
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"
        headers = {"Accept": "application/json"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"  Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                info_stores = data.get("data", {}).get("InfoStores", [])
                if not info_stores:
                    print("  No InfoStores found.")
                for store in info_stores:
                    name = store.get("StoreName")
                    stype = store.get("StoreType")
                    quant = store.get("StoreQuantRem") or store.get("StockRem") or 0
                    print(f"    - Store: {name} ({stype}), Quant: {quant}")
            else:
                print(f"  Response: {response.text}")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_article("13627-5", sid)
        debug_article("613100230-1", sid)
        debug_article("103801109-5", sid)
    else:
        print("Failed to get ETM session")
