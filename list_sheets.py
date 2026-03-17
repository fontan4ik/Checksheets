import gsheets_utils
import config

def list_sheets():
    client = gsheets_utils.get_gsheet_client()
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    sheets = spreadsheet.worksheets()
    for sheet in sheets:
        print(f"Sheet: {sheet.title}")

if __name__ == "__main__":
    list_sheets()
