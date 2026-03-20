import gspread
from google.oauth2.service_account import Credentials
import config

def deep_search():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    
    print("Searching for specific headers...")
    search_terms = ["ЭТМ Стройкерамика", "Модель", "Остаток АПИ"]
    
    for i, ws in enumerate(spreadsheet.worksheets()):
        try:
            h = ws.row_values(1)
            for term in search_terms:
                if term in h:
                    print(f"MATCH: '{term}' found in WS {i} (Title: {ws.title}) at column {h.index(term)+1}")
        except:
            continue

if __name__ == "__main__":
    deep_search()
