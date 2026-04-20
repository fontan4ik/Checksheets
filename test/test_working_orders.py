#!/usr/bin/env python3
"""Working orders report - correct endpoints"""

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
    r = requests.get(f'{BASE_URL}/api/client/campaign', headers={'Authorization': f'Bearer {tok}'}, timeout=30)
    return [c['id'] for c in r.json()['list']]

def create_orders(tok, cids):
    """Create report - from/to as RFC 3339"""
    body = {
        'from': '2025-04-01T00:00:00Z',
        'to': '2025-04-15T23:59:59Z',
        'campaigns': cids
    }
    
    r = requests.post(f'{BASE_URL}/api/client/statistic/orders/generate',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    print(f'Create: {r.status_code}')
    if r.status_code == 200:
        return r.json().get('UUID')
    print(f'Error: {r.text}')
    return None

def check_status(tok, uid):
    """Correct status endpoint: /api/client/statistic/{UUID}"""
    url = f'{BASE_URL}/api/client/statistic/{uid}'
    
    for i in range(20):
        r = requests.get(url, headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        if r.status_code != 200:
            time.sleep(3)
            continue
        
        d = r.json()
        state = d.get('state')
        print(f'Status: {state}')
        
        if state == 'OK':
            link = d.get('link')
            if link:
                r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                return r2.content
            return None
        elif state == 'ERROR':
            print(f'Error: {d.get("error")}')
            return None
        
        time.sleep(3)
    
    return None

def parse_orders(raw):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
        print(f'Unzipped')
    
    text = raw.decode('utf-8').replace('\ufeff', '')
    lines = text.strip().split('\n')
    print(f'Total lines: {len(lines)}')
    print(f'Header: {lines[0][:250]}')
    
    hdrs = lines[0].split(';')
    print(f'\nColumns ({len(hdrs)}):')
    for i, h in enumerate(hdrs):
        print(f'  {i}: {h}')
    
    # Find target SKU
    for line in lines[1:]:
        if not line.strip() or 'Всего' in line: continue
        if TARGET in line:
            print(f'\n*** FOUND TARGET ***')
            parts = line.split(';')
            for i, p in enumerate(parts):
                print(f'  {i}: {p}')
            return True
    
    print('\nTarget not found')
    for l in lines[1:6]:
        if l.strip():
            print(f'  {l[:150]}')
    return False

# Main test
tok = get_tok()
print('Token OK')

camps = get_camps(tok)
print(f'Campaigns: {len(camps)}')

# Test with multiple campaigns (up to 10)
uid = create_orders(tok, camps[:10])
if uid:
    print(f'UUID: {uid}')
    raw = check_status(tok, uid)
    if raw:
        print(f'Downloaded {len(raw)} bytes')
        parse_orders(raw)
    else:
        print('No data')
else:
    print('Failed to create')

print('\nDone')