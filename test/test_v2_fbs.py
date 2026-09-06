import requests
import json

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

# Test POST /v2/product/info/stocks-by-warehouse/fbs
# Payload options: sku, warehouse_id (optional?), limit
# Let's test passing sku list with warehouse_id
skus = [1145227174, 1145227331, 1145227420]
payload = {
    "sku": skus,
    "warehouse_id": 1020005000689690, # ЭТМ САМАРА
    "limit": 100
}

resp = requests.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    headers=OZON_HEADERS,
    json=payload
)
print("status:", resp.status_code)
data = resp.json()
print("Keys in response:", data.keys())
print("products count:", len(data.get("products", [])))
print(json.dumps(data, indent=2, ensure_ascii=False))
