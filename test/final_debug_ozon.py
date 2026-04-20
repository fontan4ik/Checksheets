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
# Reference period from Excel: 08.04.2026 - 14.04.2026
DATE_FROM = "2026-04-08"
DATE_TO = "2026-04-14"

def get_token():
    url = f"{BASE_URL}/api/client/token"
    body = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}
    r = requests.post(url, json=body)
    return r.json().get('access_token')

def get_all_campaigns(token):
    url = f"{BASE_URL}/api/client/campaign"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers)
    return [c['id'] for c in r.json().get('list', [])]

def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    campaigns = get_all_campaigns(token)
    print(f"Total campaigns: {len(campaigns)}", flush=True)
    
    full_stats = {'qty': 0, 'rev': 0, 'spend': 0}
    
    batch_size = 20
    for i in range(0, len(campaigns), batch_size):
        batch = campaigns[i:i+batch_size]
        print(f"\nBatch {i//batch_size + 1}: {len(batch)} campaigns...", flush=True)
        
        gen_url = f"{BASE_URL}/api/client/statistic/orders/generate"
        payload = {"campaigns": batch, "dateFrom": DATE_FROM, "dateTo": DATE_TO}
        
        r = requests.post(gen_url, headers=headers, json=payload)
        if r.status_code != 200:
            print(f"  Error generating: {r.text}", flush=True)
            continue
            
        uuid = r.json().get('UUID')
        print(f"  UUID: {uuid}", flush=True)
        
        ready = False
        for attempt in range(40):
            status_url = f"{BASE_URL}/api/client/statistic/orders/status?UUID={uuid}"
            sr = requests.get(status_url, headers=headers)
            
            if sr.status_code == 200:
                content = sr.content
                if content[:2] == b'PK' or b'SKU' in content or b'sku' in content or b';' in content:
                    print(f"  READY at attempt {attempt+1}!", flush=True)
                    dl_url = f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}"
                    dr = requests.get(dl_url, headers=headers)
                    if dr.status_code == 200:
                        parse_csv_and_add(dr.content, full_stats)
                    ready = True
                    break
                else:
                    try:
                        state = sr.json().get('state')
                        if state == 'OK':
                             dl_url = f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}"
                             dr = requests.get(dl_url, headers=headers)
                             if dr.status_code == 200:
                                 parse_csv_and_add(dr.content, full_stats)
                             ready = True
                             break
                        elif state == 'ERROR':
                             print(f"  ERROR: {sr.json()}", flush=True)
                             break
                    except:
                        pass
            elif sr.status_code == 404:
                if (attempt + 1) % 5 == 0:
                    print(f"  ...still waiting (attempt {attempt+1})", flush=True)
            else:
                print(f"  Status code: {sr.status_code}", flush=True)
                
            time.sleep(10)
            
        if not ready:
            print(f"  Batch {i//batch_size + 1} timed out.")
            
        # Early print if target found
        print(f"  Current totals for {TARGET_SKU}: Orders={full_stats['qty']}, Rev={full_stats['rev']}, Spend={full_stats['spend']}")

    print("\n" + "="*40)
    print(f"FINAL TOTALS FOR SKU {TARGET_SKU}")
    print(f"Orders: {full_stats['qty']} (Expected: 37)")
    print(f"Revenue: {full_stats['rev']} (Expected: 43860.00)")
    print(f"Spend: {full_stats['spend']} (Expected: 521.15)")
    print("="*40)

def parse_csv_and_add(content, full_stats):
    if content[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = content.decode('utf-8-sig')
    
    lines = text.strip().split('\n')
    if not lines: return
    
    # Detect header line
    header_idx = -1
    for i, line in enumerate(lines[:5]):
        if 'SKU' in line and ('Количество' in line or 'Orders' in line):
            header_idx = i
            break
    if header_idx == -1: header_idx = 0
    
    parts_hdr = lines[header_idx].split(';')
    sku_idx = -1
    qty_idx = -1
    rev_idx = -1
    spend_idx = -1
    
    for i, p in enumerate(parts_hdr):
        p = p.lower()
        if p == 'sku': sku_idx = i
        elif 'количество' in p: qty_idx = i
        elif 'стоимость, ₽' in p: rev_idx = i
        elif 'расход, ₽' in p: spend_idx = i
    
    # Fallback if names not found (hardcoded based on typical order report structure)
    if sku_idx == -1: sku_idx = 3
    if qty_idx == -1: qty_idx = 7
    if rev_idx == -1: rev_idx = 9
    if spend_idx == -1: spend_idx = 12
    
    for line in lines[header_idx+1:]:
        if not line or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) <= max(sku_idx, qty_idx, rev_idx, spend_idx): continue
        
        if parts[sku_idx].strip() == TARGET_SKU:
            try:
                full_stats['qty'] += int(parts[qty_idx].strip())
                full_stats['rev'] += float(parts[rev_idx].strip().replace(',', '.'))
                full_stats['spend'] += float(parts[spend_idx].strip().replace(',', '.'))
            except:
                pass

if __name__ == "__main__":
    main()
