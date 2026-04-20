#!/usr/bin/env python3
"""Find target SKU across all campaigns - early stop"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

def get_token():
    return requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30).json()['access_token']

def get_camps(tok):
    return [c['id'] for c in requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()['list']]

def search_batch(tok, batch):
    """Search single batch for target"""
    r = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json={'campaigns': batch, 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15', 'groupBy': 'SKU'},
        timeout=30)
    
    if r.status_code != 200:
        return None, None
    
    uid = r.json().get('UUID')
    if not uid:
        return None, None
    
    # Wait for report (max 20 tries)
    for _ in range(20):
        time.sleep(4)
        d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
        
        if d.get('state') == 'OK' and d.get('link'):
            raw = requests.get(BASE_URL + d['link'], headers={'Authorization': f'Bearer {tok}'}, timeout=60).content
            if raw[:2] == b'PK':
                z = zipfile.ZipFile(iomod.BytesIO(raw))
                raw = z.read(z.namelist()[0])
            
            text = raw.decode('utf-8').replace('\ufeff', '')
            
            # Search in text directly
            if TARGET in text:
                return batch, text
            
            return batch, None
    
    return batch, None

# Main
tok = get_token()
camps = get_camps(tok)
print(f'Campaigns: {len(camps)}')

for i in range(0, len(camps), 10):
    batch = camps[i:i+10]
    print(f'Batch {i//10+1}: {batch[:3]}...', end=' ')
    
    found_batch, result = search_batch(tok, batch)
    
    if found_batch and result:
        print(f'\n*** FOUND in {found_batch} ***')
        
        # Parse the line with target
        lines = result.strip().split('\n')
        for line in lines:
            if TARGET in line:
                print(f'Line: {line}')
                parts = line.split(';')
                # Columns: 0=sku, 9=расход, 10=заказы, 11=продажи
                try:
                    orders = parts[10].strip() if len(parts) > 10 else '0'
                    spend = parts[9].strip() if len(parts) > 9 else '0'
                    revenue = parts[11].strip() if len(parts) > 11 else '0'
                    print(f'Orders: {orders}, Spend: {spend}, Revenue: {revenue}')
                except:
                    pass
                break
        break
    else:
        print(f'No data')
    
    time.sleep(12)

print('Done')