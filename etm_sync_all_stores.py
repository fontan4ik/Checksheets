# -*- coding: utf-8 -*-
import sys
import time
import re
import requests
import gspread
import logging
import config
import gsheets_utils

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(r"c:\AI\Работа Voltmir\1с\sync_all_stores.log", encoding='utf-8', mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)

def normalize(s):
    if not s: return ""
    s = str(s).strip()
    s = re.sub(r'\(.*\)', '', s)
    s = re.sub(r'[^A-Z0-9]', '', s.upper())
    return s

def sync_all_stores():
    logging.info("--- STARTING ALL STORES ETM SYNC ---")
    start_time = time.time()
    headers = {"Accept": "application/json"}
    
    session = None
    for attempt in range(3):
        try:
            logging.info(f"Logging into ETM (Attempt {attempt+1}/3)...")
            params = {'log': config.ETM_LOGIN, 'pwd': config.ETM_PASSWORD}
            r_login = requests.post("https://ipro.etm.ru/api/v1/user/login", params=params, headers=headers, timeout=30)
            r_login.raise_for_status()
            session = r_login.json()['data']['session']
            break
        except Exception as e:
            logging.warning(f"Login attempt {attempt+1} failed: {e}")
            if attempt < 2: time.sleep(5)
            
    if not session:
        logging.error("Could not obtain session.")
        return

    try:
        # Get all stores
        stores_url = f"https://ipro.etm.ru/api/v1/user/stores?session-id={session}"
        all_stores = []
        try:
            r_stores = requests.get(stores_url, headers=headers, timeout=30)
            if r_stores.status_code == 200:
                rows = r_stores.json().get('data', {}).get('rows', [])
                for s in rows:
                    all_stores.append({'id': s['id'], 'name': s['StoreName']})
        except: pass
        
        logging.info(f"Found {len(all_stores)} stores")
        
        if not all_stores:
            all_stores = [
                {'id': 13, 'name': 'РЦ Самара'},
                {'id': 17, 'name': 'Самара ОП'},
                {'id': 18, 'name': 'Самара ОП 2'},
                {'id': 1, 'name': 'Основной'},
                {'id': 2, 'name': 'Москва'},
                {'id': 3, 'name': 'СПб'},
            ]
            logging.info(f"Using fallback stores: {[s['id'] for s in all_stores]}")
        
        # Aggregate remains from ALL stores
        total_etm_lookup = {}
        tail_lookup = {}
        
        for s in all_stores:
            sid = s['id']
            sname = s['name']
            logging.info(f"Fetching remains for store {sid} ({sname})...")
            rem_url = f"https://ipro.etm.ru/api/v1/goods/remains?store={sid}&session-id={session}"
            try:
                r_rem = requests.get(rem_url, headers=headers, timeout=60)
                if r_rem.status_code == 200:
                    items = r_rem.json().get('data', {}).get('rows', [])
                    logging.info(f"  Got {len(items)} items")
                    for item in items:
                        gds = normalize(item.get('GdsCode'))
                        raw_art = item.get('Article', '')
                        art = normalize(raw_art)
                        try: stock = int(float(item.get('RemInfo', 0)))
                        except: stock = 0
                        
                        if stock <= 0: continue
                        
                        if gds: total_etm_lookup[gds] = total_etm_lookup.get(gds, 0) + stock
                        if art: total_etm_lookup[art] = total_etm_lookup.get(art, 0) + stock
                        
                        match = re.search(r'(\d+)$', str(raw_art).strip())
                        if match:
                            tail = match.group(1)
                            if len(tail) >= 4:
                                tail_lookup[tail] = tail_lookup.get(tail, 0) + stock
            except Exception as e:
                logging.error(f"  Error store {sid}: {e}")

        logging.info(f"Unique ETM articles: {len(total_etm_lookup)}, Tails: {len(tail_lookup)}")
        
        # Column R = index 17, Column S = index 18
        r_idx = 17
        s_idx = 18
        
        # Get worksheet
        ws = gsheets_utils.get_worksheet("ETM TR")
        all_data = ws.get_all_values()
        row_count = len(all_data) - 1  # без заголовка
        
        # Match by column B (articles in sheet)
        results_r = []
        results_s = []
        matched = 0
        
        for row in all_data[1:]:
            gs_val = row[1] if len(row) > 1 else ""  # Column B
            norm_gs = normalize(gs_val)
            
            stock = total_etm_lookup.get(norm_gs, 0)
            if stock == 0 and norm_gs in tail_lookup:
                stock = tail_lookup[norm_gs]
            
            # Find original article from ETM
            etm_article = ""
            if norm_gs in total_etm_lookup:
                etm_article = norm_gs
                for k in total_etm_lookup.keys():
                    if normalize(k) == norm_gs:
                        etm_article = k
                        break
            
            if stock > 0: matched += 1
            results_r.append([etm_article])
            results_s.append([stock])
        
        logging.info(f"MATCHED: {matched} / {row_count}")
        
        # Save column R (Articles) - same place, overwritten
        r_range = f"{gspread.utils.rowcol_to_a1(2, r_idx + 1)}:{gspread.utils.rowcol_to_a1(1 + len(results_r), r_idx + 1)}"
        ws.update(values=results_r, range_name=r_range)
        
        # Save column S (Stocks) - same place, overwritten
        s_range = f"{gspread.utils.rowcol_to_a1(2, s_idx + 1)}:{gspread.utils.rowcol_to_a1(1 + len(results_s), s_idx + 1)}"
        ws.update(values=results_s, range_name=s_range)
        
        logging.info(f"SUCCESS! Time: {time.time() - start_time:.1f}s")
        
    except Exception as e:
        logging.exception(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    sync_all_stores()