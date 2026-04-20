#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ozon Performance API - Email report"""

import io
import requests
import time
import csv
import zipfile
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, timedelta

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'

# Email настройки - ИЗМЕНИ these
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_FROM = 'your-email@gmail.com'
EMAIL_PASSWORD = 'your-app-password'  # App password для Gmail
EMAIL_TO = 'recipient@example.com'

OUTPUT_FILE = 'ozon_ad_stats.csv'
TARGET_SKU = '1644174248'

def log(msg): print(msg)
def log_ok(msg): print(f"[OK] {msg}")
def log_err(msg): print(f"[ERROR] {msg}")

# === API ===

def get_token():
    resp = requests.post(f"{BASE_URL}/api/client/token", json={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "grant_type": "client_credentials"
    })
    resp.raise_for_status()
    log_ok("Token OK")
    return resp.json()['access_token']

def get_campaigns(token):
    resp = requests.get(f"{BASE_URL}/api/client/campaign", 
        headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    camps = resp.json()['list']
    log_ok(f"Campaigns: {len(camps)}")
    return [c for c in camps if c.get('state') == 'CAMPAIGN_STATE_RUNNING']

def request_report(token, campaign_ids, date_from, date_to):
    resp = requests.post(f"{BASE_URL}/api/client/statistics", 
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"campaigns": campaign_ids, "dateFrom": date_from, "dateTo": date_to, "groupBy": "SKU"})
    resp.raise_for_status()
    log(f"Request: {campaign_ids[:3]}...")
    return resp.json()['UUID']

def wait_report(token, uuid):
    url = f"{BASE_URL}/api/client/statistics/{uuid}"
    for i in range(25):
        time.sleep(5)
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 200:
            data = resp.json()
            if data.get('state') == 'OK' and data.get('link'):
                raw = requests.get(BASE_URL + data['link'], 
                    headers={"Authorization": f"Bearer {token}"}).content
                log_ok(f"Ready batch {i+1}")
                return raw
    return None

def parse_csv(content):
    if content[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(content))
        text = z.read(z.namelist()[0]).decode('utf-8-sig')
    else:
        text = content.decode('utf-8-sig')
    
    lines = text.replace('\ufeff', '').strip().split('\n')
    stats = {}
    
    for line in lines[1:]:
        if not line.strip() or line.startswith(';') or 'Всего' in line:
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
        except:
            continue
        
        if orders > 0 or revenue > 0 or spend > 0:
            stats[sku] = {'orders': orders, 'spend': spend, 'revenue': revenue}
    
    return stats

def fetch_stats(token, campaigns, date_from, date_to):
    campaign_ids = [c['id'] for c in campaigns]
    all_stats = {}
    
    for i in range(0, len(campaign_ids), 10):
        batch = campaign_ids[i:i+10]
        
        uuid = request_report(token, batch, date_from, date_to)
        raw = wait_report(token, uuid)
        
        if raw:
            batch_stats = parse_csv(raw)
            for sku, data in batch_stats.items():
                if sku not in all_stats:
                    all_stats[sku] = {'orders': 0, 'spend': 0, 'revenue': 0}
                all_stats[sku]['orders'] += data['orders']
                all_stats[sku]['spend'] += data['spend']
                all_stats[sku]['revenue'] += data['revenue']
        
        time.sleep(3)
    
    log_ok(f"Total: {len(all_stats)} SKU")
    return all_stats

def save_csv(stats):
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['sku', 'orders', 'revenue', 'spend'])
        for sku, data in sorted(stats.items()):
            writer.writerow([sku, data['orders'], data['revenue'], data['spend']])
    log_ok(f"Saved: {OUTPUT_FILE}")

# === EMAIL ===

def send_email(stats, date_from, date_to):
    if not EMAIL_PASSWORD or EMAIL_PASSWORD == 'your-app-password':
        log_err("Email not configured - configure SMTP settings first")
        return
    
    target = stats.get(TARGET_SKU, {'orders': 0, 'revenue': 0, 'spend': 0})
    
    # Check target found
    if target['orders'] > 0 or target['revenue'] > 0 or target['spend'] > 0:
        log_ok(f"TARGET {TARGET_SKU}: orders={target['orders']}, revenue={target['revenue']:.2f}, spend={target['spend']:.2f}")
    
    # Build HTML
    html = f"""<html><body>
    <h2>Ozon Рекламная Статистика</h2>
    <p>Период: {date_from} - {date_to}</p>
    <p>Всего SKU: {len(stats)}</p>
    
    <h3>Целевой товар (SKU: {TARGET_SKU})</h3>
    <table border="1">
        <tr><th>Показатель</th><th>Значение</th></tr>
        <tr><td>Заказов</td><td>{target['orders']}</td></tr>
        <tr><td>Выручка</td><td>{target['revenue']:.2f} ₽</td></tr>
        <tr><td>Расход</td><td>{target['spend']:.2f} ₽</td></tr>
    </table>
    
    <h3>Топ 20 по заказам</h3>
    <table border="1">
        <tr><th>SKU</th><th>Заказы</th><th>Выручка</th><th>Расход</th></tr>"""
    
    top = sorted(stats.items(), key=lambda x: x[1]['orders'], reverse=True)[:20]
    for sku, data in top:
        html += f"<tr><td>{sku}</td><td>{data['orders']}</td><td>{data['revenue']:.2f} ₽</td><td>{data['spend']:.2f} ₽</td></tr>"
    
    html += "</table></body></html>"
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Ozon Реклама - {date_from} to {date_to}"
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    # Attach CSV
    with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
        csv_part = MIMEText(f.read(), 'csv', 'utf-8')
        csv_part.add_header('Content-Disposition', 'attachment', filename=OUTPUT_FILE)
        msg.attach(csv_part)
    
    # Send
    try:
        log(f"Sending to {EMAIL_TO}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        log_ok("Email sent!")
    except Exception as e:
        log_err(f"Email error: {e}")

# === MAIN ===

def main():
    print("=" * 50)
    print("OZON PERFORMANCE API - EMAIL")
    print("=" * 50)
    
    try:
        # Token
        token = get_token()
        
        # Campaigns
        campaigns = get_campaigns(token)
        if not campaigns:
            log_err("No active campaigns")
            return
        
        # Date range: last 7 days
        today = date.today()
        date_to = today - timedelta(days=1)
        date_from = date_to - timedelta(days=6)
        
        date_from_str = date_from.strftime('%Y-%m-%d')
        date_to_str = date_to.strftime('%Y-%m-%d')
        
        log(f"Period: {date_from_str} -> {date_to_str}")
        
        # Fetch stats
        stats = fetch_stats(token, campaigns, date_from_str, date_to_str)
        
        # Save CSV
        save_csv(stats)
        
        # Send email
        send_email(stats, date_from_str, date_to_str)
        
        log_ok("DONE")
        
    except Exception as e:
        log_err(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()