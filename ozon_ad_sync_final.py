import requests
import time
import zipfile
import io
import sys
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    import config
except ImportError:
    import sys; sys.path.append(os.getcwd())
    import config

sys.stdout.reconfigure(encoding='utf-8')

# Ozon Performance API Settings
CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

SHEET_NAME = "ТЕСТ"
SKU_COL = 22 # V
QTY_COL = 53 # BA
REV_COL = 54 # BB
SPEND_COL = 55 # BC

def get_token():
    print("Getting Ozon token...", flush=True)
    r = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    })
    r.raise_for_status()
    return r.json()['access_token']

def request_orders_report(token, date_from, date_to):
    """
    As per doc: POST /api/client/statistic/orders/generate
    Payload: {"from": "RFC3339", "to": "RFC3339"}
    """
    print(f"Requesting orders report from {date_from} to {date_to}...", flush=True)
    url = f"{BASE_URL}/api/client/statistic/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "from": date_from,
        "to": date_to
    }
    
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code != 200:
        print(f"Error requesting report: {r.text}", flush=True)
        return None
    
    uuid = r.json().get('UUID')
    print(f"Report UUID: {uuid}.", flush=True)
    return uuid

def wait_for_report(token, uuid, max_wait_seconds=3600):
    """
    Ozon order reports are notoriously slow. We wait up to 1 hour by default.
    """
    print(f"Waiting for report {uuid} (max {max_wait_seconds//60} min)...", flush=True)
    headers = {"Authorization": f"Bearer {token}"}
    status_url = f"{BASE_URL}/api/client/statistic/orders/status?UUID={uuid}"
    download_url = f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}"
    
    start_time = time.time()
    attempt = 0
    
    while time.time() - start_time < max_wait_seconds:
        attempt += 1
        time.sleep(30) # Poll every 30 seconds
        
        # Check status
        resp = requests.get(status_url, headers=headers)
        
        # Handle 404 as IN_PROGRESS based on Ozon реклама V2.gs logic
        if resp.status_code == 404:
            if attempt % 4 == 0:
                elapsed = int(time.time() - start_time)
                print(f"  ...still generating ({elapsed//60} min elapsed)", flush=True)
            continue
            
        if resp.status_code == 200:
            content = resp.content
            # If it's ZIP or CSV directly (sometimes status returns content)
            if content[:2] == b'PK' or b';' in content[:100]:
                print(f"READY! Received content directly.", flush=True)
                return content
            
            try:
                state = resp.json().get('state')
                if state == 'OK':
                    print("Status OK, downloading report...", flush=True)
                    dr = requests.get(download_url, headers=headers)
                    if dr.status_code == 200:
                        return dr.content
                elif state == 'ERROR':
                    print(f"Report ERROR: {resp.json()}", flush=True)
                    return None
            except:
                pass
                
    print(f"Timeout reached after {max_wait_seconds//60} min.", flush=True)
    return None

def parse_report(content):
    if not content: return {}
    if content[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = content.decode('utf-8-sig')
    
    lines = text.strip().split('\n')
    if not lines: return {}
    
    # Header indices based on user snippet:
    # 4: SKU, 7: количество, 10: стоимость, 13: расход
    header_idx = -1
    for i, line in enumerate(lines[:5]):
        if 'SKU' in line.upper():
            header_idx = i
            break
    if header_idx == -1: header_idx = 0
    
    headers = lines[header_idx].split(';')
    sku_idx, qty_idx, rev_idx, spend_idx = -1, -1, -1, -1
    
    for i, h in enumerate(headers):
        h_low = h.lower().strip()
        if h_low == 'sku': sku_idx = i
        elif 'количество' in h_low: qty_idx = i
        elif 'стоимость' in h_low: rev_idx = i
        elif 'расход' in h_low: spend_idx = i
    
    # Final fallbacks to indices from doc
    if sku_idx == -1: sku_idx = 4
    if qty_idx == -1: qty_idx = 9 # quantity is 10th col (index 9)
    if rev_idx == -1: rev_idx = 10 # revenue is 11th col (index 10)
    if spend_idx == -1: spend_idx = 13 # spend is 14th col (index 13)

    stats = {}
    for line in lines[header_idx+1:]:
        if not line or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) <= max(sku_idx, qty_idx, rev_idx, spend_idx): continue
        
        sku = parts[sku_idx].strip().strip('"')
        if not sku: continue
        
        try:
            qty = int(parts[qty_idx].strip())
            rev = float(parts[rev_idx].strip().replace(',', '.'))
            spend = float(parts[spend_idx].strip().replace(',', '.'))
            
            if sku not in stats:
                stats[sku] = {'qty': 0, 'rev': 0, 'spend': 0}
            stats[sku]['qty'] += qty
            stats[sku]['rev'] += rev
            stats[sku]['spend'] += spend
        except: continue
        
    return stats

def main():
    print("="*60)
    print("OZON PERFORMANCE ORDERS SYNC STARTS")
    print("="*60, flush=True)
    
    # 1. Connect to GSheets
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(config.SPREADSHEET_ID)
    ws = ss.worksheet(SHEET_NAME)
    
    # 2. Get SKUs from sheet
    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        print("Sheet is empty or only header found!")
        return
        
    skus_in_sheet = []
    for row in all_values[1:]:
        sku = row[SKU_COL-1].strip() if len(row) >= SKU_COL else ""
        skus_in_sheet.append(sku)
    
    print(f"Sheet loaded. Rows to process: {len(skus_in_sheet)}", flush=True)
    
    # 3. Ozon API calls
    try:
        token = get_token()
        
        # Period: Last 7 days + today
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        # Format for Ozon RFC 3339
        date_from = start_date.strftime("%Y-%m-%dT00:00:00Z")
        date_to = end_date.strftime("%Y-%m-%dT23:59:59Z")
        
        # Request report (This report covers ALL campaigns)
        uuid = request_orders_report(token, date_from, date_to)
        if not uuid: return
        
        # Wait (Poll with long timeout)
        report_content = wait_for_report(token, uuid, max_wait_seconds=1800) # 30 min
        if not report_content:
            print("FAILED: Could not retrieve report from Ozon. Try running again later.")
            return
            
        stats = parse_report(report_content)
        print(f"Ozon data retrieved. Found {len(stats)} unique SKUs in report.", flush=True)
        
        # 4. Update worksheet
        col_qty, col_rev, col_spend = [], [], []
        updated = 0
        
        for sku in skus_in_sheet:
            if sku and sku in stats:
                s = stats[sku]
                col_qty.append([s['qty']])
                col_rev.append([s['rev']])
                col_spend.append([s['spend']])
                updated += 1
            else:
                col_qty.append([0])
                col_rev.append([0])
                col_spend.append([0.0])
        
        print(f"Preparing batch update for {len(skus_in_sheet)} rows...", flush=True)
        # Update columns BA, BB, BC starting from row 2
        last_row = len(skus_in_sheet) + 1
        ws.update(f"BA2:BA{last_row}", col_qty)
        ws.update(f"BB2:BB{last_row}", col_rev)
        ws.update(f"BC2:BC{last_row}", col_spend)
        
        print(f"\nSUCCESS! Updated {updated} rows with active ad data.", flush=True)
        
        # Target SKU validation if available
        target = '1644174248'
        if target in stats:
            s = stats[target]
            print(f"Target SKU {target}: Qty={s['qty']}, Rev={s['rev']}, Spend={s['spend']}")
            
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    main()
