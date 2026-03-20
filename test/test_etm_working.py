import requests
import config

sid = "" # define

def get_sid():
    return requests.post(f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}").json()["data"]["session"]

sid = get_sid()
article = "MVA20-1-016-C" # stripped
url = f"https://ipro.etm.ru/api/v1/goods/{article}/remains?type=mnf&session-id={sid}"
r = requests.get(url)
stores = r.json()["data"]["InfoStores"]
for s in stores:
    print(f"Name: {s.get('StoreName')} | Type: {s.get('StoreType')} | Qty: {s.get('StoreQuantRem')}")
