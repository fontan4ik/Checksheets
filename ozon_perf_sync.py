"""
Ozon Performance API - Синхронизация рекламной статистики в Google Sheets
Аналогично etm_sync_local.py
"""

import time
import io
import requests
import zipfile

import config
import gsheets_utils

# Для отладки - целевой SKU
TARGET_SKU = '1644174248'


def get_perf_token():
    """Получение OAuth токена для Performance API"""
    url = f"{config.OZON_PERF_BASE_URL}/api/client/token"
    payload = {
        "client_id": config.OZON_PERF_CLIENT_ID,
        "client_secret": config.OZON_PERF_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            if token:
                print(f"Ozon Performance token obtained")
                return token
        print(f"Token error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Token request error: {e}")
    return None


def get_perf_campaigns(token):
    """Получение списка кампаний"""
    url = f"{config.OZON_PERF_BASE_URL}/api/client/campaign"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            campaigns = data.get('list', [])
            print(f"Found {len(campaigns)} campaigns")
            return campaigns
        print(f"Campaigns error: {response.status_code}")
    except Exception as e:
        print(f"Campaigns request error: {e}")
    return []


def request_perf_report(token, campaign_ids, date_from, date_to):
    """Создание отчёта"""
    url = f"{config.OZON_PERF_BASE_URL}/api/client/statistics"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "campaigns": campaign_ids,
        "dateFrom": date_from,
        "dateTo": date_to,
        "groupBy": "SKU"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            uuid = data.get("UUID")
            if uuid:
                return uuid
        print(f"Report error: {response.status_code}")
    except Exception as e:
        print(f"Report request error: {e}")
    return None


def wait_perf_report(token, uuid):
    """Ожидание готовности отчёта"""
    url = f"{config.OZON_PERF_BASE_URL}/api/client/statistics/{uuid}"
    headers = {"Authorization": f"Bearer {token}"}
    
    max_attempts = 25
    for attempt in range(max_attempts):
        time.sleep(5)
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                state = data.get("state")
                
                if state == "OK" and data.get("link"):
                    link = data.get("link")
                    raw = requests.get(config.OZON_PERF_BASE_URL + link, headers=headers, timeout=60).content
                    return raw
                elif state == "ERROR":
                    print(f"Report generation error")
                    return None
        except Exception as e:
            print(f"Wait error: {e}")
    
    print(f"Timeout waiting for report")
    return None


def parse_perf_csv(content):
    """Парсинг CSV отчёта Ozon Performance"""
    stats = {}
    
    try:
        # Распаковка если ZIP
        if content[:2] == b'PK':
            z = zipfile.ZipFile(io.BytesIO(content))
            text = z.read(z.namelist()[0]).decode('utf-8-sig')
        else:
            text = content.decode('utf-8-sig')
    except Exception as e:
        print(f"ZIP extract error: {e}")
        return stats
    
    lines = text.replace('\ufeff', '').strip().split('\n')
    print(f"CSV lines: {len(lines)}")
    
    for line in lines[1:]:
        if not line.strip():
            continue
        if line.startswith(';') or 'Всего' in line:
            continue
        
        parts = line.split(';')
        if len(parts) < 11:
            continue
        
        sku = parts[0].strip()
        if not sku:
            continue
        
        try:
            spend = float(parts[9].replace(',', '.').strip() or 0)
            orders = int(parts[10].strip() or 0)
            revenue = float(parts[11].replace(',', '.').strip() or 0)
        except (ValueError, IndexError):
            continue
        
        if orders > 0 or revenue > 0 or spend > 0:
            stats[sku] = {
                'orders': orders,
                'spend': spend,
                'revenue': revenue
            }
    
    print(f"Parsed {len(stats)} unique SKUs with data")
    return stats


def fetch_perf_stats(token, campaigns, date_from, date_to):
    """
    Получение статистики по всем кампаниям
    Обрабатывает батчами по 10 кампаний (лимит API)
    """
    campaign_ids = [c['id'] for c in campaigns]
    all_stats = {}
    
    BATCH_SIZE = 10
    request_delay = 3  # Пауза между запросами
    
    total_batches = (len(campaign_ids) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(0, len(campaign_ids), BATCH_SIZE):
        batch = campaign_ids[i:i+BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        
        print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} campaigns)...")
        
        # Rate limiting
        elapsed = time.time() - 0
        if elapsed < request_delay:
            time.sleep(request_delay - elapsed)
        
        uuid = request_perf_report(token, batch, date_from, date_to)
        if not uuid:
            print(f"Failed to create report for batch {batch_num}")
            time.sleep(request_delay)
            continue
        
        raw = wait_perf_report(token, uuid)
        
        if raw:
            batch_stats = parse_perf_csv(raw)
            
            # Агрегация данных
            for sku, data in batch_stats.items():
                if sku not in all_stats:
                    all_stats[sku] = {'orders': 0, 'spend': 0, 'revenue': 0}
                all_stats[sku]['orders'] += data['orders']
                all_stats[sku]['spend'] += data['spend']
                all_stats[sku]['revenue'] += data['revenue']
            
            # Debug target SKU
            if TARGET_SKU in all_stats:
                t = all_stats[TARGET_SKU]
                print(f"  *** TARGET {TARGET_SKU}: orders={t['orders']}, spend={t['spend']:.2f}, revenue={t['revenue']:.2f}")
        
        time.sleep(request_delay)
    
    print(f"Total unique SKUs: {len(all_stats)}")
    return all_stats


def sync_perf_ads():
    """
    Синхронизация рекламной статистики в Google Sheets
    Аналогично sync_etm()
    """
    print("=" * 60)
    print("Starting Ozon Performance Ads Sync...")
    print("=" * 60)
    
    # 1. Получение токена
    token = get_perf_token()
    if not token:
        print("Failed to get token")
        return
    
    # 2. Получение кампаний
    campaigns = get_perf_campaigns(token)
    if not campaigns:
        print("No campaigns found")
        return
    
    # 3. Определение периода (последние 7 дней)
    from datetime import date, timedelta
    today = date.today()
    date_to = today - timedelta(days=1)
    date_from = date_to - timedelta(days=6)
    
    date_from_str = date_from.strftime('%Y-%m-%d')
    date_to_str = date_to.strftime('%Y-%m-%d')
    
    print(f"Period: {date_from_str} -> {date_to_str}")
    
    # 4. Получение статистики
    stats = fetch_perf_stats(token, campaigns, date_from_str, date_to_str)
    
    # 5. Чтение SKU из таблицы (колонка V = column 22)
    try:
        ws = gsheets_utils.get_worksheet(config.TARGET_SHEET_NAME)
    except Exception as e:
        print(f"Error accessing Google Sheet: {e}")
        return
    
    # Колонка V (22) - Артикул Ozon / SKU
    sku_values = ws.col_values(22)[1:]  # Skip header
    print(f"Found {len(sku_values)} SKUs in column V")
    
    # 6. Подготовка данных для записи
    col_ba_data = []  # Реклама Количество (колонка 53)
    col_bb_data = []  # Реклама Стоимость (колонка 54)
    col_bc_data = []  # Реклама Расход (колонка 55)
    
    found_count = 0
    
    for sku in sku_values:
        sku_str = str(sku).strip() if sku else ""
        
        if sku_str and sku_str in stats:
            data = stats[sku_str]
            col_ba_data.append([data['orders']])
            col_bb_data.append([data['revenue']])
            col_bc_data.append([data['spend']])
            found_count += 1
        else:
            col_ba_data.append([0])
            col_bb_data.append([0])
            col_bc_data.append([0])
    
    print(f"Matched SKUs: {found_count}/{len(sku_values)}")
    
    # Debug target
    if TARGET_SKU in stats:
        t = stats[TARGET_SKU]
        print(f"*** TARGET {TARGET_SKU}: orders={t['orders']}, spend={t['spend']:.2f}, revenue={t['revenue']:.2f}")
    
    # 7. Запись в Google Sheets
    print(f"\n=== Writing to Google Sheet ===")
    
    try:
        # BA (53) - Реклама Количество
        gsheets_utils.update_column_by_header(ws, "Реклама Количество", col_ba_data)
        # BB (54) - Реклама Стоимость
        gsheets_utils.update_column_by_header(ws, "Реклама Стоимость", col_bb_data)
        # BC (55) - Реклама Расход
        gsheets_utils.update_column_by_header(ws, "Реклама Расход", col_bc_data)
        
        print(f"\n=== Ozon Performance Ads Sync completed! ===")
        print(f"Updated: {found_count}/{len(sku_values)} rows")
        
    except Exception as e:
        print(f"Error updating sheet: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    sync_perf_ads()