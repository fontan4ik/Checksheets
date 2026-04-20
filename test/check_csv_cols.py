import requests
import zipfile
import io
import time

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

# Token
r = requests.post(f'{BASE_URL}/api/client/token', json={
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'grant_type': 'client_credentials'
})
token = r.json()['access_token']
print("Token:", token[:20] + "...")

# Get campaign
r = requests.get(f'{BASE_URL}/api/client/campaign', headers={'Authorization': f'Bearer {token}'})
campaigns = r.json()['list']

# Find target
target = None
for c in campaigns:
    if 'Оплата за заказ' in c.get('title', '') and 'все товары' in c.get('title', ''):
        target = c
        break

if target:
    print(f"Campaign: {target['title']} (id: {target['id']})")
    
    # Report
    from datetime import date, timedelta
    today = date.today()
    date_to = today - timedelta(days=1)
    date_from = date_to - timedelta(days=6)
    
    print(f"Period: {date_from} -> {date_to}")
    
    r = requests.post(f'{BASE_URL}/api/client/statistics', headers={'Authorization': f'Bearer {token}'}, json={
        'campaigns': [target['id']],
        'dateFrom': date_from.strftime('%Y-%m-%d'),
        'dateTo': date_to.strftime('%Y-%m-%d'),
        'groupBy': 'SKU'
    })
    uuid = r.json()['UUID']
    print(f"UUID: {uuid}")
    
    # Wait
    for i in range(30):
        time.sleep(3)
        r = requests.get(f'{BASE_URL}/api/client/statistics/report?UUID={uuid}', headers={'Authorization': f'Bearer {token}'})
        if r.status_code == 200:
            content = r.content
            if content[:2] == b'PK':
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    with z.open(z.namelist()[0]) as f:
                        text = f.read().decode('utf-8-sig')
            else:
                text = content.decode('utf-8-sig')
            
            lines = text.split('\n')
            print('\n=== CSV Headers (first 500 chars) ===')
            print(lines[0][:500])
            print('\n=== Line for SKU 1644174248 ===')
            for line in lines:
                if '1644174248' in line:
                    print(line[:500])
                    break
            break