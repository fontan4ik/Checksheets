import requests
import config
import time

def diagnose_article(article):
    api_key = config.FERON_API_KEY
    base_url = config.FERON_BASE_URL
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": api_key,
    }
    
    print("=== Full catalog scan for article 55225 ===\n")
    
    products_map = {}
    search_token = ""
    
    # Scan entire catalog like the main script
    for i in range(100):
        url = f"{base_url}/offers/products/search"
        if search_token:
            payload = {"search_token": search_token}
        else:
            payload = {"size": 3000}
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            break
        
        data = response.json()
        items = data.get("items", [])
        for item in items:
            p_id = item.get("product_id")
            v_code = item.get("vendor_code")
            if p_id and v_code:
                v_code_str = str(v_code).strip()
                products_map[p_id] = v_code_str
                if v_code_str == article:
                    print(f"FOUND! product_id: {p_id}, vendor_code: {v_code_str}")
        
        new_token = data.get("search_token")
        if not new_token or new_token == search_token:
            break
        search_token = new_token
        
        if len(items) == 0:
            break
    
    print(f"\nTotal products in catalog: {len(products_map)}")
    
    # Check what we have for article 55225
    matching_products = {k: v for k, v in products_map.items() if v == article}
    print(f"Products with vendor_code = '{article}': {len(matching_products)}")
    for p_id, v_code in matching_products.items():
        print(f"  - {p_id} -> {v_code}")

# Run diagnostic
diagnose_article("55225")

print("\n" + "="*60)
print("=== Checking quantities for article 55225 ===")

api_key = config.FERON_API_KEY
base_url = config.FERON_BASE_URL
headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": api_key,
}

product_id = "73c39ade-c515-11eb-814a-b0c554fff378"

url = f"{base_url}/quantities/search"
payload = {"products_id": [product_id]}

response = requests.post(url, json=payload, headers=headers, timeout=30)

if response.status_code != 200:
    print(f"Error: {response.status_code} {response.text}")
else:
    data = response.json()
    items = data.get("items", [])
    
    warehouse_ids = {
        "67e4fb8a-6e27-11ef-96b6-a4bf0186f0c7": "Самара",
        "de099cee-372a-11ef-96b6-a4bf0186f0c7": "Внуково (Москва)",
        "ab50cafe-6e27-11ef-96b6-a4bf0186f0c7": "Новосибирск",
    }
    
    print(f"Product ID: {product_id}")
    print("\n--- Stock quantities ---")
    for item in items:
        w_id = item.get("warehouse_id")
        w_name = warehouse_ids.get(w_id, f"Unknown ({w_id})")
        qty_data = item.get("value", {})
        qty = qty_data.get("quantity", 0)
        print(f"{w_name}: {qty}")