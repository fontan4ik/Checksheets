import requests
import time
import zipfile
import io
import sys

sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

TARGET_SKU = '1644174248'
DATE_FROM = "2026-04-08"
DATE_TO = "2026-04-14"

ACTIVE_CAMPAIGNS = [24681662, 24681448, 24474366, 24437877, 24095027, 24066442, 24066108, 23391253, 23050334, 22435373, 20648768, 4511142]

def get_token():
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    })
    return r.json()['access_token']

def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    print(f"Requesting report for {len(ACTIVE_CAMPAIGNS)} active campaigns...")
    gen_url = f"{BASE_URL}/api/client/statistic/orders/generate"
    payload = {"campaigns": ACTIVE_CAMPAIGNS, "dateFrom": DATE_FROM, "dateTo": DATE_TO}
    
    r = requests.post(gen_url, headers=headers, json=payload)
    if r.status_code != 200:
        print(f"Error: {r.text}")
        return
    
    uuid = r.json().get('UUID')
    print(f"UUID: {uuid}")
    
    for i in range(120):
        print(f"Attempt {i+1}...", flush=True)
        time.sleep(10)
        status_url = f"{BASE_URL}/api/client/statistic/orders/status?UUID={uuid}"
        resp = requests.get(status_url, headers=headers)
        if resp.status_code == 200:
            content = resp.content
            if content[:2] == b'PK' or b'SKU' in content or b'sku' in content or b';' in content:
                print("READY!")
                process_report(content)
                break
            else:
                try:
                    state = resp.json().get('state')
                    if state == 'OK':
                        dl_url = f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}"
                        dr = requests.get(dl_url, headers=headers)
                        process_report(dr.content)
                        break
                except: pass
        else:
            print(f"Status: {resp.status_code}")

def process_report(content):
    if content[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = content.decode('utf-8-sig')
    
    lines = text.strip().split('\n')
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
        if p == 'sku' or p.strip() == 'sku': sku_idx = i
        elif 'количество' in p: qty_idx = i
        elif 'стоимость, ₽' in p: rev_idx = i
        elif 'расход, ₽' in p: spend_idx = i
    
    # Fallback if no ruble char in check
    if rev_idx == -1: 
        for i, p in enumerate(parts_hdr):
            if 'стоимость' in p.lower(): rev_idx = i
    if spend_idx == -1:
        for i, p in enumerate(parts_hdr):
            if 'расход' in p.lower(): spend_idx = i

    totals = {'qty': 0, 'rev': 0, 'spend': 0}
    for line in lines[header_idx+1:]:
        if not line or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) <= max(sku_idx, qty_idx, rev_idx, spend_idx): continue
        if parts[sku_idx].strip() == TARGET_SKU:
            totals['qty'] += int(parts[qty_idx].strip())
            totals['rev'] += float(parts[rev_idx].strip().replace(',', '.'))
            totals['spend'] += float(parts[spend_idx].strip().replace(',', '.'))
            
    print(f"\nRESULTS FOR {TARGET_SKU}:")
    print(f"Orders: {totals['qty']}")
    print(f"Revenue: {totals['rev']}")
    print(f"Spend: {totals['spend']}")

if __name__ == "__main__":
    main()
