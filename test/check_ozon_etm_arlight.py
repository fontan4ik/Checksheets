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

# Let's read some Arlight items from ТЕСТ and StreamSupps
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
sku_s_idx = h_stream.index("SKU OZON")

# Find top Arlight items in StreamSupps that have positive stock in column S
positive_arlight = []
for r in all_stream[1:]:
    b = r[brand_s_idx].strip() if len(r) > brand_s_idx else ""
    if b.lower() == "arlight":
        st = r[samara_s_idx].strip() if len(r) > samara_s_idx else ""
        if st and st not in ("0", 0):
            positive_arlight.append({
                "art": r[art_s_idx],
                "stock": st,
                "sku": r[sku_s_idx] if len(r) > sku_s_idx else ""
            })

print(f"Total positive Arlight items in StreamSupps!S: {len(positive_arlight)}")
for item in positive_arlight[:10]:
    print(f"  Art: {item['art']} | Stock: {item['stock']} | SKU in StreamSupps: {item['sku']}")

# Also find these items in sheet ТЕСТ to see their SKU and values
ws_test = sh.worksheet("ТЕСТ")
all_test = ws_test.get_all_values()
h_test = all_test[0]
art_t_idx = 0
brand_t_idx = 2 # C (3)
ac_idx = 28 # AC (29) ЭТМ САМАРА
al_idx = 37 # AL (38) ЭТМ Самара
sku_t_idx = 21 # V (22) SKU Ozon

test_lookup = {}
for r in all_test[1:]:
    art = r[art_t_idx].strip() if len(r) > art_t_idx else ""
    if art:
        test_lookup[art] = {
            "sku": r[sku_t_idx] if len(r) > sku_t_idx else "",
            "ac": r[ac_idx] if len(r) > ac_idx else "",
            "al": r[al_idx] if len(r) > al_idx else "",
        }

print("\nCross-reference with ТЕСТ:")
for item in positive_arlight[:10]:
    t_data = test_lookup.get(item["art"], {})
    print(f"  Art: {item['art']} | Stream S: {item['stock']} | ТЕСТ AL: {t_data.get('al')} | ТЕСТ AC: {t_data.get('ac')} | ТЕСТ SKU: {t_data.get('sku')}")

# Now let's query Ozon API for these items:
# 1. /v2/product/info by offer_id
sample_arts = [it["art"] for it in positive_arlight[:5]]
print(f"\nQuerying Ozon /v2/product/info for offer_ids: {sample_arts}")
resp = requests.post(
    "https://api-seller.ozon.ru/v2/product/info",
    headers=OZON_HEADERS,
    json={"offer_id": sample_arts[0]}
)
print(f"Ozon response for {sample_arts[0]} (HTTP {resp.status_code}):")
if resp.status_code == 200:
    data = resp.json().get("result", {})
    print(f"  ID: {data.get('id')}, SKU: {data.get('sku')}, Name: {data.get('name')}, Visible: {data.get('visible')}")
    print(f"  Stocks: {data.get('stocks')}")
else:
    print(resp.text)

# 2. Check stock on warehouse ETM SAMARA (1020005000689690)
# via /v1/product/info/stocks-by-warehouse/fbs
sample_skus = [int(test_lookup[a]["sku"]) for a in sample_arts if test_lookup.get(a, {}).get("sku") and test_lookup[a]["sku"].isdigit()]
if sample_skus:
    print(f"\nQuerying Ozon /v1/product/info/stocks-by-warehouse/fbs for SKUs {sample_skus} on warehouse {ETM_OZON_WAREHOUSE}:")
    resp_wh = requests.post(
        "https://api-seller.ozon.ru/v1/product/info/stocks-by-warehouse/fbs",
        headers=OZON_HEADERS,
        json={"sku": sample_skus, "warehouse_id": ETM_OZON_WAREHOUSE}
    )
    print(f"Warehouse stocks response (HTTP {resp_wh.status_code}):")
    print(json.dumps(resp_wh.json(), indent=2, ensure_ascii=False))
