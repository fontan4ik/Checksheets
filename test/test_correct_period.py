#!/usr/bin/env python3
"""Quick test with CORRECT period (2025)"""

import io
import requests
import time
import zipfile

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET = '1644174248'
DATE_FROM = '2025-04-01'
DATE_TO = '2025-04-15'

def get_token():
    r = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30)
    return r.json()['access_token']

def get_camps(tok):
    return [c['id'] for c in requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()['list']]

def create(tok, cids):
    r = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json={'campaigns': cids, 'dateFrom': DATE_FROM, 'dateTo': DATE_TO, 'groupBy': 'SKU'},
        timeout=30)
    return r.json().get('UUID')

def wait(tok, uid):
    for _ in range(25):
        time.sleep(5)
        d = requests.get(f'{BASE_URL}/api/client/statistics/{uid}',
            headers={'Authorization': f'Bearer {tok}'}, timeout=30).json()
        if d.get('state') == 'OK' and d.get('link'):
            return requests.get(BASE_URL + d['link'], headers={'Authorization': f'Bearer {tok}'}, timeout=60).content
    return None

def parse(raw, stats):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(raw))
        text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = raw.decode('utf-8-sig')
    
    for line in text.replace('\ufeff', '').strip().split('\n')[1:]:
        if not line.strip() or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) < 11: continue
        sku = parts[0].strip()
        if not sku: continue
        try:
            spend = float(parts[9].replace(',', '.').strip() or 0)
            orders = int(parts[10].strip() or 0)
            revenue = float(parts[11].replace(',', '.').strip() or 0)
        except: continue
        if orders > 0 or revenue > 0 or spend > 0:
            if sku not in stats: stats[sku] = {'orders':0,'spend':0,'revenue':0}
            stats[sku]['orders'] += orders
            stats[sku]['spend'] += spend
            stats[sku]['revenue'] += revenue

# Test with CORRECT period
print(f"=== Testing period {DATE_FROM} -> {DATE_TO} ===")
print(f"Expected for {TARGET}: orders=37, revenue=43860, spend=521.15")

tok = get_token()
camps = get_camps(tok)
print(f"Campaigns: {len(camps)}")

stats = {}
for i in range(0, min(30, len(camps)), 10):  # First 3 batches only for quick test
    batch = camps[i:i+10]
    print(f"Batch {i//10+1}...")
    uid = create(tok, batch)
    raw = wait(tok, uid)
    if raw:
        parse(raw, stats)
        if TARGET in stats:
            t = stats[TARGET]
            print(f"\n*** FOUND {TARGET}! ***")
            print(f"Orders: {t['orders']}")
            print(f"Revenue: {t['revenue']:.2f}")
            print(f"Spend: {t['spend']:.2f}")
            break
    time.sleep(3)

if TARGET in stats:
    t = stats[TARGET]
    print(f"\n=== RESULT for {TARGET} ===")
    print(f"Orders: {t['orders']} (expected: 37)")
    print(f"Revenue: {t['revenue']:.2f} (expected: 43860)")
    print(f"Spend: {t['spend']:.2f} (expected: 521.15)")
else:
    print(f"\n{TARGET} NOT FOUND in first 30 campaigns")
    print(f"Total unique SKUs with data: {len(stats)}")
    if stats:
        top = sorted(stats.items(), key=lambda x: x[1]['orders'], reverse=True)[:5]
        print("Top 5:")
        for sku, d in top:
            print(f"  {sku}: orders={d['orders']}, spend={d['spend']:.2f}")

print("Done")