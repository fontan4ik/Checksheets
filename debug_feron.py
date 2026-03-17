import requests
import config

def test_feron_api():
    url = f"{config.FERON_BASE_URL}/v1/stocks/list"
    headers = {
        "Content-Type": "application/json",
        "API-KEY": config.FERON_API_KEY
    }
    payload = {"filter": ["48546", "38269"]}
    
    print(f"Testing Feron API with key: {config.FERON_API_KEY[:10]}...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Response:")
            print(response.json())
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_feron_api()
