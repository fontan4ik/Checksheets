import os
from google.oauth2 import service_account
import googleapiclient.discovery

creds_file = os.path.join('..', 'nomadic-bedrock-485314-b0-d7624dedd83c.json')

credentials = service_account.Credentials.from_service_account_file(
    creds_file, 
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)

service = googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)

SHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI'

# Try column V with explicit range
print('Testing column V...')
result = service.spreadsheets().values().get(
    spreadsheetId=SHEET_ID, 
    range="'тест'!V:V"
).execute()

vals = result.get('values', [])
print(f'Total rows: {len(vals)}')

# Print first 20 non-empty
non_empty = [v for v in vals if v and v[0]]
print(f'Non-empty rows: {len(non_empty)}')
for i, v in enumerate(non_empty[:20]):
    print(f'  {i}: {v}')