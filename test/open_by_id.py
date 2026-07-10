import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials

creds_file = os.path.join('..', 'nomadic-bedrock-485314-b0-d7624dedd83c.json')
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
client = gspread.authorize(creds)

SHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI'
spreadsheet = client.open_by_key(SHEET_ID)

# Print all sheet titles
print('All worksheets:')
for w in spreadsheet.worksheets():
    print(' -', w.title)