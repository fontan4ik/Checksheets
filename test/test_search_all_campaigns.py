#!/usr/bin/env python3
"""Search ALL campaigns for target SKU"""

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

def parse(raw, target_found=None):
    if raw[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(raw))
        text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = raw.decode('utf-8-sig')
    
    lines = text.replace('\ufeff', '').strip().split('\n')
    print(f"  Lines: {len(lines)}")
    
    for line in lines[1:]:
        if not line.strip() or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) < 11: continue
        sku = parts[0].strip()
        if not sku: continue
        
        if sku == TARGET:
            try:
                spend = float(parts[9].replace(',', '.').strip() or 0)
                orders = int(parts[10].strip() or 0)
                revenue = float(parts[11].replace(',', '.').strip() or 0)
                print(f"\n*** FOUND {TARGET}! ***")
                print(f"Orders: {orders}")
                print(f"Revenue: {revenue:.2f}")
                print(f"Spend: {spend:.2f}")
                return True
            except:
                pass
    return False

# Search ALL campaigns
print(f"=== Searching ALL campaigns for {TARGET} ===")
print(f"Period: {DATE_FROM} -> {DATE_TO}")

tok = get_token()
camps = get_camps(tok)
print(f"Total campaigns: {len(camps)}")

found = False
for i in range(0, len(camps), 10):
    batch = camps[i:i+10]
    batch_num = i // 10 + 1
    print(f"Batch {batch_num}/{len(camps)//10 + 1}... ", end='', flush=True)
    
    uid = create(tok, batch)
    if uid:
        raw = wait(tok, uid)
        if raw:
            if parse(raw):
                found = True
                break
    
    if i % 30 == 0:
        time.sleep(3)

if not found:
    print(f"\n{TARGET} NOT FOUND in any campaign")
    print(f"Period: {DATE_FROM} -> {DATE_TO}")
    print("Possible reasons:")
    print("1. SKU not in advertising campaigns")
    print("2. Different date period")
    print("3. Campaign data deleted/archived")

print("Done")