#!/usr/bin/env python3
"""Ozon Performance API - Aggregate orders report from all campaigns"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import zipfile

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET_SKU = '1644174248'
DATE_FROM = '2025-04-01'
DATE_TO = '2025-04-15'
BATCH_SIZE = 5
MAX_WAIT_ATTEMPTS = 25
WAIT_INTERVAL = 6

def get_token():
    """Get OAuth token"""
    print('Getting token...')
    resp = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }, timeout=30)
    resp.raise_for_status()
    token = resp.json()['access_token']
    print(f'Token OK')
    return token

def get_campaigns(token):
    """Get all campaigns"""
    print('Getting campaigns...')
    resp = requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {token}'}, timeout=30)
    resp.raise_for_status()
    campaigns = resp.json()['list']
    print(f'Found {len(campaigns)} campaigns')
    return [c['id'] for c in campaigns]

def create_report(token, campaign_ids, date_from, date_to):
    """Create statistics report"""
    url = f'{BASE_URL}/api/client/statistics'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'campaigns': campaign_ids,
        'dateFrom': date_from,
        'dateTo': date_to,
        'groupBy': 'SKU'
    }
    
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f'Error creating report: {resp.status_code} - {resp.text}')
        return None
    return resp.json().get('UUID')

def wait_and_download(token, uuid):
    """Wait for report and download"""
    url = f'{BASE_URL}/api/client/statistics/{uuid}'
    
    for attempt in range(MAX_WAIT_ATTEMPTS):
        time.sleep(WAIT_INTERVAL)
        r = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=30)
        d = r.json()
        state = d.get('state')
        
        if state == 'OK':
            link = d.get('link', '')
            r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {token}'}, timeout=60)
            content = r2.content
            
            if content[:2] == b'PK':
                z = zipfile.ZipFile(io.BytesIO(content))
                csv = z.read(z.namelist()[0]).decode('utf-8')
            else:
                csv = content.decode('utf-8')
            
            return csv
        
        elif state == 'ERROR':
            print(f'Report error: {d.get("error")}')
            return None
    
    print('Timeout waiting for report')
    return None

def parse_csv(csv, all_stats):
    """Parse CSV and aggregate stats"""
    lines = csv.replace('\ufeff', '').strip().split('\n')
    print(f'  Parsing {len(lines)} lines...')
    
    for line in lines[1:]:
        if not line.strip():
            continue
        if 'Всего' in line or line.startswith('sku;'):
            continue
        
        parts = line.split(';')
        if len(parts) < 11:
            continue
        
        sku = parts[0].strip()
        if not sku:
            continue
        
        try:
            spend = float(parts[8].strip().replace(',', '.')) if parts[8].strip() else 0
            orders = int(parts[9].strip()) if parts[9].strip() else 0
            revenue = float(parts[10].strip().replace(',', '.')) if parts[10].strip() else 0
        except (ValueError, IndexError):
            continue
        
        if sku not in all_stats:
            all_stats[sku] = {'orders': 0, 'spend': 0, 'revenue': 0}
        
        all_stats[sku]['orders'] += orders
        all_stats[sku]['spend'] += spend
        all_stats[sku]['revenue'] += revenue
    
    return all_stats

def main():
    print('='*60)
    print(f'Ozon Performance API - Aggregate Report')
    print(f'Target SKU: {TARGET_SKU}')
    print(f'Period: {DATE_FROM} → {DATE_TO}')
    print('='*60)
    
    token = get_token()
    campaigns = get_campaigns(token)
    
    if not campaigns:
        print('No campaigns found!')
        return
    
    all_stats = {}
    total_batches = (len(campaigns) + BATCH_SIZE - 1) // BATCH_SIZE
    
    print(f'\nProcessing {len(campaigns)} campaigns in {total_batches} batches...')
    
    for batch_num in range(total_batches):
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(campaigns))
        batch = campaigns[start_idx:end_idx]
        
        print(f'\nBatch {batch_num+1}/{total_batches}: campaigns {start_idx+1}-{end_idx}')
        
        uuid = create_report(token, batch, DATE_FROM, DATE_TO)
        if not uuid:
            print(f'  Failed to create report, waiting...')
            time.sleep(30)
            continue
        
        print(f'  UUID: {uuid}')
        
        csv = wait_and_download(token, uuid)
        if csv:
            parse_csv(csv, all_stats)
            print(f'  Total unique SKUs so far: {len(all_stats)}')
            
            if TARGET_SKU in all_stats:
                data = all_stats[TARGET_SKU]
                print(f'  *** TARGET FOUND! orders={data["orders"]}, spend={data["spend"]:.2f}, revenue={data["revenue"]:.2f}')
        else:
            print(f'  Report not ready')
        
        if batch_num < total_batches - 1:
            print(f'  Waiting before next batch...')
            time.sleep(20)
    
    print('\n' + '='*60)
    print('FINAL RESULTS')
    print('='*60)
    
    if TARGET_SKU in all_stats:
        data = all_stats[TARGET_SKU]
        print(f'\n*** TARGET SKU {TARGET_SKU} ***')
        print(f'Orders: {data["orders"]}')
        print(f'Spend: {data["spend"]:.2f} RUB')
        print(f'Revenue: {data["revenue"]:.2f} RUB')
    else:
        print(f'\n*** TARGET SKU {TARGET_SKU} NOT FOUND ***')
        print(f'Total unique SKUs: {len(all_stats)}')
        
        if all_stats:
            top = sorted(all_stats.items(), key=lambda x: x[1]['orders'], reverse=True)[:10]
            print('\nTop 10 by orders:')
            for sku, data in top:
                print(f'  {sku}: orders={data["orders"]}, spend={data["spend"]:.2f}, revenue={data["revenue"]:.2f}')
    
    print('\nDone')

if __name__ == '__main__':
    main()