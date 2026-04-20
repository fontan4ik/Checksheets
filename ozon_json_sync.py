import requests
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

# RFC 3339 dates as in doc
DATE_FROM = "2026-04-08T00:00:00Z"
DATE_TO   = "2026-04-14T23:59:59Z"

TARGET_SKU = '1644174248'

def get_token():
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    }, timeout=30)
    return r.json()['access_token']

def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Request JSON report
    url = f"{BASE_URL}/api/client/statistic/orders/generate/json"
    payload = {"from": DATE_FROM, "to": DATE_TO}
    
    print(f"Requesting JSON report for period {DATE_FROM} to {DATE_TO}...", flush=True)
    r = requests.post(url, headers=headers, json=payload)
    print(f"Response: {r.status_code} - {r.text}", flush=True)
    
    if r.status_code != 200:
        if 'Превышен лимит активных запросов' in r.text:
             print("Wait! Active request limit exceeded. We must wait or find the current UUID.")
        return

    uuid = r.json().get('UUID')
    print(f"UUID: {uuid}", flush=True)
    
    # Poll status
    # Note: doc doesn't specify status endpoint for JSON, assuming same as CSV
    for i in range(120):
        time.sleep(15)
        # Try both endpoints to check status
        sr = requests.get(f"{BASE_URL}/api/client/statistic/orders/status?UUID={uuid}", headers=headers)
        if sr.status_code == 404:
             if (i+1) % 4 == 0:
                 print(f"  Attempt {i+1}: still generating (404)...", flush=True)
             continue
        
        if sr.status_code == 200:
             # Check if it's JSON content
             try:
                 obj = sr.json()
                 if isinstance(obj, list):
                      print("READY! Received JSON data.")
                      process_json(obj)
                      return
                 state = obj.get('state')
                 if state == 'OK':
                      print("Ready! Downloading...")
                      dr = requests.get(f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}", headers=headers)
                      if dr.status_code == 200:
                           process_json(dr.json())
                           return
                 elif state == 'ERROR':
                      print(f"Error: {obj}")
                      return
             except:
                  pass
    
    print("Timeout")

def process_json(data):
    # data is list of objects
    totals = {'qty': 0, 'rev': 0, 'spend': 0}
    found = False
    for item in data:
        sku = str(item.get('sku', ''))
        if sku == TARGET_SKU:
            found = True
            totals['qty'] += int(item.get('quantity', 0))
            totals['rev'] += float(item.get('cost', 0)) # стоимость, ₽
            totals['spend'] += float(item.get('spent', 0)) # расход, ₽
    
    if found:
        print("\n" + "="*40)
        print(f"DATA FOR SKU {TARGET_SKU}:")
        print(f"Orders (Qty): {totals['qty']}")
        print(f"Revenue (Cost): {totals['rev']}")
        print(f"Spend (Spent): {totals['spend']}")
        print("="*40)
    else:
        print(f"SKU {TARGET_SKU} not found in this report.")
        if data:
             print(f"Sample SKUs in report: {[item.get('sku') for item in data[:10]]}")

if __name__ == "__main__":
    main()
