import http.client
import json

def test_feron_exact_case():
    conn = http.client.HTTPSConnection("clientapi.shop.feron.ru")
    key = "ZjA5MDg3MTAtNjQ5ZS00ODU5LWJjNjktY2NkY2E1ZDdlNjUx"
    payload = json.dumps({"filter": ["48546"]})
    
    headers = {
        "Content-Type": "application/json",
        "API-KEY": key
    }
    
    print(f"Testing exact header case 'API-KEY' with provided key...")
    conn.request("POST", "/v1/stocks/list", payload, headers)
    response = conn.getresponse()
    print(f"Status: {response.status}, Reason: {response.reason}")
    print(f"Response: {response.read().decode()}")
    
    # Try decoded too
    decoded_key = "f0908710-649e-4859-bc69-ccdca5d7e651"
    headers["API-KEY"] = decoded_key
    print(f"\nTesting exact header case 'API-KEY' with decoded key...")
    conn.request("POST", "/v1/stocks/list", payload, headers)
    response = conn.getresponse()
    print(f"Status: {response.status}, Reason: {response.reason}")
    print(f"Response: {response.read().decode()}")

if __name__ == "__main__":
    test_feron_exact_case()
