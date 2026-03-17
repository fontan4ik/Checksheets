import requests

def test_headers(url_path, headers):
    url = f"https://clientapi.shop.feron.ru{url_path}"
    try:
        response = requests.post(url, headers=headers, json={"filter": ["48546"]}, timeout=5)
        print(f"Header {list(headers.keys())[1]}: {response.status_code}")
    except: pass

key = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"
base_headers = {"Content-Type": "application/json"}

print("Testing different header names...")
test_headers("/v1/stocks/list", {**base_headers, "api_key": key})
test_headers("/v1/stocks/list", {**base_headers, "X-Token": key})
test_headers("/v1/stocks/list", {**base_headers, "Access-Token": key})
test_headers("/v1/stocks/list", {**base_headers, "apiKey": key})
