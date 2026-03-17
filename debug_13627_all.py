import requests
import config

sid = requests.post(f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}").json()["data"]["session"]
r = requests.get(f"https://ipro.etm.ru/api/v1/goods/13627/remains?type=mnf&session-id={sid}")
stores = r.json()["data"]["InfoStores"]
for s in stores:
    print(f"S: {s}")
