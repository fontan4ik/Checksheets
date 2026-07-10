import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials

creds_file = os.path.join('..', 'nomadic-bedrock-485314-b0-d7624dedd83c.json')
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
client = gspread.authorize(creds)

files = client.list_spreadsheet_files()
print('All spreadsheets:')
for f in files:
    print('name:', f.get('name'), '| id:', f.get('id'))