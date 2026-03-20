import requests
import re
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

def test_new_logic(article, session_id):
    import re
    print(f"\nTesting: {article}")
    etm_article = re.sub(r'-\d+$', '', str(article).strip())
    print(f"  Stripped article: {etm_article}")
    
    variants = [etm_article]
    if etm_article != article:
        variants.append(article)
        
    for variant in variants:
        url = f"https://ipro.etm.ru/api/v1/goods/{requests.utils.quote(variant)}/remains?type=mnf&session-id={session_id}"
        headers = {"Accept": "application/json"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            stores = response.json().get("data", {}).get("InfoStores", [])
            stock = 0
            for s in stores:
                name = (s.get("StoreName") or "").lower()
                stype = s.get("StoreType") or ""
                if any(k in name for k in ["стройкерамика", "самар"]) and stype in ["rc", "op"]:
                    val = s.get("StoreQuantRem") or s.get("StockRem") or 0
                    print(f"    Match! Store: {repr(name)} ({stype}) | Qty: {val}")
                    stock += val
            if stock > 0:
                print(f"  Final Stock for {variant}: {stock}")
                return
    print(f"  Final Stock: 0")

if __name__ == "__main__":
    sid = get_etm_session()
    if sid:
        test_new_logic("13627-5", sid)
        test_new_logic("613100230-1", sid)
    else: print("No session")
