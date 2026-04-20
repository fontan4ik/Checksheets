import requests
import sys

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

UUID = 'e3785894-b0e2-40eb-8118-bcbe25b44d3d' # Current live UUID

def get_token():
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    })
    return r.json()['access_token']

def main():
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Try the one without 'status?UUID='
    url = f"{BASE_URL}/api/client/statistic/orders/{UUID}"
    print(f"Checking {url}...")
    r = requests.get(url, headers=headers)
    print(f"Status color code: {r.status_code}")
    print(f"Content: {r.text[:500]}")

if __name__ == "__main__":
    main()
