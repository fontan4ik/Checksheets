#!/usr/bin/env python3
"""Test known batch that had data: batch 9 campaigns"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

# From test_fast_find output - batch 9 = campaigns 80-89
BATCH9 = ['14668810', '14668709', '14572872', '14347967', '14326724', '14273493', '14273430', '14204373', '14187440', '14181643']

def get_token():
    return requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30).json()['access_token']

def test():
    tok = get_token()
    print(f'Testing batch 9: {BATCH9}')
    
    r = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json={'campaigns': BATCH9, 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15', 'groupBy': 'SKU'},
        timeout=30)
    print(f'Create: {r.status_code}')
    
    uid = r.json().get('UUID')
    if not uid: print('No UUID'); return
    
    print(f'UUID: {uid}')
    
    for i in range(15):
        time.sleep(3)
        d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
        print(f'Attempt {i+1}: {d.get("state")}')
        
        if d.get('state') == 'OK' and d.get('link'):
            raw = requests.get(BASE_URL + d['link'], headers={'Authorization': f'Bearer {tok}'}, timeout=60).content
            if raw[:2] == b'PK':
                z = zipfile.ZipFile(iomod.BytesIO(raw))
                raw = z.read(z.namelist()[0])
            
            lines = raw.decode('utf-8').replace('\ufeff', '').strip().split('\n')
            print(f'Lines: {len(lines)}')
            
            # Check for target SKU
            for line in lines:
                if TARGET in line:
                    print(f'\n*** FOUND TARGET {TARGET}! ***')
                    print(line)
                    return
            
            # Show all unique SKUs to see if present
            skus = [l.split(';')[0] for l in lines[2:] if l.strip() and not l.startswith('Всего')]
            print(f'All SKU IDs: {len(skus)}')
            print(f'Sample: {skus[:5]}')
            return
    
    print('Timeout')

test()
print('Done')