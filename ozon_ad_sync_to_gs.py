import requests
import time
import zipfile
import io
import sys
import os
import gspread
from google.oauth2.service_account import Credentials

# Add project root to sys.path to import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    import config
except ImportError:
    # Fallback if scripts are run differently
    import sys; sys.path.append(os.getcwd())
    import config

sys.stdout.reconfigure(encoding='utf-8')

# Ozon Settings (from scripts)
CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

SHEET_NAME = "ТЕСТ"
# Column indices (1-indexed for Google Sheets)
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

def get_active_campaigns(token):
    print("Getting campaigns...", flush=True)
    r = requests.get(f"{BASE_URL}/api/client/campaign", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    campaigns = r.json().get('list', [])
    active = [c['id'] for c in campaigns if c.get('state') == 'CAMPAIGN_STATE_RUNNING']
    print(f"Total: {len(campaigns)}, Active: {len(active)}", flush=True)
    return active

def request_and_wait_report(token, campaign_ids, date_from, date_to):
    print(f"Requesting orders report for {len(campaign_ids)} campaigns ({date_from} to {date_to})...", flush=True)
    url = f"{BASE_URL}/api/client/statistic/orders/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"campaigns": campaign_ids, "dateFrom": date_from, "dateTo": date_to}
    
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code != 200:
        print(f"Error requesting report: {r.text}", flush=True)
        return None
    
    uuid = r.json().get('UUID')
    print(f"Report UUID: {uuid}. Waiting...", flush=True)
    
    # Wait up to 20 minutes (120 * 10s)
    for i in range(120):
        time.sleep(10)
        status_url = f"{BASE_URL}/api/client/statistic/orders/status?UUID={uuid}"
        resp = requests.get(status_url, headers=headers)
        if resp.status_code == 200:
            content = resp.content
            # Check if it's already the report or still JSON status
            if content[:2] == b'PK' or b'SKU' in content or b'sku' in content or b';' in content:
                 return content
            try:
                state = resp.json().get('state')
                if state == 'OK':
                    dl_url = f"{BASE_URL}/api/client/statistic/orders/download?UUID={uuid}"
                    dr = requests.get(dl_url, headers=headers)
                    return dr.content
                if state == 'ERROR':
                    print(f"Report generation error: {resp.json()}", flush=True)
                    return None
            except: pass
        if (i+1) % 6 == 0:
            print(f"  ...still waiting ({i+1}/120)", flush=True)
    
    print("Timeout waiting for report", flush=True)
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
    
    header_idx = -1
    for i, line in enumerate(lines[:5]):
        if 'SKU' in line.upper() and ('КОЛИЧЕСТВО' in line.upper() or 'ORDERS' in line.upper()):
            header_idx = i
            break
    if header_idx == -1: header_idx = 0
    
    headers = lines[header_idx].split(';')
    sku_idx, qty_idx, rev_idx, spend_idx = -1, -1, -1, -1
    
    for i, h in enumerate(headers):
        h = h.lower().strip()
        if h == 'sku': sku_idx = i
        elif 'количество' in h: qty_idx = i
        elif 'стоимость' in h and '₽' in h: rev_idx = i # Стоимость, ₽
        elif 'расход' in h and '₽' in h: spend_idx = i  # Расход, ₽
    
    # Fallbacks for specific names
    if rev_idx == -1:
        for i, h in enumerate(headers):
            if 'стоимость' in h.lower(): rev_idx = i
    if spend_idx == -1:
        for i, h in enumerate(headers):
            if 'расход' in h.lower(): spend_idx = i
            
    # Absolute fallbacks if still not found
    if sku_idx == -1: sku_idx = 3
    if qty_idx == -1: qty_idx = 7
    if rev_idx == -1: rev_idx = 9
    if spend_idx == -1: spend_idx = 12

    stats = {}
    for line in lines[header_idx+1:]:
        if not line or 'Всего' in line: continue
        parts = line.split(';')
        if len(parts) <= max(sku_idx, qty_idx, rev_idx, spend_idx): continue
        
        sku = parts[sku_idx].strip()
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
    print("Starting Ozon Performance Sync to Google Sheets...", flush=True)
    
    # 1. Connect to GSheets
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(config.GSHEETS_CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(config.SPREADSHEET_ID)
    ws = ss.worksheet(SHEET_NAME)
    
    # 2. Get SKUs from sheet
    all_values = ws.get_all_values()
    if not all_values:
        print("Sheet is empty!")
        return
        
    skus_in_sheet = []
    for row in all_values[1:]: # Skip header
        if len(row) >= SKU_COL:
            skus_in_sheet.append(row[SKU_COL-1].strip())
        else:
            skus_in_sheet.append("")
    
    print(f"Found {len(skus_in_sheet)} rows with SKUs in sheet.", flush=True)
    
    # 3. Get Ozon data
    token = get_token()
    active_camps = get_active_campaigns(token)
    
    # Dates: User wanted 08.04.2026 to 14.04.2026 for reference
    # Let's make it work for the last 14 days by default unless it's a specific test
    # But for the current task, I'll use the user's reference period to prove correctness.
    date_from = "2026-04-08"
    date_to = "2026-04-14"
    
    report_content = request_and_wait_report(token, active_camps, date_from, date_to)
    if not report_content:
        print("Failed to get Ozon report.")
        return
        
    stats = parse_report(report_content)
    print(f"Parsed Ozon report. Unique SKUs with data: {len(stats)}", flush=True)
    
    # 4. Prepare data for update
    col_qty = []
    col_rev = []
    col_spend = []
    
    updated_count = 0
    for sku in skus_in_sheet:
        if sku and sku in stats:
            s = stats[sku]
            col_qty.append([s['qty']])
            col_rev.append([s['rev']])
            col_spend.append([s['spend']])
            updated_count += 1
            if sku == '1644174248':
                print(f"TARGET SKU 1644174248 FOUND: Qty={s['qty']}, Rev={s['rev']}, Spend={s['spend']}", flush=True)
        else:
            col_qty.append([0])
            col_rev.append([0])
            col_spend.append([0.0])
            
    # 5. Write back to sheet
    print(f"Updating {len(skus_in_sheet)} rows in sheet...", flush=True)
    
    # Batch update for efficiency
    # Start row is 2 (after header)
    ws.update(f"BA2:BA{len(col_qty)+1}", col_qty)
    ws.update(f"BB2:BB{len(col_rev)+1}", col_rev)
    ws.update(f"BC2:BC{len(col_spend)+1}", col_spend)
    
    print(f"Done! Updated {updated_count} rows with non-zero data.", flush=True)

if __name__ == "__main__":
    main()
