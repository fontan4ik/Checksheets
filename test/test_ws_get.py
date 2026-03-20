import gsheets_utils
import config

print("Testing get_worksheet...")
try:
    ws = gsheets_utils.get_worksheet(config.ETM_SHEET_NAME)
    print(f"Success! WS title: {ws.title}")
    headers = ws.row_values(1)
    print(f"Headers: {headers[:5]}")
except Exception as e:
    print(f"Error: {e}")
