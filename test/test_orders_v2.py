import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import zipfile

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = "https://api-performance.ozon.ru"

TARGET_SKU = '1644174248'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    body = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    print("Getting token...")
    response = requests.post(url, json=body)
    print(f"Token: {response.status_code}")
    if response.status_code != 200:
        print(response.text)
        return None
    return response.json().get('access_token')

def get_campaigns(token):
    url = f"{BASE_URL}/api/client/campaign"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Campaigns: {response.status_code}")
        return None
    return response.json().get('list', [])

def try_endpoints(token, campaign_ids, date_from, date_to):
    endpoints = [
        ("/api/client/statistics/all_sku_promo/orders/generate", {"timeBounds": {"from": date_from, "to": date_to}}),
        ("/api/client/statistics/orders/generate", {"campaigns": campaign_ids, "dateFrom": date_from, "dateTo": date_to}),
    ]

    for endpoint, body in endpoints:
        url = BASE_URL + endpoint
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        print(f"\nTrying: {endpoint}")
        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            print(f"  Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                uuid = data.get('UUID')
                if uuid:
                    print(f"  SUCCESS! UUID: {uuid}")
                    return uuid, endpoint.replace('/generate', '')
        except Exception as e:
            print(f"  Error: {e}")
    return None, None

def get_status(token, uuid, base_endpoint):
    urls_to_try = [
        f"{BASE_URL}{base_endpoint}/status?UUID={uuid}",
        f"{BASE_URL}/api/client/statistics/report?UUID={uuid}",
        f"{BASE_URL}/api/client/statistics/orders/status?UUID={uuid}",
    ]
    
    for url in urls_to_try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"  Status URL: {url}")
            print(f"    Response: {response.status_code} - {response.text[:200]}")
            if response.status_code == 200:
                text = response.text.strip()
                if text.startswith('PK') or text.startswith('sku') or text.startswith(';'):
                    return "OK"
                try:
                    data = response.json()
                    return data.get('state', 'IN_PROGRESS')
                except:
                    pass
            elif response.status_code == 404:
                continue
        except Exception as e:
            print(f"  Error: {e}")
            continue
    
    return "NOT_FOUND"

def download(token, uuid, base_endpoint):
    urls = [
        f"{BASE_URL}{base_endpoint}/download?UUID={uuid}",
        f"{BASE_URL}/api/client/statistics/report?UUID={uuid}&download=1",
        f"{BASE_URL}/api/client/statistics/orders/download?UUID={uuid}",
    ]
    
    for url in urls:
        headers = {"Authorization": "Bearer {token}"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200 and len(response.content) > 0:
                return response.content
        except:
            continue
    
    return None

def parse(content):
    is_zip = content[:2] == b'PK'
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            csv = zf.read(zf.namelist()[0]).decode('utf-8')
    else:
        csv = content.decode('utf-8')

    lines = csv.replace('\ufeff', '').strip().split('\n')
    print(f"Lines: {len(lines)}")
    print(f"Header: {lines[0][:200]}")

    headers = lines[0].split(';')
    sku_idx = next((i for i, h in enumerate(headers) if h.lower().strip() == 'sku'), 0)

    stats = {}
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith('Total'):
            continue
        parts = line.split(';')
        sku = parts[sku_idx].strip() if sku_idx < len(parts) else parts[0].strip()
        if not sku:
            continue
        stats[sku] = True

    print(f"Unique SKUs: {len(stats)}")

    if TARGET_SKU in stats:
        print(f"\n*** TARGET SKU {TARGET_SKU} FOUND! ***")
    else:
        print(f"\n*** TARGET SKU {TARGET_SKU} NOT FOUND ***")
        print(f"Available: {list(stats.keys())[:5]}")

    return stats

def main():
    print("=" * 50)
    print("TESTING ALL ORDERS ENDPOINTS")
    print("=" * 50)

    token = get_token()
    if not token:
        return

    campaigns = get_campaigns(token)
    if not campaigns:
        return

    print(f"Campaigns: {len(campaigns)}")

    test_ids = [c['id'] for c in campaigns[:3]]
    date_from = "2026-04-01"
    date_to = "2026-04-15"

    uuid, base_endpoint = try_endpoints(token, test_ids, date_from, date_to)
    if not uuid:
        print("\nNo endpoint worked!")
        return

    print(f"\nWaiting for report...")
    for i in range(20):
        time.sleep(5)
        status = get_status(token, uuid, base_endpoint)
        print(f"  Attempt {i+1}: {status}")
        if status == "OK":
            content = download(token, uuid, base_endpoint)
            if content:
                print(f"Downloaded: {len(content)} bytes")
                parse(content)
            return
        elif status == "ERROR":
            print("Error!")
            return

    print("Timeout")

if __name__ == "__main__":
    main()
