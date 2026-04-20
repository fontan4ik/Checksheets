#!/usr/bin/env python3
"""Search all batches for target SKU"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

def get_tok():
    return requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30).json()['access_token']

def get_camps(tok):
    return [c['id'] for c in requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()['list']]

def create_and_wait(tok, cids):
    """Quick create and wait"""
    body = {'campaigns': cids, 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15', 'groupBy': 'SKU'}
    
    r = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    if r.status_code != 200:
        return None, None
    
    uid = r.json().get('UUID')
    
    for _ in range(20):
        time.sleep(5)
        d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
        if d.get('state') == 'OK':
            link = d.get('link')
            if link:
                raw = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120).content
                if raw[:2] == b'PK':
                    z = zipfile.ZipFile(iomod.BytesIO(raw))
                    raw = z.read(z.namelist()[0])
                return uid, raw.decode('utf-8').replace('\ufeff', '')
    
    return uid, None

def search_batch(tok, cids):
    """Check if target in batch"""
    uid, raw = create_and_wait(tok, cids)
    if not raw:
        return None, cids
    
    lines = raw.strip().split('\n')
    
    for line in lines[1:]:
        if not line.strip() or 'Всего' in line or line.startswith('sku;'):
            continue
        if TARGET in line:
            parts = line.split(';')
            print(f'\n*** FOUND {TARGET} in campaign(s) {cids} ***')
            print(f'Line: {line}')
            # Parse: columns 9=расход, 10=заказы, 11=продажи
            try:
                spend = parts[9].strip() if len(parts) > 9 else '0'
                orders = parts[10].strip() if len(parts) > 10 else '0'
                revenue = parts[11].strip() if len(parts) > 11 else '0'
                print(f'Orders: {orders}, Spend: {spend}, Revenue: {revenue}')
            except:
                pass
            return cids, uid
    
    return None, cids

tok = get_tok()
camps = get_camps(tok)
print(f'Total campaigns: {len(camps)}')

# Search in batches
for start in range(0, len(camps), 10):
    batch = camps[start:start+10]
    print(f'Checking batch {start//10+1}: {batch[:3]}...', end=' ')
    
    found, checked = search_batch(tok, batch)
    if found:
        print(f'\n*** SUCCESS: Found in {found} ***')
        break
    else:
        print(f'Not found, checked {checked}')
    
    if start + 10 < len(camps):
        time.sleep(15)

print('\nDone')