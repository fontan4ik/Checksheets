#!/usr/bin/env python3
"""
Ozon Performance API - Получение рекламной статистики по заказам
For columns: BA (Реклама Количество), BB (Реклама Стоимость), BC (Реклама Расход)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import zipfile

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

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
    return [c['id'] for c in resp.json()['list']]

def create_report(token, campaign_ids, date_from, date_to):
    """Создать отчёт через /api/client/statistics с groupBy=SKU"""
    body = {
        'campaigns': campaign_ids,
        'dateFrom': date_from,
        'dateTo': date_to,
        'groupBy': 'SKU'
    }
    
    resp = requests.post(f'{BASE_URL}/api/client/statistics',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()['UUID']

def wait_for_report(token, uuid):
    """Ожидание отчёта через /api/client/statistics/{uuid}"""
    url = f'{BASE_URL}/api/client/statistics/{uuid}'
    
    for i in range(25):
        time.sleep(5)
        resp = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=30)
        if resp.status_code != 200:
            continue
        
        data = resp.json()
        state = data.get('state')
        
        if state == 'OK':
            link = data.get('link')
            if link:
                resp2 = requests.get(BASE_URL + link, 
                    headers={'Authorization': f'Bearer {token}'}, timeout=120)
                content = resp2.content
                
                if content[:2] == b'PK':
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        return zf.read(zf.namelist()[0]).decode('utf-8')
                return content.decode('utf-8')
        
        elif state == 'ERROR':
            raise Exception(f'Report error: {data}')
    
    raise TimeoutError('Timeout waiting for report')

def parse_csv_with_mapping(csv_text, all_stats):
    """Парсинг CSV и маппинг колонок:
    - SKU = column 0
    - Заказы = column 10 (index 10)
    - Продажи (выручка) = column 11 (index 11)  
    - Расход = column 9 (index 9)
    """
    lines = csv_text.replace('\ufeff', '').strip().split('\n')
    
    for line in lines[1:]:
        if not line.strip():
            continue
        if 'Всего' in line or line.startswith('sku;'):
            continue
        
        parts = line.split(';')
        if len(parts) < 12:
            continue
        
        sku = parts[0].strip()
        if not sku:
            continue
        
        try:
            spend = float(parts[9].strip().replace(',', '.')) if parts[9].strip() else 0.0
            orders = int(parts[10].strip()) if parts[10].strip() else 0
            revenue = float(parts[11].strip().replace(',', '.')) if parts[11].strip() else 0.0
        except (ValueError, IndexError):
            continue
        
        if sku not in all_stats:
            all_stats[sku] = {'orders': 0, 'spend': 0.0, 'revenue': 0.0}
        
        all_stats[sku]['orders'] += orders
        all_stats[sku]['spend'] += spend
        all_stats[sku]['revenue'] += revenue
    
    return all_stats

def main():
    target_sku = '1644174248'
    date_from = '2025-04-01'
    date_to = '2025-04-15'
    
    print(f'Target SKU: {target_sku}')
    print(f'Period: {date_from} → {date_to}')
    
    token = get_token()
    print('Token OK')
    
    campaigns = get_campaigns(token)
    print(f'Campaigns: {len(campaigns)}')
    
    all_stats = {}
    
    # Batch process - maximum 10 campaigns per request
    BATCH_SIZE = 10
    
    for start in range(0, len(campaigns), BATCH_SIZE):
        batch = campaigns[start:start + BATCH_SIZE]
        batch_num = start // BATCH_SIZE + 1
        total_batches = (len(campaigns) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f'Batch {batch_num}/{total_batches}: {batch[:3]}...')
        
        try:
            uuid = create_report(token, batch, date_from, date_to)
            csv = wait_for_report(token, uuid)
            parse_csv_with_mapping(csv, all_stats)
            
            if target_sku in all_stats:
                data = all_stats[target_sku]
                print(f'\n*** FOUND TARGET {target_sku} ***')
                print(f'Orders: {data["orders"]}')
                print(f'Spend: {data["spend"]:.2f} RUB')
                print(f'Revenue: {data["revenue"]:.2f} RUB')
                break
            
            print(f'  Processed {len(all_stats)} unique SKUs')
        
        except Exception as e:
            print(f'Batch error: {e}')
        
        if start + BATCH_SIZE < len(campaigns):
            time.sleep(20)
    
    print('\n=== FINAL RESULTS ===')
    print(f'Total unique SKUs: {len(all_stats)}')
    
    if target_sku in all_stats:
        data = all_stats[target_sku]
        print(f'\n*** TARGET SKU {target_sku} ***')
        print(f'Orders: {data["orders"]}')
        print(f'Spend: {data["spend"]:.2f} RUB')
        print(f'Revenue: {data["revenue"]:.2f} RUB')
    else:
        print(f'Target {target_sku} NOT FOUND')
        if all_stats:
            top = sorted(all_stats.items(), key=lambda x: x[1]['orders'], reverse=True)[:5]
            print('\nTop 5 by orders:')
            for sku, d in top:
                print(f'  {sku}: orders={d["orders"]}, spend={d["spend"]:.2f}')
    
    print('\nDone')

if __name__ == '__main__':
    main()