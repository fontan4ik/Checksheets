import requests
import json

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

# 1. Test /v1/warehouse/list
# Check why it gave 400
resp = requests.post("https://api-seller.ozon.ru/v1/warehouse/list", headers=OZON_HEADERS)
print("Warehouse list (no body) status:", resp.status_code)
if resp.status_code != 200:
    print(resp.text)
else:
    for wh in resp.json().get("result", []):
        print(f"Warehouse: ID={wh.get('warehouse_id')}, name='{wh.get('name')}', has_entrust_stocks={wh.get('has_entrust_stocks')}")

# 2. Test /v2/product/info/stocks-by-warehouse/fbs with limit=100
sku = 1145227174 # SKU for 024108(2)-1
r = requests.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    headers=OZON_HEADERS,
    json={"sku": [sku], "limit": 100}
)
print(f"\nStocks for SKU {sku} across warehouses (HTTP {r.status_code}):")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# 3. Test on specific warehouse 1020005000689690 (ЭТМ САМАРА)
r_etm = requests.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    headers=OZON_HEADERS,
    json={"sku": [sku], "warehouse_id": 1020005000689690, "limit": 100}
)
print(f"\nStocks for SKU {sku} on warehouse 1020005000689690 (HTTP {r_etm.status_code}):")
print(json.dumps(r_etm.json(), indent=2, ensure_ascii=False))
