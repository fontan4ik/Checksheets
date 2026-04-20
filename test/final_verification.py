import requests
import time
import json
import zipfile
import io
import sys

# Set encoding for output
sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = "https://api-performance.ozon.ru"

TARGET_SKU = '1644174248'
DATE_FROM = "2026-04-08"
DATE_TO = "2026-04-14"

def get_token():
    url = f"{BASE_URL}/api/client/token"
    body = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    response = requests.post(url, json=body)
    if response.status_code != 200:
        return None
    return response.json().get('access_token')

def get_campaigns(token):
    url = f"{BASE_URL}/api/client/campaign"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return None
    return [c['id'] for c in response.json().get('list', [])]

def generate_report(token, campaign_ids):
    url = f"{BASE_URL}/api/client/statistics/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "campaigns": campaign_ids,
        "dateFrom": DATE_FROM,
        "dateTo": DATE_TO
    }
    response = requests.post(url, headers=headers, json=body)
    if response.status_code != 200:
        print(f"Error generating for {len(campaign_ids)} campaigns: {response.text}")
        return None
    return response.json().get('UUID')

def wait_for_report(token, uuid):
    status_url = f"{BASE_URL}/api/client/statistics/orders/status?UUID={uuid}"
    headers = {"Authorization": f"Bearer {token}"}
    
    for _ in range(30):
        time.sleep(10)
        resp = requests.get(status_url, headers=headers)
        if resp.status_code == 200:
            content = resp.content
            if content[:2] == b'PK' or b'SKU' in content or b'sku' in content or b';' in content:
                # Ready
                return uuid
            try:
                state = resp.json().get('state')
                if state == 'OK': return uuid
                if state == 'ERROR': return None
            except:
                pass
        elif resp.status_code == 404:
            pass # still generating
    return None

def download_report(token, uuid):
    url = f"{BASE_URL}/api/client/statistics/orders/download?UUID={uuid}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.content
    return None

def parse_csv(content, all_stats):
    if content[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            csv_text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        csv_text = content.decode('utf-8-sig')
    
    lines = csv_text.strip().split('\n')
    if not lines: return
    
    headers = lines[0].split(';')
    sku_idx = -1
    qty_idx = -1
    price_idx = -1
    spend_idx = -1
    
    for i, h in enumerate(headers):
        h = h.lower()
        if h == 'sku': sku_idx = i
        elif 'количество' in h: qty_idx = i
        elif 'стоимость, ₽' in h: price_idx = i
        elif 'расход, ₽' in h: spend_idx = i
    
    if sku_idx == -1: return # Invalid CSV
    
    for line in lines[1:]:
        if not line or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) <= sku_idx: continue
        
        sku = parts[sku_idx].strip()
        if not sku: continue
        
        try:
            qty = int(parts[qty_idx].strip()) if qty_idx != -1 else 0
            price = float(parts[price_idx].strip().replace(',', '.')) if price_idx != -1 else 0
            spend = float(parts[spend_idx].strip().replace(',', '.')) if spend_idx != -1 else 0
        except:
            continue
            
        if sku not in all_stats:
            all_stats[sku] = {'qty': 0, 'price': 0, 'spend': 0}
        
        all_stats[sku]['qty'] += qty
        all_stats[sku]['price'] += price
        all_stats[sku]['spend'] += spend

def main():
    print("Main started...", flush=True)
    token = get_token()
    if not token:
        print("Failed to get token", flush=True)
        return
    print("Token obtained.", flush=True)
    
    campaign_ids = get_campaigns(token)
    if not campaign_ids:
        print("No campaigns found", flush=True)
        return
    
    print(f"Found {len(campaign_ids)} campaigns. Processing in batches of 50...", flush=True)
    
    all_stats = {}
    batch_size = 50
    for i in range(0, len(campaign_ids), batch_size):
        batch = campaign_ids[i:i+batch_size]
        print(f"Batch {i//batch_size + 1}: requesting report for {len(batch)} campaigns...", flush=True)
        
        uuid = generate_report(token, batch)
        if not uuid: 
            print("  Failed to generate report UUID", flush=True)
            continue
        
        print(f"  UUID: {uuid}. Waiting for report...", flush=True)
        ready_uuid = wait_for_report(token, uuid)
        if ready_uuid:
            print("  Report ready. Downloading...", flush=True)
            content = download_report(token, ready_uuid)
            if content:
                print("  Parsing CSV...", flush=True)
                parse_csv(content, all_stats)
                print(f"  Processed. Current SKUs in memory: {len(all_stats)}", flush=True)
        else:
            print(f"  Report {uuid} timed out or failed.", flush=True)
            
        if TARGET_SKU in all_stats:
            s = all_stats[TARGET_SKU]
            print(f"  -> {TARGET_SKU} current sum: Qty={s['qty']}, Price={s['price']}, Spend={s['spend']}", flush=True)
    
    print("\n" + "="*40)
    print("FINAL RESULTS")
    print("="*40)
    if TARGET_SKU in all_stats:
        s = all_stats[TARGET_SKU]
        print(f"SKU: {TARGET_SKU}")
        print(f"Orders: {s['qty']} (Expected: 37)")
        print(f"Revenue: {s['price']} (Expected: 43860.00)")
        print(f"Spend: {s['spend']} (Expected: 521.15)")
    else:
        print(f"SKU {TARGET_SKU} not found in any campaign.")
    print("="*40)

if __name__ == "__main__":
    main()
