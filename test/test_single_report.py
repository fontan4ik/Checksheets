#!/usr/bin/env python3
"""Ozon Performance API - Single report with all campaigns"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import zipfile
import json

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET_SKU = '1644174248'

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
    return campaign_ids

def create_report_all(token, campaign_ids):
    """Create single report for all campaigns"""
    url = f'{BASE_URL}/api/client/statistics'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'campaigns': campaign_ids,
        'dateFrom': '2025-04-01',
        'dateTo': '2025-04-15',
        'groupBy': 'SKU'
    }
    
    print(f'Creating report for {len(campaign_ids)} campaigns...')
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f'Response: {resp.status_code}')
    
    if resp.status_code != 200:
        print(f'Error: {resp.text}')
        return None
    
    return resp.json().get('UUID')

def wait_for_report(token, uuid):
    print(f'Waiting for report {uuid}...')
    url = f'{BASE_URL}/api/client/statistics/{uuid}'
    
    for i in range(40):
        time.sleep(5)
        r = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=30)
        d = r.json()
        state = d.get('state')
        print(f'Attempt {i+1}: {state}')
        
        if state == 'OK':
            link = d.get('link', '')
            r2 = requests.get(BASE_URL + link, headers={'Authorization': f'Bearer {token}'}, timeout=120)
            content = r2.content
            
            if content[:2] == b'PK':
                z = zipfile.ZipFile(io.BytesIO(content))
                csv = z.read(z.namelist()[0]).decode('utf-8')
            else:
                csv = content.decode('utf-8')
            
            return csv
        
        elif state == 'ERROR':
            print(f'Error: {d.get("error")}')
            return None
    
    print('Timeout')
    return None

def parse_report(csv, target_sku):
    """Parse CSV and find target SKU"""
    lines = csv.replace('\ufeff', '').strip().split('\n')
    print(f'Total lines: {len(lines)}')
    
    if target_sku:
        for line in lines[1:]:
            if not line.strip():
                continue
            if 'Всего' in line or line.startswith('sku;'):
                continue
            
            parts = line.split(';')
            if len(parts) < 11:
                continue
            
            sku = parts[0].strip()
            if sku == target_sku:
                spend = parts[8].strip() if len(parts) > 8 else '0'
                orders = parts[9].strip() if len(parts) > 9 else '0'
                revenue = parts[10].strip() if len(parts) > 10 else '0'
                print(f'\n*** FOUND TARGET SKU {target_sku} ***')
                print(f'Orders: {orders}')
                print(f'Spend: {spend} RUB')
                print(f'Revenue: {revenue} RUB')
                return True
    
    print('Sample data:')
    for line in lines[1:6]:
        if line.strip() and 'Всего' not in line and not line.startswith('sku;'):
            print(f'  {line[:120]}')
    
    return False

def main():
    print('='*60)
    print('Testing single report for ALL campaigns')
    print('='*60)
    
    token = get_token()
    campaign_ids = get_campaigns(token)
    
    uuid = create_report_all(token, campaign_ids)
    if not uuid:
        print('Failed to create report')
        return
    
    print(f'UUID: {uuid}')
    
    csv = wait_for_report(token, uuid)
    if csv:
        parse_report(csv, TARGET_SKU)
    else:
        print('Failed to get report')
    
    print('\nDone')

if __name__ == '__main__':
    main()