import requests
import os
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
import googleapiclient.discovery

creds_file = os.path.join('..', 'nomadic-bedrock-485314-b0-ff60180040ed.json')

# Load credentials
credentials = service_account.Credentials.from_service_account_file(
    creds_file, 
    scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
)

# Build service
service = googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)

SHEET_ID = '15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI'

# Get sheet metadata
metadata = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
print('Title:', metadata.get('title'))
sheets = metadata.get('sheets', [])
print('Sheets:', [s.get('properties', {}).get('title') for s in sheets])

# Get first sheet (тест)
sheet_id = sheets[0]['properties']['sheetId']
print('First sheet ID:', sheet_id)

# Read column V (22) - first 10 rows
range_name = 'тест!V1:V10'
result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=range_name).execute()
values = result.get('values', [])
print('\nColumn V values:')
for i, row in enumerate(values):
    print(f'  {i}: {row}')