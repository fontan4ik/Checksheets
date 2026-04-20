import requests
import json

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

def get_token():
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    })
    return r.json()['access_token']

def main():
    token = get_token()
    r = requests.get(f"{BASE_URL}/api/client/campaign", headers={"Authorization": f"Bearer {token}"})
    campaigns = r.json()['list']
    active = [c for c in campaigns if c.get('state') == 'CAMPAIGN_STATE_RUNNING']
    print(f"Total: {len(campaigns)}")
    print(f"Active: {len(active)}")
    for c in active[:20]:
        print(f"  {c['id']} | {c['title']}")

if __name__ == "__main__":
    main()
