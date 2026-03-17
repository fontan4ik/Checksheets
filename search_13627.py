import requests
import config

sid = requests.post(f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}").json()["data"]["session"]
url = f"https://ipro.etm.ru/api/v1/goods/search?str=13627&session-id={sid}"
r = requests.get(url)
items = r.json()["data"]["rows"]
for i in items:
    print(f"Name: {i.get('Name')} | MNF: {i.get('CodeManuf')} | ETM: {i.get('Code')}")
