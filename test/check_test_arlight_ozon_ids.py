import gspread
from google.oauth2.service_account import Credentials
import config

creds = Credentials.from_service_account_file(
    config.GSHEETS_CREDS_FILE,
    scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(config.SPREADSHEET_ID)

ws_test = sh.worksheet("ТЕСТ")
all_test = ws_test.get_all_values()
h = all_test[0]

art_idx = 0
brand_idx = 2
product_id_idx = 20 # Col U (21)
sku_idx = 21 # Col V (22)

arlight_rows = [r for r in all_test[1:] if len(r) > brand_idx and r[brand_idx].strip().lower() == "arlight"]
print(f"Total Arlight rows in ТЕСТ: {len(arlight_rows)}")

has_product_id = sum(1 for r in arlight_rows if len(r) > product_id_idx and r[product_id_idx].strip() not in ("", "0", 0, None))
has_sku = sum(1 for r in arlight_rows if len(r) > sku_idx and r[sku_idx].strip() not in ("", "0", 0, None))

print(f"Arlight rows with valid product_id (U): {has_product_id}")
print(f"Arlight rows with valid sku (V): {has_sku}")

# Let's inspect some of these
for r in arlight_rows[:10]:
    art = r[art_idx]
    pid = r[product_id_idx] if len(r) > product_id_idx else ""
    sku = r[sku_idx] if len(r) > sku_idx else ""
    print(f"  Art: '{art}' | Product_id: '{pid}' | SKU: '{sku}'")

# Also check how many rows in TOTAL in ТЕСТ have valid product_id
total_has_pid = sum(1 for r in all_test[1:] if len(r) > product_id_idx and r[product_id_idx].strip() not in ("", "0", 0, None))
print(f"\nTotal rows in ТЕСТ with valid product_id: {total_has_pid} / {len(all_test)-1}")
