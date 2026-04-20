#!/usr/bin/env python3
"""Test WITHOUT campaigns in request"""

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

def create_orders_no_camps(tok):
    """Create report WITHOUT campaigns filter - get all data"""
    body = {
        'from': '2025-04-01T00:00:00Z',
        'to': '2025-04-15T23:59:59Z'
    }
    
    r = requests.post(f'{BASE_URL}/api/client/statistic/orders/generate',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    print(f'Create: {r.status_code}')
    if r.status_code != 200:
        print(f'Error: {r.text}')
        return None
    return r.json().get('UUID')

def wait_for_report(tok, uid):
    """Try multiple status endpoints"""
    endpoints = [
        f'{BASE_URL}/api/client/statistic/{uid}',      # JSON status
        f'{BASE_URL}/api/client/statistics/{uid}',     # Maybe different
    ]
    
    for url in endpoints:
        print(f'Trying: {url}')
        for i in range(30):
            r = requests.get(url, headers={'Authorization': f'Bearer {tok}'}, timeout=30)
            print(f'  {i+1}: {r.status_code}')
            
            if r.status_code == 200:
                try:
                    d = r.json()
                    state = d.get('state')
                    print(f'    State: {state}')
                    
                    if state == 'OK' and d.get('link'):
                        link = d.get('link')
                        print(f'    Downloading from: {link}')
                        r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {tok}'}, timeout=120)
                        print(f'    Downloaded: {r2.status_code} - {len(r2.content)} bytes')
                        return r2.content
                except Exception as e:
                    print(f'    Parse error: {e}')
            elif r.status_code == 404:
                pass  # Continue waiting
            else:
                print(f'    Other: {r.text[:100]}')
            
            time.sleep(3)
    
    return None

def parse(raw):
    if not raw:
        print('No data')
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
            print(f'*** FOUND: {line}')
            parts = line.split(';')
            for i, p in enumerate(parts):
                print(f'  {i}: {p}')
            return
    
    print('Target not in report')

tok = get_tok()
print('Token OK')

uid = create_orders_no_camps(tok)
print(f'UUID: {uid}')

if uid:
    raw = wait_for_report(tok, uid)
    parse(raw)
else:
    print('Failed to create')

print('\nDone')