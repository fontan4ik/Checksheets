import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import time
import json
import zipfile
import io

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = "https://api-performance.ozon.ru"

TARGET_SKU = '1644174248'

def get_token():
    url = f"{BASE_URL}/api/client/token"
    body = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    print("Getting token...")
    response = requests.post(url, json=body)
    print(f"Token response: {response.status_code}")

    if response.status_code != 200:
        print(f"Error: {response.text}")
        return None

    data = response.json()
    token = data.get('access_token')
    print(f"Token obtained: {token[:20]}...")
    return token


def get_campaigns(token):
    url = f"{BASE_URL}/api/client/campaign"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print("\nGetting campaigns...")
    response = requests.get(url, headers=headers)
    print(f"Campaigns response: {response.status_code}")

    if response.status_code != 200:
        print(f"Error: {response.text}")
        return None

    data = response.json()
    campaigns = data.get('list', [])
    print("Got {} campaigns".format(len(campaigns)))
    return campaigns


def create_orders_report(token, campaign_ids, date_from, date_to):
    url = f"{BASE_URL}/api/client/statistics/orders/generate"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "campaigns": campaign_ids,
        "dateFrom": date_from,
        "dateTo": date_to
    }

    print(f"\nCreating orders report for campaigns: {campaign_ids}")
    print(f"Period: {date_from} → {date_to}")

    response = requests.post(url, headers=headers, json=body)
    print(f"Create report response: {response.status_code}")

    if response.status_code != 200:
        print(f"Error: {response.text}")
        return None

    data = response.json()
    uuid = data.get('UUID')
    print(f"✅ Report UUID: {uuid}")
    return uuid


def get_report_status(token, uuid):
    url = f"{BASE_URL}/api/client/statistics/orders/status?UUID={uuid}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)
    response_code = response.status_code

    if response_code == 404:
        return {"status": "IN_PROGRESS", "is_zip": False}

    if response_code != 200:
        return {"status": "ERROR", "error": f"HTTP {response_code}"}

    text = response.text.strip()

    if text.startswith('PK'):
        return {"status": "OK", "is_zip": True}

    if text.startswith('sku') or text.startswith(';') or text.startswith('Дата'):
        return {"status": "OK", "is_zip": False}

    try:
        data = response.json()
        return {"status": data.get("state", "IN_PROGRESS"), "is_zip": False}
    except:
        return {"status": "ERROR", "error": "Parse error"}


def download_report(token, uuid):
    url = f"{BASE_URL}/api/client/statistics/orders/download?UUID={uuid}"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    print(f"\nDownloading report {uuid}...")
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Download error: {response.status_code} - {response.text}")
        return None

    print(f"✅ Downloaded {len(response.content)} bytes")
    return response.content


def parse_report(content):
    is_zip = content[:2] == b'PK'

    if is_zip:
        print("📦 Unzipping...")
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            print(f"   Files: {zf.namelist()}")
            csv_content = zf.read(zf.namelist()[0])
    else:
        csv_content = content

    csv_text = csv_content.decode('utf-8').replace('\ufeff', '')
    lines = csv_text.strip().split('\n')

    print(f"📄 Total lines: {len(lines)}")
    print(f"📋 First line: {lines[0][:200]}")

    headers = lines[0].split(';')
    print(f"📋 Headers: {headers}")

    sku_idx = -1
    orders_idx = -1
    revenue_idx = -1
    spend_idx = -1

    for i, h in enumerate(headers):
        h_lower = h.lower().strip()
        if h_lower == 'sku' or 'артикул' in h_lower:
            sku_idx = i
        elif 'заказ' in h_lower or h_lower == 'orders':
            orders_idx = i
        elif 'выруч' in h_lower or 'доход' in h_lower or 'сумм' in h_lower or h_lower == 'revenue':
            revenue_idx = i
        elif 'расход' in h_lower or 'spend' in h_lower or 'cost' in h_lower:
            spend_idx = i

    print(f"📊 Indexes: sku={sku_idx}, orders={orders_idx}, revenue={revenue_idx}, spend={spend_idx}")

    stats = {}
    parsed = 0

    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith('Всего') or line.startswith('Total'):
            continue

        parts = line.split(';')
        sku = parts[sku_idx].strip() if sku_idx >= 0 else parts[0].strip()

        if not sku:
            continue

        orders = int(parts[orders_idx].strip()) if orders_idx >= 0 else 0
        revenue = float(parts[revenue_idx].strip().replace(',', '.')) if revenue_idx >= 0 else 0
        spend = float(parts[spend_idx].strip().replace(',', '.')) if spend_idx >= 0 else 0

        if orders > 0 or revenue > 0 or spend > 0:
            if sku not in stats:
                stats[sku] = {'orders': 0, 'revenue': 0, 'spend': 0}
            stats[sku]['orders'] += orders
            stats[sku]['revenue'] += revenue
            stats[sku]['spend'] += spend
            parsed += 1

    print(f"✅ Parsed: {parsed} rows, {len(stats)} unique SKUs")

    total_orders = sum(s['orders'] for s in stats.values())
    total_revenue = sum(s['revenue'] for s in stats.values())
    total_spend = sum(s['spend'] for s in stats.values())

    print(f"📊 TOTAL: orders={total_orders}, revenue={total_revenue:.2f}, spend={total_spend:.2f}")

    if TARGET_SKU in stats:
        data = stats[TARGET_SKU]
        print(f"\n🎯 TARGET SKU {TARGET_SKU}:")
        print(f"   Orders: {data['orders']}")
        print(f"   Revenue: {data['revenue']:.2f} ₽")
        print(f"   Spend: {data['spend']:.2f} ₽")
    else:
        print(f"\n⚠️ TARGET SKU {TARGET_SKU} NOT FOUND!")
        print(f"   Available SKUs: {list(stats.keys())[:10]}")

    return stats


def test_api():
    print("=" * 50)
    print("TESTING ORDERS REPORT API")
    print("=" * 50)

    token = get_token()
    if not token:
        print("❌ Failed to get token")
        return

    campaigns = get_campaigns(token)
    if not campaigns:
        print("❌ Failed to get campaigns")
        return

    print(f"\n📊 First 5 campaigns:")
    for c in campaigns[:5]:
        print(f"   ID: {c.get('id')}, Title: {c.get('title')}")

    test_campaigns = [c['id'] for c in campaigns[:3]]
    print(f"\n📊 Testing with campaigns: {test_campaigns}")

    today = time.strftime("%Y-%m-%d")
    date_from = "2025-04-01"
    date_to = today

    uuid = create_orders_report(token, test_campaigns, date_from, date_to)
    if not uuid:
        print("❌ Failed to create report")
        return

    print("\n⏳ Waiting for report...")
    for attempt in range(30):
        time.sleep(5)
        status = get_report_status(token, uuid)
        print(f"   Attempt {attempt + 1}: {status['status']}")

        if status['status'] == 'OK':
            content = download_report(token, uuid)
            if content:
                parse_report(content)
            return
        elif status['status'] == 'ERROR':
            print(f"❌ Error: {status.get('error')}")
            return

    print("❌ Timeout")


if __name__ == "__main__":
    test_api()
