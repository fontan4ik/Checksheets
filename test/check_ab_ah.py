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
headers = ws_test.row_values(1)

# Columns AB-AH are 28-34 (1-based), so indices 27 to 33
for col_idx in range(27, 34):
    h = headers[col_idx] if col_idx < len(headers) else f"Col {col_idx+1}"
    col_vals = ws_test.col_values(col_idx + 1)[1:] # exclude header
    nonzero = sum(1 for v in col_vals if v not in ("", "0", 0, None))
    print(f"Col {col_idx+1} ({chr(65+col_idx) if col_idx<26 else 'A'+chr(65+col_idx-26)}): '{h}' -> non-zero count: {nonzero} / {len(col_vals)}")
