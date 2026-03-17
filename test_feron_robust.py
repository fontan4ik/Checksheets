import requests
import base64

def test_config(url_path, headers, description):
    url = f"https://clientapi.shop.feron.ru{url_path}"
    payload = {"filter": ["48546"]}
    try:
        if "stocks" in url_path:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
        else:
            response = requests.get(url, headers=headers, timeout=10)
        print(f"[{description}] {url_path} -> {response.status_code}")
        if response.status_code == 401:
            print(f"   Response headers: {response.headers}")
    except Exception as e:
        print(f"[{description}] Error: {e}")

key_b64 = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

print("--- Feron API Robust Test ---")

# Test 1: v1 vs api/v1 with B64 key
headers = {"Content-Type": "application/json", "API-KEY": key_b64, "User-Agent": ua}
test_config("/v1/stocks/list", headers, "B64 Key, UA")
test_config("/api/v1/stocks/list", headers, "B64 Key, UA, /api")

# Test 2: v1 with Decoded Key
decoded_key = base64.b64decode(key_b64).decode('utf-8')
headers["API-KEY"] = decoded_key
test_config("/v1/stocks/list", headers, "Decoded Key, UA")

# Test 3: Single product GET
test_config("/v1/products/48546", headers, "Single Product GET")
test_config("/api/v1/products/48546", headers, "Single Product GET /api")

# Test 4: Check if key should be in Authorization
headers_auth = {"Content-Type": "application/json", "Authorization": f"Bearer {key_b64}", "User-Agent": ua}
test_config("/v1/stocks/list", headers_auth, "Auth Bearer B64")
headers_auth["Authorization"] = f"Bearer {decoded_key}"
test_config("/v1/stocks/list", headers_auth, "Auth Bearer Decoded")
