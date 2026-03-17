import requests
import config

sid = requests.post(f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}").json()["data"]["session"]
r = requests.get(f"https://ipro.etm.ru/api/v1/goods/613100230/remains?type=mnf&session-id={sid}")
stores = r.json()["data"]["InfoStores"]
for s in stores:
    name = s.get("StoreName") or "N/A"
    qty = s.get("StoreQuantRem") or s.get("StockRem") or 0
    stype = s.get("StoreType")
    if qty > 0:
        print(f"Name: {repr(name)} | Type: {stype} | Qty: {qty}")
