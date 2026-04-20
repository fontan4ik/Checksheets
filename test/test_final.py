import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import zipfile

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET_SKU = '1644174248'

print('Waiting 2 minutes for rate limit...')
time.sleep(120)

print('Getting token...')
resp = requests.post(f'{BASE_URL}/api/client/token', json={
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'grant_type': 'client_credentials'
})
token = resp.json()['access_token']
print('Token OK')

print('Creating report...')
body = {
    'campaigns': ['24681662'],
    'dateFrom': '2025-04-01',
    'dateTo': '2025-04-15',
    'groupBy': 'SKU'
}
resp = requests.post(f'{BASE_URL}/api/client/statistics', 
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, 
    json=body)

print(f'Status: {resp.status_code}')
print(f'Response: {resp.text}')

if resp.status_code != 200:
    print('Failed!')
    sys.exit(1)

uuid = resp.json().get('UUID')
print(f'UUID: {uuid}')

if not uuid:
    print('No UUID!')
    sys.exit(1)

print('Waiting for report...')
for i in range(40):
    time.sleep(5)
    r = requests.get(f'{BASE_URL}/api/client/statistics/{uuid}',
        headers={'Authorization': f'Bearer {token}'})
    d = r.json()
    state = d.get('state')
    print(f'Attempt {i+1}: {state}')
    
    if state == 'OK':
        link = d.get('link', '')
        r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {token}'})
        content = r2.content
        
        if content[:2] == b'PK':
            z = zipfile.ZipFile(io.BytesIO(content))
            csv = z.read(z.namelist()[0]).decode('utf-8')
        else:
            csv = content.decode('utf-8')
        
        lines = csv.replace('\ufeff', '').strip().split('\n')
        print(f'Total lines: {len(lines)}')
        print(f'Header: {lines[0][:100]}')
        
        # Find target SKU
        for line in lines[1:]:
            if not line.strip() or 'Всего' in line or line.startswith('sku;'):
                continue
            parts = line.split(';')
            sku = parts[0].strip() if parts else ''
            if sku == TARGET_SKU:
                print(f'FOUND TARGET SKU {TARGET_SKU}!')
                spend = parts[8].strip() if len(parts) > 8 else '0'
                orders = parts[9].strip() if len(parts) > 9 else '0'
                revenue = parts[10].strip() if len(parts) > 10 else '0'
                print(f'Orders: {orders}, Spend: {spend}, Revenue: {revenue}')
                break
        else:
            print('Target not found. Sample data:')
            for line in lines[1:5]:
                if line.strip() and 'Всего' not in line and not line.startswith('sku;'):
                    print(f'  {line[:120]}')
        break
    elif state == 'ERROR':
        print(f'Error: {d.get("error")}')
        break

print('Done')
