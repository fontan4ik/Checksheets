#!/usr/bin/env python3
"""Ozon Performance API - Final working script"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

def get_token():
    return requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30).json()['access_token']

def get_camps(tok):
    return [c['id'] for c in requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()['list']]

def create(tok, cids):
    r = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json={'campaigns': cids, 'dateFrom': '2025-04-01', 'dateTo': '2025-04-15', 'groupBy': 'SKU'},
        timeout=30)
    return r.json().get('UUID')

def wait(tok, uid):
    for _ in range(20):
        time.sleep(5)
        d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
        if d.get('state') == 'OK' and d.get('link'):
            raw = requests.get(BASE_URL + d['link'], headers={'Authorization': f'Bearer {tok}'}, timeout=120).content
            if raw[:2] == b'PK':
                z = zipfile.ZipFile(iomod.BytesIO(raw))
                return z.read(z.namelist()[0])
            return raw
    return None

def parse(raw, stats):
    lines = raw.decode('utf-8').replace('\ufeff', '').strip().split('\n')
    for line in lines[1:]:
        if not line.strip() or 'Всего' in line or line.startswith('sku;'): continue
        p = line.split(';')
        if len(p) < 12: continue
        sku = p[0].strip()
        if not sku: continue
        try:
            spend = float(p[9].strip().replace(',', '.')) if p[9].strip() else 0.0
            orders = int(p[10].strip()) if p[10].strip() else 0
            revenue = float(p[11].strip().replace(',', '.')) if p[11].strip() else 0.0
        except: continue
        if sku not in stats: stats[sku] = {'orders':0,'spend':0.0,'revenue':0.0}
        stats[sku]['orders'] += orders
        stats[sku]['spend'] += spend
        stats[sku]['revenue'] += revenue

tok = get_token()
camps = get_camps(tok)
stats = {}

for i in range(0, min(50, len(camps)), 10):
    print(f'Batch {i//10+1}...')
    batch = camps[i:i+10]
    uid = create(tok, batch)
    if uid:
        raw = wait(tok, uid)
        if raw: parse(raw, stats)
        if TARGET in stats: break
    time.sleep(15)

if TARGET in stats:
    d = stats[TARGET]
    print(f'\n*** TARGET {TARGET}: orders={d["orders"]}, spend={d["spend"]:.2f}, revenue={d["revenue"]:.2f}')
else:
    print(f'Not found - total SKUs: {len(stats)}')

print('Done')