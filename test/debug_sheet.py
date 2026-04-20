import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials
from requests import Session

creds_file = os.path.join('..', 'nomadic-bedrock-485314-b0-ff60180040ed.json')
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
session = Session()
session.timeout = (30, 60)
client = gspread.authorize(creds, session=session)

SHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI'
spreadsheet = client.open_by_key(SHEET_ID)
sheet = spreadsheet.get_worksheet(0)

print('Sheet title:', sheet.title)
print('Row count:', sheet.row_count)
print('Col count:', sheet.col_count)

# Get first 5 rows of column A
print('\nColumn A (first 10):')
for i in range(1, 11):
    val = sheet.acell(f'A{i}').value
    print(f'  A{i}: {val}')

# Get first 5 rows of column V
print('\nColumn V (first 10):')
for i in range(1, 11):
    val = sheet.acell(f'V{i}').value
    print(f'  V{i}: {val}')

# Get all values from column A
print('\nAll column A values (limit 20):')
vals = sheet.col_values(1)[:20]
for i, v in enumerate(vals):
    print(f'  {i}: {v}')

# Get all values from column V
print('\nAll column V values (limit 20):')
vals = sheet.col_values(22)[:20]
for i, v in enumerate(vals):
    print(f'  {i}: {v}')