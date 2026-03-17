import gspread
from google.oauth2.service_account import Credentials
import config

def export_titles():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    
    with open("sheet_titles.txt", "w", encoding="utf-8") as f:
        for i, ws in enumerate(spreadsheet.worksheets()):
            f.write(f"{i}: {ws.title}\n")
    print("Exported sheet titles to sheet_titles.txt")

if __name__ == "__main__":
    export_titles()
