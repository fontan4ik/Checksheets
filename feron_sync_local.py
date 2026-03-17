import requests
import json
import time
import config
import gsheets_utils

def fetch_feron_stocks(articles):
    """
    Fetch stocks for a list of articles from Feron API in chunks.
    """
    if not articles:
        return {}

    url = f"{config.FERON_BASE_URL}/v1/stocks/list"
    headers = {
        "Content-Type": "application/json",
        "API-KEY": config.FERON_API_KEY
    }
    
    chunk_size = 500
    stock_map = {}
    
    for i in range(0, len(articles), chunk_size):
        chunk = articles[i:i + chunk_size]
        payload = {"filter": chunk}
        
        try:
            print(f"   Fetching Feron stocks chunk {i//chunk_size + 1}...")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                for item in data:
                    code = item.get("code")
                    if not code: continue
                    
                    wh_data = {"samara": 0, "vnukovo": 0, "novosibirsk": 0}
                    for stock in item.get("stocks", []):
                        wh = stock.get("warehouse")
                        qty = stock.get("stock") or 0
                        if wh in wh_data:
                            wh_data[wh] = qty
                    stock_map[code] = wh_data
            else:
                print(f"   Error fetching Feron stocks: {response.status_code} {response.text}")
        except Exception as e:
            print(f"   Exception during Feron stock fetch: {e}")
        
        time.sleep(0.5) # Be nice to API
        
    return stock_map

def sync_feron():
    print("Starting Feron Local Sync...")
    
    try:
        ws = gsheets_utils.get_worksheet(config.FERON_SHEET_NAME)
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return

    # In "ТЕСТ" sheet:
    # Column A (1): Артикул
    # Column AI (35): Ферон Самара
    # Column AJ (36): Ферон Внуково
    # Column AK (37): Ферон Новосибирск
    
    print(f"Clearing existing Feron columns in '{config.FERON_SHEET_NAME}'...")
    gsheets_utils.clear_column(ws, "Ферон Самара")
    gsheets_utils.clear_column(ws, "Ферон Внуково")
    gsheets_utils.clear_column(ws, "Ферон Новосибирск")

    articles = ws.col_values(1)[1:] # Skip header
    print(f"Found {len(articles)} articles in column A")

    # Filter out empty articles
    valid_articles = [str(a).strip() for a in articles if str(a).strip()]
    
    if not valid_articles:
        print("No articles to process.")
        return

    stock_map = fetch_feron_stocks(valid_articles)
    
    samara_results = []
    vnukovo_results = []
    novosibirsk_results = []
    
    for article in articles:
        art = str(article).strip()
        data = stock_map.get(art, {"samara": 0, "vnukovo": 0, "novosibirsk": 0})
        samara_results.append([data["samara"]])
        vnukovo_results.append([data["vnukovo"]])
        novosibirsk_results.append([data["novosibirsk"]])

    print("Updating Google Sheet...")
    try:
        gsheets_utils.update_column_by_header(ws, "Ферон Самара", samara_results)
        gsheets_utils.update_column_by_header(ws, "Ферон Внуково", vnukovo_results)
        gsheets_utils.update_column_by_header(ws, "Ферон Новосибирск", novosibirsk_results)
        print("Feron Sync completed successfully!")
    except Exception as e:
        print(f"Error updating sheet: {e}")

if __name__ == "__main__":
    sync_feron()
