import gspread
from google.oauth2.service_account import Credentials
import config

def verify_indices():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    
    indices = [0, 6, 26]
    for idx in indices:
        ws = spreadsheet.get_worksheet(idx)
        print(f"WS {idx} (Title: {ws.title}) Headers: {ws.row_values(1)[:40]}")

if __name__ == "__main__":
    verify_indices()
