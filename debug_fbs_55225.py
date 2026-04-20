import gspread
from oauth2client.service_account import ServiceAccountCredentials
import config

# Connect to Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(config.GSHEETS_CREDS_FILE, scope)
client = gspread.authorize(creds)

# Open spreadsheet
spreadsheet = client.open_by_key(config.SPREADSHEET_ID)

# Try "FERON TR" sheet
ws = spreadsheet.worksheet("FERON TR")

# Get column B values (articles)
col_b_values = ws.col_values(2)

print(f"Total rows in column B (FERON TR): {len(col_b_values)}")
print(f"First 5 values: {col_b_values[:5]}")

# Find row with article 55225
article_to_find = "55225"
for idx, val in enumerate(col_b_values):
    if str(val).strip() == article_to_find:
        print(f"\nFound '{article_to_find}' at row {idx+1}")
        # Check columns H, I, J for this row
        h_val = ws.cell(idx+1, 8).value  # Column H
        i_val = ws.cell(idx+1, 9).value  # Column I  
        j_val = ws.cell(idx+1, 10).value # Column J
        print(f"  Current values: H={h_val}, I={i_val}, J={j_val}")
        break
else:
    print(f"\nArticle '{article_to_find}' NOT found in column B!")

# Check column A too
col_a_values = ws.col_values(1)
print(f"\nFirst 5 values in column A: {col_a_values[:5]}")