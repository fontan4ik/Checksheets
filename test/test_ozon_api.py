import requests
import json
import time
import io
import zipfile
import csv
from datetime import date, timedelta

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json().get('access_token')

def request_orders_report(token, campaign_ids, date_from, date_to):
    url = f"{BASE_URL}/api/client/statistics/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"campaigns": campaign_ids, "dateFrom": date_from, "dateTo": date_to}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json().get('UUID')

def check_status(token, uuid):
    url = f"{BASE_URL}/api/client/statistics/orders/{uuid}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 404: return "IN_PROGRESS", None
    response.raise_for_status()
    if response.content[:2] == b'PK': return "OK", response.content
    return "OK", response.content

def main():
    print("Main started")
    token = get_token()
    print("Token ok")
    print("Getting campaigns...")
    url = f"{BASE_URL}/api/client/campaign"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    print(f"Campaigns response: {resp.status_code}")
    resp.raise_for_status()
    campaigns = resp.json().get('list', [])
    print(f"Found {len(campaigns)} campaigns")
    
    target_campaign_id = None
    for c in campaigns:
        title = c.get('title', '')
        if 'Оплата за заказ' in title and 'все товары' in title:
            target_campaign_id = c.get('id')
            print(f"Target Campaign found: {title} ({target_campaign_id})")
            break
    
    if not target_campaign_id:
        print("Searching for any 'Оплата за заказ'...")
        for c in campaigns:
            if 'Оплата за заказ' in c.get('title', ''):
                target_campaign_id = c.get('id')
                print(f"Using: {c.get('title')} ({target_campaign_id})")
                break
    
    if not target_campaign_id:
        print("No campaign found. IDs available:")
        for c in campaigns[:5]: print(f" - {c.get('title')} ({c.get('id')})")
        return

    # Period: April 8 to April 14
    date_from = "2026-04-08"
    date_to = "2026-04-14"
    
    print(f"Requesting report for {date_from} to {date_to}...")
    uuid = request_orders_report(token, [target_campaign_id], date_from, date_to)
    print(f"UUID: {uuid}")
    
    for attempt in range(60):
        print(f"Check status attempt {attempt}...")
        state, content = check_status(token, uuid)
        print(f"Status: {state}")
        if state == "OK":
            print("Report ready!")
            if content and content[:2] == b'PK':
                print("ZIP detected")
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    name = z.namelist()[0]
                    with z.open(name) as f:
                        text = f.read().decode('utf-8-sig')
            elif content:
                print("CSV detected")
                text = content.decode('utf-8-sig')
            else:
                print("No content")
                break
            
            lines = text.strip().split('\n')
            print(f"Headers: {lines[0]}")
            with open('report.csv', 'w', encoding='utf-8-sig') as f:
                f.write(text)
            print("Saved report to report.csv")
            
            target_sku = "1644174248"
            total_orders = 0
            for line in lines[1:]:
                parts = line.split(';')
                if len(parts) > 10:
                    sku = parts[2].strip()
                    if sku == target_sku:
                        try:
                            orders = int(float(parts[10].replace(',', '.')))
                            total_orders += orders
                        except: pass
            
            print(f"RESULT: Total orders for SKU {target_sku} is {total_orders}")
            break
        else:
            time.sleep(5)

if __name__ == "__main__":
    main()
