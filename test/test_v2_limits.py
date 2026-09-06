import requests
import json

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

# Test maximum SKUs in one request
# Let's generate 500 dummy/real SKUs
skus = [1145227174] * 100

resp = requests.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    headers=OZON_HEADERS,
    json={"sku": skus, "limit": 1000}
)
print("100 SKUs with limit 1000 status:", resp.status_code)

skus500 = [1145227174] * 500
resp500 = requests.post(
    "https://api-seller.ozon.ru/v2/product/info/stocks-by-warehouse/fbs",
    headers=OZON_HEADERS,
    json={"sku": skus500, "limit": 1000}
)
print("500 SKUs with limit 1000 status:", resp500.status_code)
if resp500.status_code != 200:
    print(resp500.text)
