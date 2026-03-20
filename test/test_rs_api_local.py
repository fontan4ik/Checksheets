import requests
import base64

def test_rs_api():
    login = "ntc-es1"
    password = "4XK69YO0"
    base_url = "https://cdis.russvet.ru/rs"
    
    # Create Basic Auth header
    auth_str = f"{login}:{password}"
    encoded_auth = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    endpoints = [
        ("Stocks", f"{base_url}/stocks"),
        ("Residue All", f"{base_url}/residue/all/96?page=1&rows=5")
    ]

    for name, url in endpoints:
        print(f"Testing {name}: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Status Code: {response.status_code}")
            if response.status_code == 200:
                print("Success!")
                print(f"Response (first 500 chars): {response.text[:500]}")
            else:
                print(f"Error Body: {response.text[:500]}")
        except Exception as e:
            print(f"Request failed: {e}")
        print("-" * 20)

if __name__ == "__main__":
    test_rs_api()
