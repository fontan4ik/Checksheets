import requests
import json
import time

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    payload = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}
    return requests.post(url, json=payload).json().get('access_token')

def main():
    token = get_token()
    campaign_id = 24437877
    # 2026-04-14 (Yesterday)
    url = f"{BASE_URL}/api/client/statistics/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"campaigns": [campaign_id], "dateFrom": "2026-04-14", "dateTo": "2026-04-14"}
    
    print("Requesting...")
    r = requests.post(url, headers=headers, json=payload)
    print(f"Code: {r.status_code}")
    uuid = r.json().get('UUID')
    print(f"UUID: {uuid}")
    
    for _ in range(20):
        for status_type in ["statistics", "statistic"]:
            status_url = f"{BASE_URL}/api/client/{status_type}/orders/{uuid}"
            rs = requests.get(status_url, headers=headers)
            if rs.status_code == 200:
                print(f"DONE ({status_type})")
                # print first 2 lines
                import io, zipfile
                content = rs.content
                text = content.decode('utf-8-sig') if content[:2] != b'PK' else zipfile.ZipFile(io.BytesIO(content)).open(zipfile.ZipFile(io.BytesIO(content)).namelist()[0]).read().decode('utf-8-sig')
                lines = text.splitlines()
                if lines:
                    print("Headers:")
                    print(lines[0])
                    if len(lines) > 1:
                        print("First line:")
                        print(lines[1])
                    return
            else:
                pass
        print(f"Status (both): 404")
        time.sleep(10)

if __name__ == "__main__":
    main()
