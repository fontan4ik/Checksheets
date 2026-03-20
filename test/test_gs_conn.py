import gspread
from google.oauth2.service_account import Credentials
import json
import config

def test_creds():
    try:
        # Use the filename from config
        creds_file = config.GSHEETS_CREDS_FILE
        print(f"Opening creds file: {creds_file}")
        with open(creds_file, "r", encoding="utf-8") as f:
            creds_data = json.load(f)
            print("JSON load success")
            
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet_id = config.SPREADSHEET_ID
        spreadsheet = client.open_by_key(spreadsheet_id)
        print(f"Connected to: {spreadsheet.title}")
        print("Worksheets:", [ws.title for ws in spreadsheet.worksheets()])
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_creds()
