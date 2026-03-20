import gsheets_utils
import config

def list_worksheets():
    try:
        client = gsheets_utils.get_gsheet_client()
        spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
        print("Worksheets found:")
        for ws in spreadsheet.worksheets():
            print(f"Name: {ws.title}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_worksheets()
