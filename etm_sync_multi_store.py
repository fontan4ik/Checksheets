# -*- coding: utf-8 -*-
import sys
import time
import re
import requests
import gspread
import logging
import config
import gsheets_utils

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(r"c:\AI\Работа Voltmir\1с\sync_multi.log", encoding='utf-8', mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)

def normalize(s):
    if not s: return ""
    s = str(s).strip()
    # Remove text in parentheses
    s = re.sub(r'\(.*\)', '', s)
    # Clear all except alphanumeric
    s = re.sub(r'[^A-Z0-9]', '', s.upper())
    return s

def sync():
    logging.info("--- STARTING MULTI-STORE ETM SYNC (SAMARA) ---")
    start_time = time.time()
    headers = {"Accept": "application/json"}
    
    # 1. Login
    session = None
    for attempt in range(3):
        try:
            logging.info(f"Logging into ETM (Attempt {attempt+1}/3)...")
            params = {'log': config.ETM_LOGIN, 'pwd': config.ETM_PASSWORD}
            r_login = requests.post("https://ipro.etm.ru/api/v1/user/login", params=params, headers=headers, timeout=30)
            r_login.raise_for_status()
            login_data = r_login.json()
            logging.info(f"Login response: {login_data}")
            session = login_data['data']['session']
            break
        except Exception as e:
            logging.warning(f"Login attempt {attempt+1} failed: {e}")
            if attempt < 2: time.sleep(5)
            
    if not session:
        logging.error("Could not obtain session.")
        return

    try:
        # 2. Find Samara stores
        stores_url = f"https://ipro.etm.ru/api/v1/user/stores?session-id={session}"
        samara_store_ids = []
        try:
            r_stores = requests.get(stores_url, headers=headers, timeout=30)
            if r_stores.status_code == 200:
                rows = r_stores.json().get('data', {}).get('rows', [])
                for s in rows:
                    name = s.get('StoreName', '').lower()
                    if 'самар' in name or 'строй' in name:
                        samara_store_ids.append({'id': s['id'], 'name': s['StoreName']})
        except: pass
        
        if not samara_store_ids:
            samara_store_ids = [{'id': 13, 'name': 'РЦ Самара'}, {'id': 17, 'name': 'Самара ОП'}, {'id': 18, 'name': 'Самара ОП 2'}]
        
        logging.info(f"Targets: {[s['id'] for s in samara_store_ids]}")

        # 3. Aggregate remains
        total_etm_lookup = {}
        # We also build an "article tail" index to handle cases like SEN30 22068 -> 22068
        tail_lookup = {}
        
        for s in samara_store_ids:
            sid = s['id']
            logging.info(f"Fetching remains for store {sid}...")
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
                        
                        # Add to primary lookup
                        if gds: total_etm_lookup[gds] = total_etm_lookup.get(gds, 0) + stock
                        if art: total_etm_lookup[art] = total_etm_lookup.get(art, 0) + stock
                        
                        # Add to tail lookup (numeric tail of the article)
                        # Example: SEN30 22068 -> Extract 22068
                        match = re.search(r'(\d+)$', str(raw_art).strip())
                        if match:
                            tail = match.group(1)
                            if len(tail) >= 4: # Only for tails that are somewhat unique
                                tail_lookup[tail] = tail_lookup.get(tail, 0) + stock
            except Exception as e:
                logging.error(f"  Error store {sid}: {e}")

        # 4. Matching logic
        logging.info(f"Unique ETM articles: {len(total_etm_lookup)}, Tails: {len(tail_lookup)}")
        
        # Test 22068
        n_22068 = normalize("22068")
        st_22068 = total_etm_lookup.get(n_22068, 0)
        tail_st_22068 = tail_lookup.get("22068", 0)
        logging.info(f"CHECK 22068: Direct={st_22068}, Tail={tail_st_22068}")

        # 5. Read GS and Update
        ws = gsheets_utils.get_worksheet("ETM TR")
        all_data = ws.get_all_values()
        header = all_data[0]
        # Column K is index 10 (0-based), column B for articles is index 1
        t_idx = 10  # Column K
            
        results = []
        matched = 0
        for row in all_data[1:]:
            gs_val = row[1] if len(row) > 1 else ""  # Column B
            norm_gs = normalize(gs_val)
            
            # 1. Exact match (normalize vs normalize)
            stock = total_etm_lookup.get(norm_gs, 0)
            
            # 2. Tail match (if GS val is numeric tail of ETM article)
            if stock == 0 and norm_gs in tail_lookup:
                stock = tail_lookup[norm_gs]
                
            if stock > 0: matched += 1
            results.append([stock])
            
        logging.info(f"MATCHED: {matched} / {len(results)}")

        # 6. Save
        c_range = f"{gspread.utils.rowcol_to_a1(2, t_idx + 1)}:{gspread.utils.rowcol_to_a1(1 + len(results), t_idx + 1)}"
        ws.update(values=results, range_name=c_range)
        logging.info(f"SUCCESS! Time: {time.time() - start_time:.1f}s")
        
    except Exception as e:
        logging.exception(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    sync()
