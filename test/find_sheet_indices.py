import gspread
from google.oauth2.service_account import Credentials
import config

def find_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    
    for i, ws in enumerate(spreadsheet.worksheets()):
        try:
            headers = ws.row_values(1)
            # Check for RS sheet
            if "Модель" in headers:
                print(f"RS_INDEX = {i} (Title: {ws.title})")
            # Check for ETM sheet
            if "ЭТМ Стройкерамика" in headers or (len(headers) >= 38 and headers[37] == "ЭТМ Стройкерамика"):
                 print(f"ETM_INDEX = {i} (Title: {ws.title})")
            # Fallback for ETM if headers are mangled
            if "тест" in ws.title.lower() or i == 0:
                 if "Артикул" in headers:
                      print(f"ETM_CANDIDATE = {i} (Title: {ws.title})")
        except:
            continue

if __name__ == "__main__":
    find_sheets()
