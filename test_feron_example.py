import requests

def test_exact_example():
    url = "https://clientapi.shop.feron.ru/api/v1/products/list"
    key = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"
    headers = {
        "API-KEY": key,
        "Content-Type": "application/json"
    }
    payload = {}
    print(f"Testing Example 1: {url}")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_exact_example()
