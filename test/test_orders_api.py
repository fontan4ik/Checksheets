#!/usr/bin/env python3
"""Using orders/generate endpoint - should give SKU-level data"""

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
    print(f'Token: {r.status_code}')
    return r.json()['access_token']

def get_camps(tok):
    r = requests.get(f'{BASE_URL}/api/client/campaign', headers={'Authorization': f'Bearer {tok}'}, timeout=30)
    cs = r.json()['list']
    print(f'Campaigns: {len(cs)}')
    return [c['id'] for c in cs]

def create_orders_report(tok, cids):
    """Use orders/generate endpoint"""
    r = requests.post(f'{BASE_URL}/api/client/statistics/orders/generate',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json={'campaigns': cids, 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15'},
        timeout=30)
    print(f'Create orders report: {r.status_code}')
    if r.status_code != 200:
        print(f'Error: {r.text}')
        return None
    return r.json().get('UUID')

def wait_orders(tok, uid):
    """Wait for orders report"""
    for i in range(40):
        time.sleep(5)
        r = requests.get(f'{BASE_URL}/api/client/statistics/orders/status?UUID={uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        
        if r.status_code == 200:
            text = r.text.strip()
            if text.startswith('PK'):
                # Download ZIP
                r2 = requests.get(f'{BASE_URL}/api/client/statistics/orders/download?UUID={uid}',
                    headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                return r2.content
            elif text.startswith('sku') or text.startswith(';'):
                return r.text.encode('utf-8')
        elif r.status_code == 404:
            print(f'Wait {i+1}: IN_PROGRESS')
        else:
            print(f'Status: {r.status_code}')
    
    raise TimeoutError('Timeout waiting for orders report')

def parse_orders(raw):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    
    text = raw.decode('utf-8').replace('\ufeff', '')
    lines = text.strip().split('\n')
    print(f'Total lines: {len(lines)}')
    print(f'Header: {lines[0][:150]}')
    
    # Show all columns
    hdrs = lines[0].split(';')
    print(f'Columns ({len(hdrs)}):')
    for i, h in enumerate(hdrs):
        print(f'  {i}: {h}')
    
    # Find target SKU
    for line in lines[1:]:
        if not line.strip() or 'Всего' in line: continue
        if TARGET in line:
            print(f'\n*** FOUND TARGET ***')
            print(f'Line: {line}')
            parts = line.split(';')
            for i, p in enumerate(parts):
                print(f'  {i}: {p}')
            return
    
    print('Target not found')
    # Display sample
    print('Sample:')
    for l in lines[1:6]:
        if l.strip():
            print(f'  {l[:120]}')

# Test with first 3 campaigns
tok = get_tok()
camps = get_camps(tok)
test_camps = camps[:3]
print(f'Test campaigns: {test_camps}')

uid = create_orders_report(tok, test_camps)
if uid:
    print(f'UUID: {uid}')
    raw = wait_orders(tok, uid)
    if raw:
        parse_orders(raw)
    else:
        print('No data')
else:
    print('Failed to create report')

print('\nDone')