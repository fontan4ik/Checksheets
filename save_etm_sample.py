import requests
import json
import config

sid = "" # will fill

def get_session():
    url = f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}"
    r = requests.post(url, headers={"Accept": "application/json"})
    return r.json()["data"]["session"]

sid = get_session()
url = f"https://ipro.etm.ru/api/v1/goods/13627/remains?type=mnf&session-id={sid}"
r = requests.get(url, headers={"Accept": "application/json"})
with open("etm_sample.json", "w", encoding="utf-8") as f:
    json.dump(r.json(), f, indent=2, ensure_ascii=False)
