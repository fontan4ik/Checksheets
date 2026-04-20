# -*- coding: utf-8 -*-
import requests
import config
import json
import sys

def inspect():
    try:
        url_login = f"https://ipro.etm.ru/api/v1/user/login?log={config.ETM_LOGIN}&pwd={config.ETM_PASSWORD}"
        r_login = requests.post(url_login, timeout=10)
        session = r_login.json()['data']['session']
        
        # Test direct access by GdsCode 3832734
        gds = "3832734"
        print(f"Requesting direct remains for ETM Code: {gds}")
        url = f"https://ipro.etm.ru/api/v1/goods/{gds}/remains?session-id={session}"
        r = requests.get(url, timeout=15)
        
        print(f"Status Code: {r.status_code}")
        data = r.json()
        print(json.dumps(data, indent=4, ensure_ascii=False))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect()
