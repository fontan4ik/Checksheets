#!/usr/bin/env python3
"""Extract from batch 9 - the one with 85 lines"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

def get_tok():
    return requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30).json()['access_token']

def get_camps(tok):
    return [str(c['id']) for c in requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()['list']]

def mk_rpt(tok, cids):
    resp = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json={'campaigns': cids, 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15', 'groupBy': 'SKU'},
        timeout=30)
    return resp.json()['UUID']

def wait4(tok, uid):
    for _ in range(30):
        time.sleep(5)
        d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
        if d.get('state') == 'OK':
            lnk = d.get('link', '')
            raw = requests.get(BASE_URL + lnk, headers={'Authorization': f'Bearer {tok}'}, timeout=120).content
            if raw[:2] == b'PK':
                z = zipfile.ZipFile(iomod.BytesIO(raw))
                return z.read(z.namelist()[0])
        elif d.get('state') == 'ERROR':
            raise Exception('Report error')
    raise TimeoutError('Timeout')

def parse(raw):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(iomod.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    lines = raw.decode('utf-8').replace('\ufeff', '').strip().split('\n')
    print(f'Lines: {len(lines)}')
    
    # Parse header to find columns
    hdr = lines[0].split(';')
    for i, h in enumerate(hdr):
        print(f'  Col {i}: {h}')
    
    # Find target SKU directly - it's in column 0
    for line in lines[1:]:
        if TARGET in line:
            print(f'FOUND: {line}')
            parts = line.split(';')
            print(f'Full: {parts}')
            return
    
    print('Target not found in this report')
    print('Sample data:')
    for l in lines[1:6]:
        print(f'  {l[:100]}')

tok = get_tok()
camps = get_camps(tok)
print(f'Campaigns 80-89 (batch 9): {camps[80:90]}')

uid = mk_rpt(tok, camps[80:90])
print(f'UUID: {uid}')
raw = wait4(tok, uid)
parse(raw)

print('\nDone')