import requests
import base64
import config

def list_rs_warehouses():
    auth_str = f"{config.RS_LOGIN}:{config.RS_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Accept": "application/json"
    }
    url = f"{config.RS_BASE_URL}/stocks"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            stocks = data.get("Stocks", [])
            print("Available RS Warehouses:")
            for s in stocks:
                print(f"ID: {s.get('ORGANIZATION_ID')}, Name: {s.get('NAME')}")
        else:
            print(f"Error fetching warehouses: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_rs_warehouses()
