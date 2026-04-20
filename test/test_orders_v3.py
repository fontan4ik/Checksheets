#!/usr/bin/env python3
"""Correct orders report - /api/client/statistic/orders/generate"""

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
    """Use CORRECT endpoint: /api/client/statistic/orders/generate"""
    # RFC 3339 date format
    body = {
        'from': '2025-04-01T00:00:00Z',
        'to': '2025-04-15T23:59:59Z',
        'campaigns': cids
    }
    
    r = requests.post(f'{BASE_URL}/api/client/statistic/orders/generate',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    print(f'Create orders report: {r.status_code}')
    if r.status_code != 200:
        print(f'Error: {r.text}')
        return None
    return r.json().get('UUID')

def check_status(tok, uid):
    """Check status at /api/client/statistic/orders/status"""
    for i in range(40):
        time.sleep(5)
        r = requests.get(f'{BASE_URL}/api/client/statistic/orders/status?UUID={uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30)
        
        if r.status_code == 200:
            text = r.text.strip()
            if text.startswith('PK'):
                r2 = requests.get(f'{BASE_URL}/api/client/statistic/orders/download?UUID={uid}',
                    headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                return r2.content
            elif text.startswith('sku') or text.startswith(';'):
                return text.encode('utf-8')
            try:
                d = r.json()
                print(f'Status: {d.get("state", "unknown")}')
            except:
                pass
        elif r.status_code == 404:
            print(f'Wait {i+1}: NOT_READY')
        else:
            print(f'Status code: {r.status_code}')
    
    raise TimeoutError('Timeout')

def parse_orders(raw):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    
    text = raw.decode('utf-8').replace('\ufeff', '')
    lines = text.strip().split('\n')
    print(f'Total lines: {len(lines)}')
    print(f'Header: {lines[0][:200]}')
    
    hdrs = lines[0].split(';')
    print(f'\nColumns:')
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
            print(f'  {l[:100]}')
    return False

tok = get_tok()
camps = get_camps(tok)
print(f'Test campaigns: {camps[:3]}')

uid = create_orders_report(tok, camps[:3])
if uid:
    print(f'UUID: {uid}')
    raw = check_status(tok, uid)
    if raw:
        parse_orders(raw)
else:
    print('Failed')

print('\nDone')