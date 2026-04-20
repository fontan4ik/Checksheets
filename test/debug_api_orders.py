import requests
import time
import io
import zipfile

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

def test_orders_report():
    token = get_token()
    
    # Get campaigns
    camp_url = f"{BASE_URL}/api/client/campaign"
    headers = {"Authorization": f"Bearer {token}"}
    camps = requests.get(camp_url, headers=headers).json().get('list', [])
    campaign_ids = [c['id'] for c in camps if 'Оплата за заказ' in c.get('title', '')]
    
    if not campaign_ids:
        campaign_ids = [c['id'] for c in camps[:5]]

    print(f"Campaigns: {campaign_ids}")

    # Request report
    url = f"{BASE_URL}/api/client/statistics/orders/generate"
    payload = {
        "campaigns": campaign_ids,
        "dateFrom": "2026-04-08",
        "dateTo": "2026-04-14"
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    uuid = resp.json().get('UUID')
    print(f"UUID: {uuid}")
    
    # Wait
    for i in range(20):
        report_url = f"{BASE_URL}/api/client/statistics/orders/{uuid}"
        r = requests.get(report_url, headers=headers)
        if r.status_code == 200:
            if r.content[:2] == b'PK':
                print("Got ZIP report")
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    name = z.namelist()[0]
                    with z.open(name) as f:
                        content = f.read().decode('utf-8-sig')
            else:
                print("Got CSV report")
                content = r.content.decode('utf-8-sig')
            
            lines = content.strip().split('\n')
            print(f"Total lines: {len(lines)}")
            if len(lines) > 0:
                print("Header:")
                print(lines[0])
                # Find SKU 1644174248
                count = 0
                target_sku = "1644174248"
                for line in lines[1:]:
                    if target_sku in line:
                        print(f"Match: {line}")
                        count += 1
                print(f"Total matches for {target_sku}: {count}")
            break
        print("Waiting...")
        time.sleep(5)

if __name__ == "__main__":
    test_orders_report()
