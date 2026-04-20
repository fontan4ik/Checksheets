#!/usr/bin/env python3
"""Debug orders status/check endpoint"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests, time, zipfile, io as iomod

CLIENT_ID = '92353868-1771409527407@advertising.performance.ozon.ru'
CLIENT_SECRET = 'qAXQ4PHS8Gccd5FfzX8d47BRm02BDH-9vYfYmwxvCMprrSXzEquYZnKhxPjprirtMakIKAnrR5Dd8894uw'
BASE_URL = 'https://api-performance.ozon.ru'
TARGET = '1644174248'

def get_tok():
    r = requests.post(f'{BASE_URL}/api/client/token', json={
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'
    }, timeout=30)
    return r.json()['access_token']

def get_camps(tok):
    r = requests.get(f'{BASE_URL}/api/client/campaign', headers={'Authorization': f'Bearer {tok}'}, timeout=30)
    return [c['id'] for c in r.json()['list']]

def create_orders(tok, cids):
    """Create report - from/to as RFC 3339"""
    body = {
        'from': '2025-04-01T00:00:00Z',
        'to': '2025-04-15T23:59:59Z'
        # campaigns optional - let server decide
    }
    
    r = requests.post(f'{BASE_URL}/api/client/statistic/orders/generate',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'},
        json=body, timeout=30)
    print(f'Create: {r.status_code} - {r.text[:200]}')
    if r.status_code == 200:
        return r.json().get('UUID')
    return None

def try_status_endpoints(tok, uid):
    """Try different status endpoints"""
    endpoints = [
        f'{BASE_URL}/api/client/statistic/orders/status?UUID={uid}',
        f'{BASE_URL}/api/client/statistic/status?UUID={uid}',
        f'{BASE_URL}/api/client/statistics/orders/status?UUID={uid}',
        f'{BASE_URL}/api/client/statistics/{uid}',
        f'{BASE_URL}/api/client/statistic/orders/check?UUID={uid}',
    ]
    
    for ep in endpoints:
        try:
            r = requests.get(ep, headers={'Authorization': f'Bearer {tok}'}, timeout=30)
            print(f'{ep.split("/")[-1]}: {r.status_code}')
            if r.status_code == 200:
                text = r.text.strip()
                if text:
                    print(f'  Response: {text[:150]}')
        except Exception as e:
            print(f'Error: {e}')

tok = get_tok()
camps = get_camps(tok)

uid = create_orders(tok, camps[:3])
if uid:
    print(f'UUID: {uid}')
    for i in range(3):
        print(f'\n--- Check attempt {i+1} ---')
        try_status_endpoints(tok, uid)
        time.sleep(3)
else:
    print('No UUID')

print('\nDone')