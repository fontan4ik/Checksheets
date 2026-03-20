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

def debug_broad(article, session_id):
    print(f"\n--- Broad search for: {article} ---")
    url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(article)}/remains?type=mnf&session-id={session_id}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        info_stores = data.get("data", {}).get("InfoStores", [])
        total = 0
        for s in info_stores:
            name = s.get("StoreName") or ""
            qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
            stype = s.get("StoreType")
            if (qty > 0 or stype == "all") and stype != "etm_all":
                is_match = "самар" in name.lower() or "стройкерамика" in name.lower()
                print(f"  [{'MATCH' if is_match else 'SKIP'}] {repr(name)} ({stype}) | Qty: {qty}")
                if is_match and stype != "all":
                    total += qty
        print(f"  Total matched (excluding 'all'): {total}")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        debug_broad("13627", sid)
        debug_broad("613100230", sid)
    else: print("No session")
