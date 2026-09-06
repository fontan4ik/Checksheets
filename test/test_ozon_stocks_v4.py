import requests
import json
import gspread
from google.oauth2.service_account import Credentials
import config

OZON_CLIENT_ID = "142355"
OZON_API_KEY = "fe539630-170b-4b48-b222-8ba092907a63"
OZON_HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}
ETM_OZON_WAREHOUSE = 1020005000689690

creds = Credentials.from_service_account_file(
    config.GSHEETS_CREDS_FILE,
    scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(config.SPREADSHEET_ID)

ws_stream = sh.worksheet("StreamSupps")
all_stream = ws_stream.get_all_values()
h_stream = all_stream[0]
art_s_idx = h_stream.index("Артикул продавца")
brand_s_idx = h_stream.index("brand")
samara_s_idx = h_stream.index("ЭТМ САМАРА")
etm_smr_idx = h_stream.index("ETM SMR")
codes_idx = h_stream.index("CODES")

positive_arlight = []
for r in all_stream[1:]:
    b = r[brand_s_idx].strip() if len(r) > brand_s_idx else ""
    if b.lower() == "arlight":
        st = r[samara_s_idx].strip() if len(r) > samara_s_idx else ""
        if st and st not in ("0", 0):
            positive_arlight.append({
                "art": r[art_s_idx],
                "stock": int(st),
                "etm_smr": r[etm_smr_idx],
                "codes": r[codes_idx]
            })

print(f"Found {len(positive_arlight)} Arlight items with positive stock in StreamSupps!S")

# Check product info on Ozon via POST /v3/products/info/attributes or /v2/product/info/list
# Let's test /v3/products/info/attributes for the first 10 offer_ids
arts = [x["art"] for x in positive_arlight[:10]]
print(f"Checking offer_ids on Ozon: {arts}")

# v2/product/info/list
resp = requests.post(
    "https://api-seller.ozon.ru/v2/product/info/list",
    headers=OZON_HEADERS,
    json={"offer_id": arts}
)
print(f"POST /v2/product/info/list status: {resp.status_code}")
if resp.status_code == 200:
    items = resp.json().get("result", {}).get("items", [])
    print(f"Returned {len(items)} items from Ozon:")
    for it in items:
        print(f"  offer_id: {it.get('offer_id')}, id: {it.get('id')}, sku: {it.get('sku')}, stocks: {it.get('stocks')}")
else:
    print(resp.text)

# Also check /v4/product/info/stocks for warehouse 1020005000689690!
# Official Ozon method for FBS stocks: POST /v4/product/info/stocks
resp_stocks = requests.post(
    "https://api-seller.ozon.ru/v4/product/info/stocks",
    headers=OZON_HEADERS,
    json={
        "filter": {
            "offer_id": arts,
            "visibility": "ALL"
        },
        "limit": 100
    }
)
print(f"\nPOST /v4/product/info/stocks status: {resp_stocks.status_code}")
if resp_stocks.status_code == 200:
    items = resp_stocks.json().get("result", {}).get("items", [])
    print(f"Returned stocks for {len(items)} items:")
    for it in items:
        # filter by warehouse_id
        wh_stocks = [s for s in it.get("stocks", []) if s.get("type") == "fbs"]
        print(f"  offer_id: {it.get('offer_id')}, product_id: {it.get('product_id')}, stocks: {wh_stocks}")
else:
    print(resp_stocks.text)
