#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика: показываем реальную структуру CSV из /api/client/statistic/orders
и ищем SKU 1644174248 чтобы проверить колонки.
"""
import sys
import io
import zipfile
import requests
import time
import json

sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET_SKU = '1644174248'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    payload = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}
    r = requests.post(url, json=payload)
    r.raise_for_status()
    return r.json().get('access_token')

def get_campaigns(token):
    url = f"{BASE_URL}/api/client/campaign"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    campaigns = r.json().get('list', [])
    # Найти "Оплата за заказ - все товары"
    for c in campaigns:
        title = c.get('title', '')
        print(f"  Campaign: {c.get('id')} | {title} | {c.get('state')}")
        if 'Оплата за заказ' in title and 'все товары' in title:
            print(f"  --> TARGET: {c.get('id')}")
    return campaigns

def request_orders_report(token, campaign_ids, date_from, date_to):
    # Правильный endpoint (singular: statistic, без s)
    url = f"{BASE_URL}/api/client/statistic/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"campaigns": campaign_ids, "dateFrom": date_from, "dateTo": date_to}
    print(f"\nPOST {url}")
    print(f"Payload: {json.dumps(payload)}")
    r = requests.post(url, headers=headers, json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}")
    r.raise_for_status()
    return r.json().get('UUID')

def wait_and_download(token, uuid):
    url = f"{BASE_URL}/api/client/statistic/orders/{uuid}"
    headers = {"Authorization": f"Bearer {token}"}
    print(f"\nWaiting for report {uuid}...")
    for attempt in range(60):
        r = requests.get(url, headers=headers)
        print(f"  Attempt {attempt+1}: status={r.status_code}, content_len={len(r.content)}, first_bytes={r.content[:4]}")
        if r.status_code == 200:
            if r.content[:2] == b'PK':
                print("  --> READY (ZIP)")
                return r.content
            else:
                try:
                    j = r.json()
                    state = j.get('state', '')
                    print(f"  --> JSON state: {state}, full: {str(j)[:200]}")
                    if state == 'OK':
                        return r.content
                    elif state == 'ERROR':
                        print("ERROR state!")
                        return None
                except:
                    print(f"  --> Raw text: {r.text[:200]}")
        elif r.status_code == 404:
            print("  --> 404, still generating...")
        time.sleep(5)
    print("TIMEOUT!")
    return None

def analyze_csv(content):
    """Анализ структуры CSV файла"""
    if content[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            print(f"\nZIP contents: {names}")
            with z.open(names[0]) as f:
                text = f.read().decode('utf-8-sig')
    else:
        text = content.decode('utf-8-sig')
    
    lines = text.strip().split('\n')
    print(f"\nTotal lines: {len(lines)}")
    
    # Показываем первые 5 строк полностью
    print("\n=== FIRST 5 LINES ===")
    for i, line in enumerate(lines[:5]):
        parts = line.split(';')
        print(f"\n--- Line {i} ({len(parts)} cols) ---")
        for j, part in enumerate(parts):
            print(f"  [{j}] = '{part}'")
    
    # Ищем строки с нашим SKU
    print(f"\n=== ROWS WITH SKU {TARGET_SKU} ===")
    found = False
    for i, line in enumerate(lines):
        if TARGET_SKU in line:
            found = True
            parts = line.split(';')
            print(f"\nLine {i} ({len(parts)} cols):")
            for j, part in enumerate(parts):
                print(f"  [{j}] = '{part}'")
    
    if not found:
        print(f"SKU {TARGET_SKU} NOT FOUND in CSV!")
        print("\nSearching for any line with orders > 0:")
        for i, line in enumerate(lines[:5]):
            if i == 0:
                continue  # skip header
            parts = line.split(';')
            # Print first few lines anyway
            print(f"  Line {i}: {line[:150]}")

if __name__ == '__main__':
    try:
        print("=== TOKEN ===")
        token = get_token()
        print("OK")

        print("\n=== CAMPAIGNS ===")
        campaigns = get_campaigns(token)
        
        # Берём только кампанию "Оплата за заказ - все товары"
        target = None
        for c in campaigns:
            title = c.get('title', '')
            if 'Оплата за заказ' in title and 'все товары' in title:
                target = c
                break
        
        if not target:
            print("Target campaign not found! Using first RUNNING campaign.")
            for c in campaigns:
                if c.get('state') == 'CAMPAIGN_STATE_RUNNING':
                    target = c
                    break
        
        if not target:
            print("No campaigns found!")
            sys.exit(1)
        
        print(f"\nUsing campaign: {target['id']} - {target['title']}")
        
        # Период: апрель 8-14 (прошлая неделя)
        date_from = "2026-04-08"
        date_to = "2026-04-14"
        
        print(f"\n=== REQUESTING REPORT {date_from} -> {date_to} ===")
        uuid = request_orders_report(token, [target['id']], date_from, date_to)
        print(f"UUID: {uuid}")
        
        if not uuid:
            print("No UUID returned!")
            sys.exit(1)
        
        content = wait_and_download(token, uuid)
        if not content:
            print("Failed to download report!")
            sys.exit(1)
        
        # Сохраняем сырой файл
        with open('orders_raw.zip' if content[:2] == b'PK' else 'orders_raw.csv', 'wb') as f:
            f.write(content)
        print("\nRaw file saved.")
        
        analyze_csv(content)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
