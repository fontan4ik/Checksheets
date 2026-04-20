#!/usr/bin/env python3
"""Full flow with longer wait and all campaigns"""

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
    """Create with campaigns - use larger period"""
    body = {
        'from': '2025-04-01T00:00:00Z',
        'to': '2025-04-16T23:59:59Z',
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
    """Wait with more attempts"""
    url = f'{BASE_URL}/api/client/statistics/{uid}'
    print(f'Waiting for: {uid}')
    
    for i in range(60):  # More attempts
        r = requests.get(url, headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        
        if r.status_code == 200:
            d = r.json()
            state = d.get('state')
            print(f'Attempt {i+1}: {state}')
            
            if state == 'OK':
                link = d.get('link')
                if link:
                    r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                    return r2.content
                return None
            elif state == 'ERROR':
                print(f'Error: {d}')
                return None
        
        time.sleep(5)  # Wait longer
    
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
    
    if len(lines) < 3:
        print(f'Header: {lines[0]}')
        print('No data rows')
        return
    
    print(f'Header: {lines[0][:200]}')
    print(f'Row 1: {lines[1][:200]}')
    
    # Find target SKU
    for line in lines[2:]:
        if not line.strip() or 'Всего' in line: continue
        if TARGET in line:
            print(f'\n*** FOUND TARGET ***')
            parts = line.split(';')
            for i, p in enumerate(parts):
                print(f'  {i}: {p}')
            return
    
    print('\nTarget not in report')

tok = get_tok()
print('Token OK')

camps = get_camps(tok)
print(f'Campaigns: {len(camps)}')

# Batch campaigns
for start in range(0, min(50, len(camps)), 10):
    batch = camps[start:start+10]
    print(f'\n=== Batch {start//10+1}: {batch} ===')
    
    uid = create_orders(tok, batch)
    if not uid:
        print('Failed to create')
        continue
    
    raw = wait_report(tok, uid)
    if raw:
        result = parse(raw)
        if result:
            break
    
    time.sleep(10)

print('\nDone')