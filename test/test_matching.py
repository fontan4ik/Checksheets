import requests

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

resp = requests.post("https://api-seller.ozon.ru/v2/warehouse/list", headers=OZON_HEADERS, json={})
warehouses = resp.json().get("warehouses", [])

target_warehouses = [
  { "name": "ФЕРОН ФБС", "column": 28, "letter": "AB" },
  { "name": "ЭТМ САМАРА", "column": 29, "letter": "AC" },
  { "name": "РЕЗЕРВ", "column": 30, "letter": "AD" },
  { "name": "НТЦ СКЛАД", "column": 31, "letter": "AE" },
  { "name": "ПОДОРОЖНИК ФБС", "column": 32, "letter": "AF" },
  { "name": "Арлайт Москва", "column": 33, "letter": "AG" },
  { "name": "GAUSS MSK", "column": 34, "letter": "AH" }
]

print("Matching targets against v2/warehouse/list:")
for t in target_warehouses:
    wh = next((w for w in warehouses if w.get("name") == t["name"] or (w.get("name") and t["name"].lower() in w.get("name").lower())), None)
    if wh:
        print(f"  MATCH: {t['name']} -> ID {wh.get('warehouse_id')} ({wh.get('name')}) | status: {wh.get('status')}")
    else:
        print(f"  NOT FOUND: {t['name']}")
