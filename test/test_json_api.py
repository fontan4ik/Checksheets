import requests
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

DATE_FROM = "2026-04-14T00:00:00Z"
DATE_TO   = "2026-04-14T23:59:59Z"

def get_token():
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    })
    return r.json()['access_token']

def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Try JSON version for one day
    url = f"{BASE_URL}/api/client/statistic/orders/generate/json"
    payload = {"from": DATE_FROM, "to": DATE_TO}
    
    print(f"Requesting JSON report for {DATE_FROM}...", flush=True)
    r = requests.post(url, headers=headers, json=payload)
    print(f"Response: {r.status_code} - {r.text}", flush=True)
    
    if r.status_code == 200:
        uuid = r.json().get('UUID')
        print(f"UUID: {uuid}", flush=True)
        # Check status
        for i in range(20):
            time.sleep(10)
            sr = requests.get(f"{BASE_URL}/api/client/statistic/orders/{uuid}", headers=headers)
            print(f"Attempt {i+1} status: {sr.status_code}", flush=True)
            if sr.status_code == 200:
                print("READY!", flush=True)
                print(f"Content length: {len(sr.content)}", flush=True)
                # If it's JSON, print first 200 chars
                try:
                    print(sr.json()[:2] if isinstance(sr.json(), list) else sr.json())
                except:
                    print(sr.text[:200])
                break

if __name__ == "__main__":
    main()
