#!/usr/bin/env python3
"""Full flow: create with campaigns, check at /api/client/statistics/{UUID}"""

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
    """Create with campaigns"""
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
    print(f'Error: {r.text[:200]}')
    return None

def wait_report(tok, uid):
    """Use /api/client/statistics/{uuid} (with 's')"""
    url = f'{BASE_URL}/api/client/statistics/{uid}'
    print(f'Checking: {url}')
    
    for i in range(30):
        r = requests.get(url, headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        
        if r.status_code == 200:
            d = r.json()
            state = d.get('state')
            print(f'  {i+1}: {state}')
            
            if state == 'OK':
                link = d.get('link')
                print(f'    Link: {link}')
                if link:
                    r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                    return r2.content
                return None
        else:
            print(f'  {i+1}: {r.status_code}')
        
        time.sleep(3)
    
    return None

def parse(raw):
    if not raw:
        print('No data')
        return
    
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    
    text = raw.decode('utf-8').replace('\ufeff', '')
    lines = text.strip().split('\n')
    print(f'Lines: {len(lines)}')
    print(f'Header: {lines[0][:300]}')
    
    # Print all lines to see content
    for i, line in enumerate(lines):
        print(f'{i}: {line[:150]}')

tok = get_tok()
print('Token OK')

camps = get_camps(tok)
print(f'Campaigns: {len(camps)}')

# Try with multiple campaigns - up to 10 (API limit)
test_camps = camps[:10]
print(f'Testing with: {test_camps}')

uid = create_orders(tok, test_camps)
print(f'UUID: {uid}')

if uid:
    raw = wait_report(tok, uid)
    parse(raw)

print('\nDone')