import gspread
from google.oauth2.service_account import Credentials
import config

def get_gsheet_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    return gspread.authorize(creds)

def get_worksheet(sheet_name):
    if config.SPREADSHEET_ID == "YOUR_SPREADSHEET_ID":
        raise ValueError("Please set SPREADSHEET_ID in config.py")
    client = get_gsheet_client()
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    return spreadsheet.worksheet(sheet_name)

def update_column_by_header(worksheet, header_name, values, start_row=2):
    """
    Updates a specific column identified by its header name.
    values should be a list of single-item lists: [[v1], [v2], ...]
    """
    headers = worksheet.row_values(1)
    try:
        col_index = headers.index(header_name) + 1
    except ValueError:
        # Fallback for ETM if AL is known
        if header_name == "ЭТМ Стройкерамика":
            col_index = 38
        else:
            raise ValueError(f"Header '{header_name}' not found in sheet")
    
    range_label = f"{gspread.utils.rowcol_to_a1(start_row, col_index)}:{gspread.utils.rowcol_to_a1(start_row + len(values) - 1, col_index)}"
    worksheet.update(range_label, values)

def clear_column(worksheet, header_name, start_row=2):
    """
    Clears all data in a specific column starting from start_row.
    """
    headers = worksheet.row_values(1)
    try:
        col_index = headers.index(header_name) + 1
    except ValueError:
        if header_name == "ЭТМ Стройкерамика":
            col_index = 38
        else:
            return # Header not found, nothing to clear
            
    last_row = worksheet.row_count
    if last_row < start_row:
        return
        
    col_letter = gspread.utils.rowcol_to_a1(1, col_index).strip('1')
    range_label = f"{col_letter}{start_row}:{col_letter}{last_row}"
    worksheet.batch_clear([range_label])
