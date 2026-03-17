import requests
import base64

key = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"
url = "https://clientapi.shop.feron.ru/v1/stocks/list"

# Try Basic Auth using key as username
auth_str = f"{key}:"
encoded_auth = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
headers = {"Authorization": f"Basic {encoded_auth}", "Content-Type": "application/json"}

try:
    response = requests.post(url, headers=headers, json={"filter": ["48546"]}, timeout=5)
    print(f"Basic Auth (Key:): {response.status_code}")
except: pass

# Try Basic Auth using key as is
headers = {"Authorization": f"Basic {key}", "Content-Type": "application/json"}
try:
    response = requests.post(url, headers=headers, json={"filter": ["48546"]}, timeout=5)
    print(f"Basic Auth (Raw): {response.status_code}")
except: pass
