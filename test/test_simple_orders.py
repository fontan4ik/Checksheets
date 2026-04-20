#!/usr/bin/env python3
"""Simple test without campaigns filter"""

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

def create_orders(tok):
    """Create report - NO campaigns filter, all"""
    body = {
        'from': '2025-04-01T00:00:00Z',
        'to': '2025-04-15T23:59:59Z'
    }
    
    r = requests.post(f'{BASE_URL}/api/client/statistic/orders/generate',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    print(f'Create: {r.status_code} - {r.text[:200]}')
    if r.status_code == 200:
        return r.json().get('UUID')
    return None

def check_status(tok, uid):
    """Check at /api/client/statistic/{UUID}"""
    url = f'{BASE_URL}/api/client/statistic/{uid}'
    
    for i in range(20):
        r = requests.get(url, headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        if r.status_code == 200:
            d = r.json()
            state = d.get('state')
            print(f'Status ({i+1}): {state}')
            
            if state == 'OK':
                link = d.get('link')
                print(f'Link: {link}')
                if link:
                    r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                    print(f'Download: {r2.status_code} - {len(r2.content)} bytes')
                    return r2.content
                return None
            elif state == 'ERROR':
                print(f'Error: {d.get("error")}')
                return None
        else:
            print(f'Status code: {r.status_code}')
        
        time.sleep(3)
    
    return None

def parse_orders(raw):
    if not raw:
        print('No raw data')
        return
    
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
        print(f'Unzipped')
    
    text = raw.decode('utf-8').replace('\ufeff', '')
    lines = text.strip().split('\n')
    print(f'Lines: {len(lines)}')
    print(f'Header: {lines[0][:300]}')
    
    # Find target SKU
    for line in lines[1:]:
        if not line.strip() or 'Всего' in line: continue
        if TARGET in line:
            print(f'\n*** FOUND: {line} ***')
            parts = line.split(';')
            for i, p in enumerate(parts):
                print(f'  {i}: {p}')
            return True
    
    print('\nTarget not found')
    for l in lines[1:10]:
        if l.strip():
            print(f'  {l[:150]}')
    return False

# Test
tok = get_tok()
print('Token OK')

uid = create_orders(tok)
print(f'UUID: {uid}')

if uid:
    raw = check_status(tok, uid)
    if raw:
        parse_orders(raw)
    else:
        print('No data downloaded')
else:
    print('Failed to create report')

print('\nDone')