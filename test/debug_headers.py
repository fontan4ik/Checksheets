import gspread
from google.oauth2.service_account import Credentials
import config

def check_headers():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    
    ws0 = spreadsheet.get_worksheet(0)
    h0 = ws0.row_values(1)
    if "ЭТМ Стройкерамика" in h0:
        print("ETM sheet is index 0")
    if "Модель" in h0:
        print("RS sheet is index 0")
    print(f"Index 0 total headers: {len(h0)}")
    if len(h0) >= 38:
        print(f"Col 38 (AL) header: {h0[37]}")

    ws6 = spreadsheet.get_worksheet(6)
    h6 = ws6.row_values(1)
    print(f"Index 6 total headers: {len(h6)}")
    print(f"Index 6 first headers: {h6[:10]}")
    if "Модель" in h6:
        print("RS sheet is index 6")

if __name__ == "__main__":
    check_headers()
