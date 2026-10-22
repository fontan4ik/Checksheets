"""Marketplace client. Credentials stay in existing configuration; writes never auto-retry."""
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
from network_bypass import SourceAddressAdapter


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(name, value):
    path = BASE / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class Client:
    def __init__(self):
        config = (ROOT / 'Shared_Настройки.js').read_text()
        self.ozon_headers = {'Client-Id': re.search(r"const clientId\s*=\s*'([^']+)'", config)[1],
                             'Api-Key': re.search(r"const apiKey\s*=\s*'([^']+)'", config)[1],
                             'Content-Type': 'application/json'}
        block = config.split('const wbHeaders', 1)[1].split('};', 1)[0]
        self.wb_headers = {'Authorization': re.search(r"Authorization\s*:\s*['\"]([^'\"]+)['\"]", block)[1],
                           'Content-Type': 'application/json'}
        self.http = requests.Session()
        self.http.trust_env = False
        for iface in ('en1', 'en0'):
            result = subprocess.run(['ifconfig', iface], capture_output=True, text=True)
            match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match and 'status: active' in result.stdout:
                self.http.mount('https://', SourceAddressAdapter(match[1], interface_name=iface))
                break
        else:
            raise RuntimeError('Active physical interface unavailable')

    def call(self, platform, path, payload, *, mutation=False, method='POST'):
        host, headers = ('https://api-seller.ozon.ru', self.ozon_headers) if platform == 'ozon' else ('https://content-api.wildberries.ru', self.wb_headers)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        entry = {'started_at': now(), 'platform': platform, 'path': path, 'mutation': mutation,
                 'request_sha256': hashlib.sha256(encoded).hexdigest(), 'request_bytes': len(encoded)}
        log = BASE / 'api_calls.jsonl'
        with log.open('a') as stream:
            stream.write(json.dumps({**entry, 'phase': 'prepared'}, ensure_ascii=False) + '\n')
            stream.flush()
        response = None
        for attempt in range(1 if mutation else 5):
            try:
                response = self.http.request(method, host + path, data=encoded if method != 'GET' else None, headers=headers, timeout=(15, 120))
            except requests.RequestException as exc:
                if mutation or attempt == 4:
                    with log.open('a') as stream:
                        stream.write(json.dumps({**entry, 'phase': 'uncertain', 'error': type(exc).__name__, 'finished_at': now()}) + '\n')
                    raise RuntimeError('Request outcome uncertain; reconcile live state before retry') from None
                time.sleep(2 ** attempt)
                continue
            if not mutation and response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(2 ** (attempt + 1), 30))
                continue
            break
        try:
            body = response.json()
        except ValueError:
            body = {'non_json_response': True}
        response_record = {'http_status': response.status_code}
        if len(response.content) <= 262_144:
            response_record['body'] = body
        else:
            response_record['body_summary'] = {
                'truncated_for_log_size': True,
                'response_bytes': len(response.content),
                'response_sha256': hashlib.sha256(response.content).hexdigest(),
                'top_level_keys': sorted(body) if isinstance(body, dict) else [],
                'collection_sizes': {
                    key: len(value) for key, value in (body.items() if isinstance(body, dict) else [])
                    if isinstance(value, (list, dict))
                },
            }
        with log.open('a') as stream:
            stream.write(json.dumps({**entry, 'phase': 'response', **response_record,
                                     'finished_at': now()}, ensure_ascii=False) + '\n')
            stream.flush()
        if response.status_code != 200:
            raise RuntimeError(f'{platform} {path}: HTTP {response.status_code}; see api_calls.jsonl')
        time.sleep(.65 if platform == 'wb' else .2)
        return body

    def wb_cards(self, offer):
        cards = []
        cursor = {'limit': 100}
        seen = set()
        while True:
            data = self.call('wb', '/content/v2/get/cards/list', {'settings': {
                'sort': {'ascending': True}, 'cursor': cursor,
                'filter': {'withPhoto': -1, 'textSearch': offer}}})
            if data.get('error') or not isinstance(data.get('cards'), list):
                raise RuntimeError('Invalid WB list response')
            batch = data['cards']
            cards.extend(c for c in batch if c.get('vendorCode') == offer)
            returned = data.get('cursor', {})
            if returned.get('total') != len(batch):
                raise RuntimeError('WB page count mismatch')
            if len(batch) < 100:
                return cards
            signature = (returned.get('updatedAt'), returned.get('nmID'))
            if None in signature or signature in seen:
                raise RuntimeError('WB cursor incomplete or repeated')
            seen.add(signature)
            cursor = {'limit': 100, 'updatedAt': signature[0], 'nmID': signature[1]}

    def ozon_bindings(self, certificate_id):
        items = []
        last_id = 0
        expected_count = None
        seen_product_ids = set()
        while True:
            data = self.call('ozon', '/v1/product/certificate/products/list', {
                'certificate_id': int(certificate_id), 'last_id': last_id, 'limit': 1000})['result']
            batch = data.get('items')
            count = data.get('count')
            if not isinstance(batch, list) or not isinstance(count, int):
                raise RuntimeError('Ozon binding response omitted items or count')
            if expected_count is None:
                expected_count = count
            elif count != expected_count:
                raise RuntimeError('Ozon binding count changed during pagination')
            for binding in batch:
                product_id = str(binding.get('product_id') or '')
                if not product_id or product_id in seen_product_ids:
                    raise RuntimeError('Ozon binding pagination returned a missing or repeated product_id')
                seen_product_ids.add(product_id)
            items.extend(batch)
            if len(items) == expected_count:
                return items
            if not batch or len(items) > expected_count:
                raise RuntimeError('Ozon binding pagination incomplete')
            last_id = batch[-1]['product_id']
