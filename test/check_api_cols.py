import requests
import zipfile
import io
import time

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

# Token
r = requests.post(BASE_URL + '/api/client/token', json={
    'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'})
token = r.json()['access_token']

# Get campaign id
r = requests.get(BASE_URL + '/api/client/campaign', headers={'Authorization': 'Bearer ' + token})
campaigns = r.json()['list']
target = [c for c in campaigns if 'Оплата за заказ' in c.get('title', '') and 'все товары' in c.get('title', '')][0]
campaign_id = target['id']

# Request NEW report
from datetime import date, timedelta
today = date.today()
date_to = today - timedelta(days=1)
date_from = date_to - timedelta(days=6)

r = requests.post(BASE_URL + '/api/client/statistics', headers={'Authorization': 'Bearer ' + token}, json={
    'campaigns': [campaign_id], 'dateFrom': date_from.strftime('%Y-%m-%d'), 'dateTo': date_to.strftime('%Y-%m-%d'), 'groupBy': 'SKU'})
uuid = r.json()['UUID']

# Wait
for i in range(30):
    time.sleep(3)
    r = requests.get(BASE_URL + '/api/client/statistics/report?UUID=' + uuid, headers={'Authorization': 'Bearer ' + token})
    if r.status_code == 200:
        content = r.content
        if content[:2] == b'PK':
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                with z.open(z.namelist()[0]) as f:
                    text = f.read().decode('utf-8-sig')
        else:
            text = content.decode('utf-8-sig')
        
        # Save to file
        with open('api_output.csv', 'w', encoding='utf-8') as f:
            f.write(text)
        
        lines = text.split('\n')
        
        # Find SKU
        for line in lines:
            if '1644174248' in line:
                parts = line.split(';')
                with open('sku_output.txt', 'w', encoding='utf-8') as f:
                    f.write("Parts count: " + str(len(parts)) + "\n")
                    for i, p in enumerate(parts):
                        f.write(str(i) + ": " + p + "\n")
                print("Saved to sku_output.txt")
                break
        break