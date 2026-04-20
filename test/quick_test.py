#!/usr/bin/env python3
"""Quick verify - test with 2 campaigns only"""

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

def quick_test():
    tok = get_token()
    camps = get_camps(tok)
    
    # Test with single campaign
    for camp_id in camps[:1]:
        print(f'Testing campaign {camp_id}...')
        r = requests.post(f'{BASE_URL}/api/client/statistics',
            headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
            json={'campaigns': [camp_id], 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15', 'groupBy': 'SKU'},
            timeout=30)
        
        uid = r.json().get('UUID')
        if not uid: continue
        
        for _ in range(10):
            time.sleep(3)
            d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
                headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
            if d.get('state') == 'OK' and d.get('link'):
                raw = requests.get(BASE_URL + d['link'], headers={'Authorization': f'Bearer {tok}'}, timeout=60).content
                if raw[:2] == b'PK':
                    z = zipfile.ZipFile(iomod.BytesIO(raw))
                    raw = z.read(z.namelist()[0])
                lines = raw.decode('utf-8').replace('\ufeff', '').strip().split('\n')
                print(f'Lines: {len(lines)}')
                for l in lines:
                    if TARGET in l:
                        print(f'FOUND: {l}')
                print('Sample:', lines[1:3])
                break

quick_test()
print('Done')