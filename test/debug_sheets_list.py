import os
from google.oauth2 import service_account
import googleapiclient.discovery

creds_file = os.path.join('..', 'nomadic-bedrock-485314-b0-ff60180040ed.json')

credentials = service_account.Credentials.from_service_account_file(
    creds_file, 
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)

service = googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)

SHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI'

# Get all sheet info
metadata = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
sheets = metadata.get('sheets', [])

print('All sheets:')
for i, s in enumerate(sheets):
    props = s.get('properties', {})
    print(f'{i}: title="{props.get("title")}", sheetId={props.get("sheetId")}, index={props.get("index")}')

# Try reading from Sheet0 by index
print('\n--- Try reading from first sheet (index 0) ---')
first = sheets[0]
title = first['properties']['title']
print(f'Title: {title}')

result = service.spreadsheets().values().get(
    spreadsheetId=SHEET_ID, 
    range=f"{title}!V:V"
).execute()
vals = result.get('values', [])
print(f'Rows: {len(vals)}')
if vals:
    print(f'First 5: {vals[:5]}')