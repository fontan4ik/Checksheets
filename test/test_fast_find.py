#!/usr/bin/env python3
"""Fast search for target SKU in campaigns"""

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
BATCH_SIZE = 10

def get_token():
    print('Getting token...')
    resp = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }, timeout=30)
    print('Token OK')
    return resp.json()['access_token']

def get_campaigns(token):
    print('Getting campaigns...')
    resp = requests.get(f'{BASE_URL}/api/client/campaign', 
        headers={'Authorization': f'Bearer {token}'}, timeout=30)
    campaigns = resp.json()['list']
    print(f'Found {len(campaigns)} campaigns')
    return [c['id'] for c in campaigns]

def find_in_batch(token, campaign_ids, target):
    """Search for target in a batch"""
    url = f'{BASE_URL}/api/client/statistics'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'campaigns': campaign_ids,
        'dateFrom': DATE_FROM,
        'dateTo': DATE_TO,
        'groupBy': 'SKU'
    }
    
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f'Error: {resp.status_code}')
        return None
    
    uuid = resp.json().get('UUID')
    print(f'Report: {uuid}', end=' ')
    
    for i in range(25):
        time.sleep(5)
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
            print(f'{len(lines)} lines')
            
            for line in lines[1:]:
                if not line.strip():
                    continue
                if 'Всего' in line or line.startswith('sku;'):
                    continue
                
                parts = line.split(';')
                if len(parts) < 11:
                    continue
                
                sku = parts[0].strip()
                if sku == target:
                    spend = parts[8].strip() if parts[8].strip() else '0'
                    orders = parts[9].strip() if parts[9].strip() else '0'
                    revenue = parts[10].strip() if parts[10].strip() else '0'
                    print(f'\n*** FOUND! {target} ***')
                    print(f'Orders: {orders}')
                    print(f'Spend: {spend} RUB')
                    print(f'Revenue: {revenue} RUB')
                    return True
            
            return False
        
        elif state == 'ERROR':
            print(f'Error')
            return None
    
    print('Timeout')
    return None

def main():
    print('='*60)
    print(f'Fast search for SKU {TARGET_SKU}')
    print('='*60)
    
    token = get_token()
    campaigns = get_campaigns(token)
    
    batches = [campaigns[i:i+BATCH_SIZE] for i in range(0, len(campaigns), BATCH_SIZE)]
    
    for i, batch in enumerate(batches):
        print(f'\nBatch {i+1}/{len(batches)}: campaigns {batch}')
        
        result = find_in_batch(token, batch, TARGET_SKU)
        
        if result:
            print('\nTarget found! Stopping.')
            break
        
        if i < len(batches) - 1:
            time.sleep(10)
    
    print('\nDone')

if __name__ == '__main__':
    main()