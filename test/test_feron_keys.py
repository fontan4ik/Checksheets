import requests
import base64

def test_key(key, description):
    url = "https://clientapi.shop.feron.ru/v1/stocks/list"
    headers = {
        "Content-Type": "application/json",
        "API-KEY": key
    }
    payload = {"filter": ["48546"]}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        print(f"[{description}] Key: {key} -> Status: {response.status_code}")
        if response.status_code == 200:
            print(f"   Success! Data: {response.json()[:1]}")
            return True
    except Exception as e:
        print(f"[{description}] Error: {e}")
    return False

# 1. The key exactly as provided (likely encoded)
provided_key = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"

# 2. Decoded key
decoded_key = base64.b64decode(provided_key).decode('utf-8')

# 3. Decoded key without the possible extra '1' at the end
# f0908710-649e-4859-bc69-ccdca55d7e651 -> 37 chars
# last part should be 12 chars: ccdca55d7e65
stripped_key = decoded_key[:-1] if len(decoded_key) == 37 else decoded_key

print(f"Decoded key: {decoded_key}")
print(f"Stripped key: {stripped_key}")

test_key(provided_key, "Provided (B64)")
test_key(decoded_key, "Decoded (UTF-8)")
test_key(stripped_key, "Stripped (UTF-8)")
test_key(provided_key, "X-API-KEY header") # with X-API-KEY

# Test with X-API-KEY
url = "https://clientapi.shop.feron.ru/v1/stocks/list"
payload = {"filter": ["48546"]}
try:
    response = requests.post(url, headers={"Content-Type": "application/json", "X-API-KEY": provided_key}, json=payload)
    print(f"[X-API-KEY Provided] Status: {response.status_code}")
    response = requests.post(url, headers={"Content-Type": "application/json", "X-API-KEY": decoded_key}, json=payload)
    print(f"[X-API-KEY Decoded] Status: {response.status_code}")
except: pass
