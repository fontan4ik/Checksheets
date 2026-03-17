import json

with open("etm_sample.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    stores = data.get("data", {}).get("InfoStores", [])
    for s in stores:
        print(s)
