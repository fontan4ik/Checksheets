import requests
import json

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

# Check product_id 608931001, 608930963, 608931075
product_ids = [608931001, 608930963, 608931075]

resp = requests.post(
    "https://api-seller.ozon.ru/v4/product/info/stocks",
    headers=OZON_HEADERS,
    json={
        "filter": {
            "product_id": [str(p) for p in product_ids],
            "visibility": "ALL"
        },
        "limit": 10
    }
)
print("Stocks response status:", resp.status_code)
print(json.dumps(resp.json(), indent=2, ensure_ascii=False))

# Also check attributes for these product_ids
resp_attr = requests.post(
    "https://api-seller.ozon.ru/v4/product/info/attributes",
    headers=OZON_HEADERS,
    json={
        "filter": {
            "product_id": product_ids,
            "visibility": "ALL"
        },
        "limit": 10
    }
)
print("\nAttributes response status:", resp_attr.status_code)
if resp_attr.status_code == 200:
    for item in resp_attr.json().get("result", []):
        print(f"Product ID: {item.get('id')}, offer_id: '{item.get('offer_id')}', name: '{item.get('name')}'")
else:
    print(resp_attr.text)
