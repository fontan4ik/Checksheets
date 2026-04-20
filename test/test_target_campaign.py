import requests
import time
import json
import zipfile
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = "https://api-performance.ozon.ru"

TARGET_SKU = '1644174248'
DATE_FROM = "2026-04-08"
DATE_TO = "2026-04-14"
CAMPAIGN_ID = 24437877 # "Оплата за заказ - все товары"

def get_token():
    url = f"{BASE_URL}/api/client/token"
    body = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}
    r = requests.post(url, json=body)
    return r.json().get('access_token')

def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    print(f"Requesting report for campaign {CAMPAIGN_ID}...")
    url = f"{BASE_URL}/api/client/statistics/orders/generate"
    payload = {"campaigns": [CAMPAIGN_ID], "dateFrom": DATE_FROM, "dateTo": DATE_TO}
    
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code != 200:
        print(f"Error: {r.text}")
        return
    
    uuid = r.json().get('UUID')
    print(f"UUID: {uuid}")
    
    for i in range(20):
        print(f"Attempt {i+1}...", flush=True)
        time.sleep(10)
        status_url = f"{BASE_URL}/api/client/statistics/orders/status?UUID={uuid}"
        resp = requests.get(status_url, headers=headers)
        if resp.status_code == 200:
            content = resp.content
            if content[:2] == b'PK':
                print("READY!")
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    text = z.read(z.namelist()[0]).decode('utf-8-sig')
                
                lines = text.strip().split('\n')
                headers = lines[0].split(';')
                print(f"Headers: {headers}")
                
                sku_idx = headers.index('SKU') if 'SKU' in headers else -1
                qty_idx = -1
                for i, h in enumerate(headers):
                    if 'Количество' in h: qty_idx = i
                
                # Let's find columns by order if names are mangled
                # Usually: [0] Date, [1] Order ID, [2] Order Num, [3] SKU, [4] Promo SKU, [5] Articul, [6] Name, [7] Qty, [8] Price, [9] Revenue, [10] Rate%, [11] Rate RUB, [12] Spend
                # Based on Excel analysis: SKU is [3], Qty is [7], Revenue [9], Spend [12] (Wait, Spend is sometimes last)
                
                # Print sample
                for line in lines[1:]:
                    if TARGET_SKU in line:
                        print(f"Found line: {line}")
                
                total_qty = 0
                total_rev = 0
                total_spend = 0
                
                for line in lines[1:]:
                    if not line or 'Всего' in line: continue
                    parts = line.split(';')
                    if len(parts) < 13: continue
                    
                    if parts[3].strip() == TARGET_SKU:
                        try:
                            qty = int(parts[7].strip())
                            rev = float(parts[9].strip().replace(',', '.'))
                            # Spend might be shifted if there are more columns
                            # Based on Excel row count (13 cols):
                            # [3] SKU, [7] Qty, [9] Revenue, [12] Spend
                            spend = float(parts[12].strip().replace(',', '.'))
                            
                            total_qty += qty
                            total_rev += rev
                            total_spend += spend
                        except Exception as e:
                            print(f"Parse error on line: {e}")
                            
                print(f"\nAGGREGATED for SKU {TARGET_SKU}:")
                print(f"Orders: {total_qty}")
                print(f"Revenue: {total_rev}")
                print(f"Spend: {total_spend}")
                break
        else:
            print(f"Status: {resp.status_code}")

if __name__ == "__main__":
    main()
