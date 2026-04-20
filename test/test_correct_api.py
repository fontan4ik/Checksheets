"""
Ozon Performance API - Orders Report
Correct endpoint: POST /api/client/statistic/orders/generate
Parameters: from, to (RFC 3339 format)
No campaigns parameter - returns ALL orders
"""
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
# Reference period from Excel file: 2026-04-08 to 2026-04-14
DATE_FROM = "2026-04-08T00:00:00Z"  # RFC 3339 format
DATE_TO   = "2026-04-14T23:59:59Z"

def get_token():
    print("Getting token...", flush=True)
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    })
    r.raise_for_status()
    token = r.json()['access_token']
    print("Token OK", flush=True)
    return token

def request_report(token):
    url = f"{BASE_URL}/api/client/statistic/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Correct payload: 'from' and 'to', NO campaigns
    payload = {
        "from": DATE_FROM,
        "to": DATE_TO
    }
    print(f"Requesting report: {url}", flush=True)
    print(f"Payload: {payload}", flush=True)
    r = requests.post(url, headers=headers, json=payload)
    print(f"Response: {r.status_code} - {r.text[:300]}", flush=True)
    if r.status_code != 200:
        return None
    uuid = r.json().get('UUID')
    print(f"UUID: {uuid}", flush=True)
    return uuid

def wait_and_download(token, uuid):
    headers = {"Authorization": f"Bearer {token}"}
    status_url = f"{BASE_URL}/api/client/statistic/orders/{uuid}"
    download_url = f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}"

    print(f"Waiting for report {uuid}...", flush=True)
    for i in range(120):
        time.sleep(10)
        # Try status endpoint
        resp = requests.get(status_url, headers=headers)
        if resp.status_code == 200:
            content = resp.content
            if content[:2] == b'PK' or b';' in content[:100]:
                print(f"READY via status endpoint (attempt {i+1})!", flush=True)
                return content
            try:
                j = resp.json()
                state = j.get('state', '')
                if state == 'OK':
                    print(f"State=OK, downloading...", flush=True)
                    dr = requests.get(download_url, headers=headers)
                    return dr.content
                elif state == 'ERROR':
                    print(f"Report ERROR: {j}", flush=True)
                    return None
                elif state:
                    if (i+1) % 6 == 0:
                        print(f"  State: {state} (attempt {i+1}/120)", flush=True)
            except:
                pass
        elif resp.status_code == 404:
            if (i+1) % 6 == 0:
                print(f"  Still generating... (attempt {i+1}/120)", flush=True)
        else:
            print(f"  Unexpected status: {resp.status_code} - {resp.text[:100]}", flush=True)

    print("TIMEOUT!", flush=True)
    return None

def parse_and_sum(content):
    """
    Expected CSV columns (0-indexed):
    0: период отчёта
    1: дата
    2: ID заказа
    3: номер заказа
    4: SKU
    5: SKU продвигаемого товара
    6: артикул
    7: наименование
    8: источник заказа
    9: количество
    10: стоимость, ₽
    11: ставку, %
    12: ставку, ₽
    13: расход, ₽
    """
    if content[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            print(f"ZIP contents: {z.namelist()}", flush=True)
            text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = content.decode('utf-8-sig')

    lines = text.strip().split('\n')
    print(f"Total lines: {len(lines)}", flush=True)
    print(f"Header: {lines[0][:200]}", flush=True)

    # Print first data row to understand structure
    if len(lines) > 1:
        print(f"First data row: {lines[1][:300]}", flush=True)

    # Find header row
    header_idx = 0
    for i, line in enumerate(lines[:5]):
        if 'SKU' in line:
            header_idx = i
            break

    headers = lines[header_idx].split(';')
    print(f"\nColumn mapping:", flush=True)
    for i, h in enumerate(headers):
        print(f"  [{i}] = '{h}'", flush=True)

    # Find column indices
    sku_idx = ord_idx = rev_idx = spend_idx = -1
    for i, h in enumerate(headers):
        h_clean = h.lower().strip()
        if h_clean == 'sku': sku_idx = i
        elif 'количество' in h_clean: ord_idx = i
        elif 'стоимость' in h_clean: rev_idx = i
        elif 'расход' in h_clean: spend_idx = i

    print(f"\nFound indices: SKU={sku_idx}, qty={ord_idx}, rev={rev_idx}, spend={spend_idx}", flush=True)

    # Aggregate per SKU
    stats = {}
    for line in lines[header_idx+1:]:
        if not line.strip(): continue
        parts = line.split(';')
        if sku_idx == -1 or len(parts) <= sku_idx: continue
        sku = parts[sku_idx].strip().strip('"')
        if not sku: continue

        try:
            qty = int(parts[ord_idx].strip()) if ord_idx != -1 else 0
            rev = float(parts[rev_idx].strip().replace(',', '.')) if rev_idx != -1 else 0
            spend = float(parts[spend_idx].strip().replace(',', '.')) if spend_idx != -1 else 0
        except:
            continue

        if sku not in stats:
            stats[sku] = {'qty': 0, 'rev': 0, 'spend': 0}
        stats[sku]['qty'] += qty
        stats[sku]['rev'] += rev
        stats[sku]['spend'] += spend

    return stats

def main():
    token = get_token()
    uuid = request_report(token)
    if not uuid:
        print("Failed to get UUID")
        return

    content = wait_and_download(token, uuid)
    if not content:
        print("Failed to download report")
        return

    # Save raw file for inspection
    ext = 'zip' if content[:2] == b'PK' else 'csv'
    fname = f"orders_report.{ext}"
    with open(fname, 'wb') as f:
        f.write(content)
    print(f"\nRaw report saved to: {fname}", flush=True)

    stats = parse_and_sum(content)
    print(f"\nTotal unique SKUs: {len(stats)}", flush=True)

    print("\n" + "="*50, flush=True)
    print("RESULT FOR TARGET SKU", flush=True)
    print("="*50, flush=True)
    if TARGET_SKU in stats:
        s = stats[TARGET_SKU]
        print(f"SKU: {TARGET_SKU}", flush=True)
        print(f"Orders: {s['qty']}  (Expected: 37)", flush=True)
        print(f"Revenue: {s['rev']}  (Expected: 43860.00)", flush=True)
        print(f"Spend:   {s['spend']}  (Expected: 521.15)", flush=True)
    else:
        print(f"SKU {TARGET_SKU} NOT FOUND", flush=True)
        top = sorted(stats.items(), key=lambda x: x[1]['qty'], reverse=True)[:5]
        print("Top 5 by orders:", flush=True)
        for sku, d in top:
            print(f"  {sku}: qty={d['qty']}, rev={d['rev']}, spend={d['spend']}", flush=True)

if __name__ == "__main__":
    main()
