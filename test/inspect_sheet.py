import gspread
from google.oauth2.service_account import Credentials
import config

creds = Credentials.from_service_account_file(
    config.GSHEETS_CREDS_FILE,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(config.SPREADSHEET_ID)

ws_stream = sh.worksheet("StreamSupps")
all_stream = ws_stream.get_all_values()
headers = all_stream[0]

# Find columns
brand_idx = headers.index("brand")
art_idx = headers.index("Артикул продавца")
etm_smr_idx = headers.index("ETM SMR")
etm_samara_idx = headers.index("ЭТМ САМАРА")
codes_idx = headers.index("CODES")
x_idx = headers.index("Х")

print(f"Indices: art={art_idx}, brand={brand_idx}, ETM SMR={etm_smr_idx}, ЭТМ САМАРА={etm_samara_idx}, CODES={codes_idx}, X={x_idx}")

# Filter for Arlight
arlight_stream = [r for r in all_stream[1:] if len(r) > brand_idx and r[brand_idx].strip().lower() == "arlight"]
print(f"Total Arlight rows in StreamSupps: {len(arlight_stream)}")

has_codes = sum(1 for r in arlight_stream if len(r) > codes_idx and r[codes_idx].strip() not in ("", "0", 0, None))
has_etm_smr = sum(1 for r in arlight_stream if len(r) > etm_smr_idx and r[etm_smr_idx].strip() not in ("", "0", 0, None))
has_etm_samara = sum(1 for r in arlight_stream if len(r) > etm_samara_idx and r[etm_samara_idx].strip() not in ("", "0", 0, None))

print(f"Arlight rows with non-empty CODES: {has_codes}")
print(f"Arlight rows with non-zero ETM SMR: {has_etm_smr}")
print(f"Arlight rows with non-zero ЭТМ САМАРА: {has_etm_samara}")

# Print sample 10 Arlight rows with codes or stocks
print("\nSample Arlight rows with CODES or stocks:")
sample_found = 0
for r in arlight_stream:
    c = r[codes_idx] if len(r) > codes_idx else ""
    smr = r[etm_smr_idx] if len(r) > etm_smr_idx else ""
    sam = r[etm_samara_idx] if len(r) > etm_samara_idx else ""
    x_val = r[x_idx] if len(r) > x_idx else ""
    if c or smr or sam:
        print(f"  Art: {r[art_idx]} | CODES: '{c}' | ETM SMR(Q): '{smr}' | X(quantum): '{x_val}' | ЭТМ САМАРА(S): '{sam}'")
        sample_found += 1
        if sample_found >= 15:
            break

# Also check specific items from earlier ТЕСТ sample: 024110(2)-1, 024108(2)-1, 015698(2)-1
check_arts = ["024110(2)-1", "024108(2)-1", "015698(2)-1", "018327(2)-1"]
print("\nChecking specific arts from ТЕСТ in StreamSupps:")
for r in all_stream[1:]:
    art = r[art_idx] if len(r) > art_idx else ""
    if art in check_arts:
        c = r[codes_idx] if len(r) > codes_idx else ""
        smr = r[etm_smr_idx] if len(r) > etm_smr_idx else ""
        sam = r[etm_samara_idx] if len(r) > etm_samara_idx else ""
        x_val = r[x_idx] if len(r) > x_idx else ""
        print(f"  Art: {art} | CODES: '{c}' | ETM SMR: '{smr}' | X: '{x_val}' | ЭТМ САМАРА: '{sam}'")

# Also check column S formula for row 2 to 10 in StreamSupps
ws_stream = sh.worksheet("StreamSupps")
print("\nChecking formulas in StreamSupps!S (ЭТМ САМАРА):")
formulas_s = ws_stream.get("S2:S10", value_render_option="FORMULA")
print("S2:S10 formulas:", formulas_s)

# Also check how column AL in ТЕСТ is calculated or populated!
ws_test = sh.worksheet("ТЕСТ")
f_al = ws_test.get("AL2:AL10", value_render_option="FORMULA")
print("\nТЕСТ!AL2:AL10 formulas:", f_al)
