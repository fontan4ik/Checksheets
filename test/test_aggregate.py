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

# Aggregate data for all SKUs
all_stats = {}

# Process in batches of 10
BATCH_SIZE = 10
total_batches = (len(campaigns) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num in range(total_batches):
    start_idx = batch_num * BATCH_SIZE
    end_idx = min(start_idx + BATCH_SIZE, len(campaigns))
    batch = campaigns[start_idx:end_idx]
    cid = [c['id'] for c in batch]
    
    print(f'\nBatch {batch_num+1}/{total_batches}: campaigns {start_idx}-{end_idx-1}')
    
    body = {
        'campaigns': cid,
        'dateFrom': '2025-04-01',
        'dateTo': '2025-04-15',
        'groupBy': 'SKU'
    }
    
    # Create report
    resp = requests.post(f'{BASE_URL}/api/client/statistics', 
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, 
        json=body, timeout=30)
    
    if resp.status_code != 200:
        print(f'  Error creating: {resp.status_code}')
        time.sleep(30)
        continue
    
    uuid = resp.json().get('UUID')
    if not uuid:
        print('  No UUID')
        time.sleep(30)
        continue
    
    # Wait for report
    report_ready = False
    for attempt in range(30):
        time.sleep(5)
        r = requests.get(f'{BASE_URL}/api/client/statistics/{uuid}',
            headers={'Authorization': f'Bearer {token}'})
        d = r.json()
        
        if d.get('state') == 'OK':
            link = d.get('link', '')
            r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {token}'})
            content = r2.content
            
            if content[:2] == b'PK':
                z = zipfile.ZipFile(io.BytesIO(content))
                csv = z.read(z.namelist()[0]).decode('utf-8')
            else:
                csv = content.decode('utf-8')
            
            lines = csv.replace('\ufeff', '').strip().split('\n')
            print(f'  Report lines: {len(lines)}')
            
            # Parse each line and aggregate
            for line in lines[1:]:
                if not line.strip() or 'Всего' in line or line.startswith('sku;'):
                    continue
                
                parts = line.split(';')
                if len(parts) < 11:
                    continue
                
                sku = parts[0].strip()
                if not sku:
                    continue
                
                # Parse values (handle Russian number format)
                try:
                    spend = float(parts[8].strip().replace(',', '.')) if parts[8].strip() else 0
                    orders = int(parts[9].strip()) if parts[9].strip() else 0
                    revenue = float(parts[10].strip().replace(',', '.')) if parts[10].strip() else 0
                except:
                    continue
                
                if sku not in all_stats:
                    all_stats[sku] = {'orders': 0, 'spend': 0, 'revenue': 0}
                
                all_stats[sku]['orders'] += orders
                all_stats[sku]['spend'] += spend
                all_stats[sku]['revenue'] += revenue
            
            report_ready = True
            break
        elif d.get('state') == 'ERROR':
            print(f'  Error: {d.get("error")}')
            break
    
    if not report_ready:
        print(f'  Report not ready')
    
    # Wait between batches to avoid rate limit
    if batch_num < total_batches - 1:
        time.sleep(60)

print('\n' + '='*50)
print('FINAL RESULTS')
print('='*50)

if TARGET_SKU in all_stats:
    data = all_stats[TARGET_SKU]
    print(f'\n*** TARGET SKU {TARGET_SKU} FOUND! ***')
    print(f'Orders: {data["orders"]}')
    print(f'Spend: {data["spend"]:.2f} RUB')
    print(f'Revenue: {data["revenue"]:.2f} RUB')
else:
    print(f'\n*** TARGET SKU {TARGET_SKU} NOT FOUND ***')
    print(f'Total unique SKUs collected: {len(all_stats)}')
    
    # Show top 10 by orders
    top = sorted(all_stats.items(), key=lambda x: x[1]['orders'], reverse=True)[:10]
    print('\nTop 10 by orders:')
    for sku, data in top:
        print(f'  {sku}: orders={data["orders"]}, spend={data["spend"]:.2f}, revenue={data["revenue"]:.2f}')

print('\nDone')
