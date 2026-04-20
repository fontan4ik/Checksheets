#!/usr/bin/env python3
"""Get data from batch 9 which had 85 lines - use /api/client/statistics (not orders)"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

def get_tok():
    r = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30)
    return r.json()['access_token']

def get_camps(tok):
    return [c['id'] for c in requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()['list']]

def create_report(tok, cids):
    """Use /api/client/statistics with groupBy=SKU"""
    body = {
        'campaigns': cids,
        'dateFrom': '2025-04-01',
        'dateTo': '2025-04-15',
        'groupBy': 'SKU'
    }
    
    r = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    print(f'Create: {r.status_code}')
    if r.status_code == 200:
        return r.json().get('UUID')
    return None

def wait_report(tok, uid):
    """Get from /api/client/statistics/{uuid}"""
    for i in range(25):
        time.sleep(5)
        r = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        if r.status_code == 200:
            d = r.json()
            state = d.get('state')
            if state == 'OK':
                link = d.get('link')
                if link:
                    r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                    return r2.content
        elif d.get('state') == 'ERROR':
            print(f'Error')
            return None
    return None

def parse(raw):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    
    text = raw.decode('utf-8').replace('\ufeff', '')
    lines = text.strip().split('\n')
    print(f'Lines: {len(lines)}')
    
    print(f'Header: {lines[0]}')
    print()
    
    # Print all lines with full content to see columns
    for i, line in enumerate(lines):
        if line.strip():
            print(f'Line {i}: {line}')

tok = get_tok()
camps = get_camps(tok)

# Exact batch 9 from test_fast_find output: campaigns 80-89
batch9 = camps[80:90]  # ['14668810', '14668709', '14572872', '14347967', '14326724', '14273493', '14273430', '14204373', '14187440', '14181643']
print(f'Batch 9: {batch9}')

uid = create_report(tok, batch9)
print(f'UUID: {uid}')

if uid:
    raw = wait_report(tok, uid)
    if raw:
        parse(raw)

print('\nDone')