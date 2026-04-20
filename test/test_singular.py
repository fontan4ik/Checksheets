import requests
import json
from datetime import date, timedelta

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    payload = {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    }
    r = requests.post(url, json=payload)
    return r.json().get('access_token')

def main():
    token = get_token()
    # Test singular endpoint
    url = f"{BASE_URL}/api/client/statistic/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"campaigns": [24437877], "dateFrom": "2026-04-08", "dateTo": "2026-04-14"}
    
    print(f"Testing singular endpoint: {url}")
    r = requests.post(url, headers=headers, json=payload)
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")
    
    uuid = r.json().get('UUID')
    if not uuid: return
    
    status_url = f"{BASE_URL}/api/client/statistic/orders/{uuid}"
    print(f"Checking status: {status_url}")
    
    import time
    for attempt in range(20):
        rs = requests.get(status_url, headers=headers)
        if rs.status_code == 200:
            if rs.content[:2] == b'PK':
                print("READY (ZIP)")
                # save and parse
                import io, zipfile
                with zipfile.ZipFile(io.BytesIO(rs.content)) as z:
                    name = z.namelist()[0]
                    with z.open(name) as f:
                        text = f.read().decode('utf-8-sig')
                print(f"Headers: {text.splitlines()[0]}")
                break
            else:
                print(f"BODY: {rs.text}")
        else:
            print(f"Code: {rs.status_code}")
        time.sleep(5)

if __name__ == "__main__":
    main()
