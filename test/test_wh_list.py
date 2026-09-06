import requests
import json

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

# 1. Test /v1/warehouse/list with payload
resp = requests.post(
    "https://api-seller.ozon.ru/v1/warehouse/list",
    headers=OZON_HEADERS,
    json={"limit": 200, "offset": 0}
)
print("v1/warehouse/list with body:", resp.status_code, resp.text[:300])

# 2. Test /v2/warehouse/list
resp2 = requests.post(
    "https://api-seller.ozon.ru/v2/warehouse/list",
    headers=OZON_HEADERS,
    json={"limit": 200, "offset": 0}
)
print("v2/warehouse/list with body:", resp2.status_code, resp2.text[:300])

# 3. Test /v1/warehouse/list GET or POST with {}
resp3 = requests.post(
    "https://api-seller.ozon.ru/v1/warehouse/list",
    headers=OZON_HEADERS,
    json={}
)
print("v1/warehouse/list with empty body:", resp3.status_code, resp3.text[:300])
