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

def debug_final(article, session_id):
    print(f"\n--- Results for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        info_stores = data.get("data", {}).get("InfoStores", [])
        total_stroy = 0
        for s in info_stores:
            name = s.get("StoreName") or ""
            qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
            stype = s.get("StoreType") or "N/A"
            if qty > 0:
                # We'll just check if it's Stroykeramika but ignoring the encoding issues in printing
                is_stroy = "стройкерамика" in name.lower()
                print(f"  Qty: {qty} | Type: {stype} | Store: {repr(name)} | IsStroy: {is_stroy}")
                if is_stroy:
                    total_stroy += qty
        print(f"  Total for Stroykeramika (rc+op): {total_stroy}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        # Testing user's articles
        debug_final("13627", sid)
        debug_final("13627-5", sid)
        debug_final("613100230", sid)
        debug_final("613100230-1", sid)
    else:
        print("No session")
