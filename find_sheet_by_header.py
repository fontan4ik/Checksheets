import gspread
from google.oauth2.service_account import Credentials
import config

def find_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    
    print("Scanning worksheets...")
    for i, ws in enumerate(spreadsheet.worksheets()):
        headers = ws.row_values(1)
        print(f"WS {i}: '{ws.title}' | Headers: {headers[:10]}...")
        if "Модель" in headers:
            print(f"  >>> POTENTIAL RS SHEET: Index {i}, Title: {ws.title}")
        if "ЭТМ Стройкерамика" in headers or any("ЭТМ" in h for h in headers):
             print(f"  >>> POTENTIAL ETM SHEET: Index {i}, Title: {ws.title}")

if __name__ == "__main__":
    find_sheets()
