#!/usr/bin/env python3
"""Target SKU checker - optimized & robust"""

import sys
import io
import requests
import time
import zipfile, io as io_module

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET_SKU = '1644174248'
DATE_FROM = '2025-04-01'
DATE_TO = '2025-04-15'

def get_token():
    resp = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()['access_token']

def get_campaigns(token):
    resp = requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {token}'}, timeout=30)
    resp.raise_for_status()
    return [str(c['id']) for c in resp.json()['list']]

def create_report(token, cids):
    resp = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={'campaigns': cids, 'dateFrom': DATE_FROM, 'dateTo': DATE_TO, 'groupBy': 'SKU'},
        timeout=30)
    resp.raise_for_status()
    return resp.json()['UUID']

def wait_report(token, uuid):
    for _ in range(35):
        time.sleep(5)
        r = requests.get(f'{BASE_URL}/api/client/statistics/{uuid}',
            headers={'Authorization': f'Bearer {token}'}, timeout=30)
        d = r.json()
        st = d.get('state')
        if st == 'OK':
            link = d.get('link', '')
            raw = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {token}'}, timeout=120).content
            if raw[:2] == b'PK':
                z = zipfile.ZipFile(io_module.BytesIO(raw))
                raw = z.read(z.namelist()[0])
            return raw
        elif st == 'ERROR':
            raise RuntimeError('Report error')
    raise TimeoutError('Timeout waiting report')

def analyze(raw):
    is_zip = raw[:2] == b'PK'
    if is_zip:
        z = zipfile.ZipFile(io_module.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    lines = raw.decode('utf-8').replace('\ufeff', '').strip().split('\n')
    
    s_idx = o_idx = r_idx = sp_idx = -1
    for i, h in enumerate(lines[0].split(';')):
        hl = h.lower().strip()
        if 'sku' in hl or 'артикул' in hl: s_idx = i
        elif 'заказ' in hl or hl == 'orders': o_idx = i
        elif 'выруч' in hl or 'доход' in hl or 'р' in hl or 'revenue' in hl: r_idx = i
        elif 'расход' in hl or 'cost' in hl or 'spend' in hl: sp_idx = i
    
    stats = {}
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith('Всего') or line.startswith('Total') or line.startswith('sku;'): continue
        p = line.split(';')
        if len(p) < max(s_idx, o_idx, r_idx, sp_idx) + 1: continue
        sku = p[s_idx].strip() if s_idx >= 0 else p[0].strip()
        if not sku: continue
        try:
            orders = int(p[o_idx].strip()) if o_idx >= 0 else 0
            revenue = float(p[r_idx].strip().replace(',', '.')) if r_idx >= 0 else 0.0
            spend = float(p[sp_idx].strip().replace(',', '.')) if sp_idx >= 0 else 0.0
        except: continue
        if sku not in stats: stats[sku] = {'orders':0,'revenue':0.0,'spend':0.0}
        stats[sku]['orders'] += orders
        stats[sku]['revenue'] += revenue
        stats[sku]['spend'] += spend
    return stats

def main():
    print(f'Searching for SKU {TARGET_SKU}...')
    token = get_token()
    all_camps = get_campaigns(token)
    
    found = None
    for i in range(0, len(all_camps), 10):
        batch = all_camps[i:i+10]
        print(f'Requesting batch {i//10+1}: {batch}')
        try:
            uuid = create_report(token, batch)
            print(f'  UUID: {uuid}')
            csv = wait_report(token, uuid)
            stats = analyze(csv)
            if TARGET_SKU in stats:
                found = stats[TARGET_SKU]
                print(f'\n*** FOUND TARGET {TARGET_SKU} ***')
                print(f'Orders: {found["orders"]}')
                print(f'Spend: {found["spend"]:.2f} RUB')
                print(f'Revenue: {found["revenue"]:.2f} RUB')
                break
            else:
                print(f'  SKU not in this batch ({len(stats)} unique SKUs)')
        except Exception as e:
            print(f'  Batch failed: {e}')
        if i+10 < len(all_camps): time.sleep(15)
    
    if not found:
        print(f'\n*** TARGET {TARGET_SKU} NOT FOUND ***')
        print('Stats would be aggregated here')
    
    print('\nTest complete.')

if __name__ == '__main__':
    main()