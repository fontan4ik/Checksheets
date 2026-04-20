import requests
import sys

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    payload = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"}
    return requests.post(url, json=payload).json().get('access_token')

def main():
    token = get_token()
    uuid = "2564ccc0-dc4f-4713-88e1-447db857034f"
    # url = f"{BASE_URL}/api/client/statistics/orders/{uuid}"
    url = f"{BASE_URL}/api/client/statistic/orders/{uuid}"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        content = r.content
        if content[:2] == b'PK':
            import io, zipfile
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                name = z.namelist()[0]
                text = z.open(name).read().decode('utf-8-sig')
            print("Headers:")
            print(text.splitlines()[0])
            print("\nFirst data row:")
            print(text.splitlines()[1])
            
            # Save for inspection
            with open('final_report.csv', 'w', encoding='utf-8-sig') as f:
                f.write(text)
        else:
            print(f"Body: {r.text}")

if __name__ == "__main__":
    main()
