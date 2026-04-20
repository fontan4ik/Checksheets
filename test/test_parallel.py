#!/usr/bin/env python3
"""Ozon Performance API - Parallel batches"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import zipfile
import concurrent.futures

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET_SKU = '1644174248'
DATE_FROM = '2025-04-01'
DATE_TO = '2025-04-15'
BATCH_SIZE = 10

results = {}

def get_token():
    print('Getting token...')
    resp = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }, timeout=30)
    token = resp.json()['access_token']
    print('Token OK')
    return token

def get_campaigns(token):
    print('Getting campaigns...')
    resp = requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {token}'}, timeout=30)
    campaigns = resp.json()['list']
    campaign_ids = [str(c['id']) for c in campaigns]
    print(f'Found {len(campaign_ids)} campaigns')
    return campaign_ids, token

def process_batch(args):
    """Process single batch"""
    batch_num, batch, token, date_from, date_to = args
    
    url = f'{BASE_URL}/api/client/statistics'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'campaigns': batch,
        'dateFrom': date_from,
        'dateTo': date_to,
        'groupBy': 'SKU'
    }
    
    print(f'Batch {batch_num}: creating report for {len(batch)} campaigns...')
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f'Batch {batch_num}: error {resp.status_code}')
            return None
        uuid = resp.json().get('UUID')
    except Exception as e:
        print(f'Batch {batch_num}: exception {e}')
        return None
    
    print(f'Batch {batch_num}: waiting for {uuid}...')
    
    for i in range(30):
        time.sleep(5)
        try:
            r = requests.get(f'{BASE_URL}/api/client/statistics/{uuid}', 
                headers={'Authorization': f'Bearer {token}'}, timeout=30)
            d = r.json()
            state = d.get('state')
            
            if state == 'OK':
                link = d.get('link', '')
                r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {token}'}, timeout=120)
                content = r2.content
                
                if content[:2] == b'PK':
                    z = zipfile.ZipFile(io.BytesIO(content))
                    csv = z.read(z.namelist()[0]).decode('utf-8')
                else:
                    csv = content.decode('utf-8')
                
                lines = csv.replace('\ufeff', '').strip().split('\n')
                print(f'Batch {batch_num}: {len(lines)} lines')
                return csv
            
            elif state == 'ERROR':
                print(f'Batch {batch_num}: error')
                return None
        except Exception as e:
            print(f'Batch {batch_num}: wait exception {e}')
    
    print(f'Batch {batch_num}: timeout')
    return None

def aggregate_results(csv_list, target_sku):
    """Aggregate all CSV results"""
    all_stats = {}
    
    for csv in csv_list:
        if not csv:
            continue
        
        lines = csv.replace('\ufeff', '').strip().split('\n')
        
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
            except:
                continue
            
            if sku not in all_stats:
                all_stats[sku] = {'orders': 0, 'spend': 0, 'revenue': 0}
            
            all_stats[sku]['orders'] += orders
            all_stats[sku]['spend'] += spend
            all_stats[sku]['revenue'] += revenue
    
    return all_stats

def main():
    print('='*60)
    print('Parallel batches test')
    print('='*60)
    
    token = get_token()
    campaign_ids, _ = get_campaigns(token)
    
    batches = [campaign_ids[i:i+BATCH_SIZE] for i in range(0, len(campaign_ids), BATCH_SIZE)]
    print(f'Created {len(batches)} batches')
    
    all_csv = []
    for i, batch in enumerate(batches):
        print(f'\nProcessing batch {i+1}/{len(batches)}...')
        csv = process_batch((i+1, batch, token, DATE_FROM, DATE_TO))
        if csv:
            all_csv.append(csv)
        
        if i < len(batches) - 1:
            time.sleep(15)
    
    print(f'\nGot {len(all_csv)} reports')
    
    all_stats = aggregate_results(all_csv, TARGET_SKU)
    print(f'Total unique SKUs: {len(all_stats)}')
    
    if TARGET_SKU in all_stats:
        data = all_stats[TARGET_SKU]
        print(f'\n*** TARGET {TARGET_SKU} ***')
        print(f'Orders: {data["orders"]}')
        print(f'Spend: {data["spend"]:.2f} RUB')
        print(f'Revenue: {data["revenue"]:.2f} RUB')
    else:
        print(f'Target not found')
    
    print('\nDone')

if __name__ == '__main__':
    main()