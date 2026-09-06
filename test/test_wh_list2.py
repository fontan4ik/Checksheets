import requests
import json

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

resp = requests.post(
    "https://api-seller.ozon.ru/v2/warehouse/list",
    headers=OZON_HEADERS,
    json={}
)
print("v2/warehouse/list status:", resp.status_code)
data = resp.json()
print("Keys:", data.keys())
warehouses = data.get("result") or data.get("warehouses", [])
print(f"Total warehouses: {len(warehouses)}")
for wh in warehouses:
    print(f"  ID: {wh.get('warehouse_id')}, name: '{wh.get('name')}', status: {wh.get('status')}")
