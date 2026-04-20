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

# Wait for rate limit
print('Waiting 120 seconds...')
time.sleep(120)

# Get token
print('Getting token...')
resp = requests.post(f'{BASE_URL}/api/client/token', json={
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'grant_type': 'client_credentials'
})
token = resp.json()['access_token']
print('Token OK')

# Get campaigns
print('Getting campaigns...')
resp = requests.get(f'{BASE_URL}/api/client/campaign', 
    headers={'Authorization': f'Bearer {token}'})
campaigns = resp.json()['list']
print(f'Found {len(campaigns)} campaigns')

# Try with different campaigns in batches
for batch_start in range(0, min(50, len(campaigns)), 10):
    batch = campaigns[batch_start:batch_start+10]
    cid = [c['id'] for c in batch]
    
    print(f'\nTrying campaigns {batch_start}-{batch_start+len(batch)} ({len(cid)} campaigns)...')
    
    body = {
        'campaigns': cid,
        'dateFrom': '2025-04-01',
        'dateTo': '2025-04-15',
        'groupBy': 'SKU'
    }
    resp = requests.post(f'{BASE_URL}/api/client/statistics', 
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, 
        json=body)
    
    if resp.status_code != 200:
        print(f'Status: {resp.status_code} - {resp.text[:100]}')
        continue
    
    uuid = resp.json().get('UUID')
    if not uuid:
        print('No UUID')
        continue
    
    print(f'UUID: {uuid}')
    
    # Wait for report
    for i in range(30):
        time.sleep(5)
        r = requests.get(f'{BASE_URL}/api/client/statistics/{uuid}',
            headers={'Authorization': f'Bearer {token}'})
        d = r.json()
        state = d.get('state')
        
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
            print(f'Report lines: {len(lines)}')
            
            # Find target SKU
            found = False
            for line in lines[1:]:
                if not line.strip() or 'Всего' in line or line.startswith('sku;'):
                    continue
                parts = line.split(';')
                sku = parts[0].strip() if parts else ''
                if sku == TARGET_SKU:
                    found = True
                    spend = parts[8].strip() if len(parts) > 8 else '0'
                    orders = parts[9].strip() if len(parts) > 9 else '0'
                    revenue = parts[10].strip() if len(parts) > 10 else '0'
                    print(f'*** FOUND TARGET SKU {TARGET_SKU}! ***')
                    print(f'Orders: {orders}, Spend: {spend}, Revenue: {revenue}')
                    sys.exit(0)
            
            if not found:
                sample = [lines[i].split(';')[0] for i in range(1, min(4, len(lines))) 
                          if lines[i].strip() and 'Всего' not in lines[i]]
                print(f'Sample SKUs in this batch: {sample}')
            break
        elif state == 'ERROR':
            print(f'Error: {d.get("error")}')
            break
    
    # Wait between batches
    time.sleep(60)

print('Done - target SKU not found in any batch')
