"""Fetch exact full WB cards for local-map products tied to Ozon binding repairs."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from network_bypass import SourceAddressAdapter

OUT = BASE / 'wb_ozon_local_missing_binding_targets_full_20261012.json'


def main() -> None:
    if OUT.exists():
        raise RuntimeError('WB Ozon-binding repair scan already exists; inspect before retry')
    bind_plan = json.loads((BASE / 'ozon_local_map_missing_bindings_20261012_plan.json').read_text())
    if not bind_plan.get('actions'):
        raise RuntimeError('No exact Ozon binding repair plan is available')
    wb_snapshot = json.loads((BASE / 'wb_live_after_reconciliation_20261012.json').read_text())
    if not wb_snapshot.get('complete'):
        raise RuntimeError('Complete WB catalog snapshot is required')
    wb_by_offer = defaultdict(list)
    for card in wb_snapshot.get('cards') or []:
        wb_by_offer[str(card.get('vendorCode') or '')].append(card)
    offers = set()
    for action in bind_plan['actions']:
        for row in action['source_proof'].get('bindings') or []:
            offers.add(str(row['offer_id']))
    targets = {}
    missing_cards = []
    duplicates = []
    for offer in sorted(offers):
        cards = wb_by_offer.get(offer) or []
        if len(cards) == 0:
            missing_cards.append(offer)
        elif len(cards) != 1:
            duplicates.append(offer)
        else:
            targets[offer] = str(cards[0]['nmID'])
    if duplicates:
        raise RuntimeError(f'Duplicate WB cards for exact offers: {duplicates[:10]}')

    config = (ROOT / 'Shared_Настройки.js').read_text()
    block = config.split('const wbHeaders', 1)[1].split('};', 1)[0]
    match = re.search(r"Authorization\s*:\s*['\"]([^'\"]+)['\"]", block)
    if not match:
        raise RuntimeError('WB authorization unavailable')
    session = requests.Session()
    session.trust_env = False
    for iface in ('en1', 'en0'):
        info = subprocess.run(['ifconfig', iface], capture_output=True, text=True).stdout
        ip = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', info)
        if ip and 'status: active' in info:
            session.mount('https://', SourceAddressAdapter(ip.group(1), interface_name=iface))
            break
    else:
        raise RuntimeError('Active physical interface unavailable')
    headers = {'Authorization': match.group(1), 'Content-Type': 'application/json'}
    rows = {}
    seen_nmids = set()
    page, cursor = 0, {'limit': 100}
    started = datetime.now(timezone.utc).isoformat()
    complete = False

    def save(error=None):
        value = {'started_at': started, 'checked_at': datetime.now(timezone.utc).isoformat(),
                 'complete': complete, 'pages': page, 'catalog_cards': len(seen_nmids),
                 'candidate_offer_count': len(offers), 'target_count': len(targets),
                 'targets_found': len(rows), 'missing_wb_cards': missing_cards,
                 'cards_by_offer': rows}
        if error:
            value['error_type'] = error
        tmp = OUT.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
        tmp.replace(OUT)

    try:
        while True:
            payload = {'settings': {'sort': {'ascending': True}, 'cursor': cursor,
                                    'filter': {'withPhoto': -1}}}
            for attempt in range(8):
                response = session.post('https://content-api.wildberries.ru/content/v2/get/cards/list',
                                        headers=headers, json=payload, timeout=90)
                if response.status_code == 429:
                    time.sleep(min(60, 5 * (attempt + 1)))
                    continue
                response.raise_for_status()
                break
            else:
                raise RuntimeError('WB rate limit retry exhausted')
            body = response.json()
            batch = body.get('cards')
            if body.get('error') or not isinstance(batch, list):
                raise RuntimeError('Invalid WB full-card page')
            page += 1
            if body.get('cursor', {}).get('total') != len(batch):
                raise RuntimeError('WB cursor total/card count mismatch')
            for card in batch:
                nm_id, offer = card.get('nmID'), str(card.get('vendorCode') or '')
                if not nm_id or not offer or nm_id in seen_nmids:
                    raise RuntimeError('Missing or duplicate WB card identity')
                seen_nmids.add(nm_id)
                if offer in targets:
                    if offer in rows or str(nm_id) != targets[offer]:
                        raise RuntimeError(f'WB offer/nmID changed or duplicated for {offer}')
                    rows[offer] = card
            if page % 50 == 0:
                save()
                print(json.dumps({'pages': page, 'catalog_cards': len(seen_nmids),
                                  'targets_found': len(rows), 'target_count': len(targets)}, ensure_ascii=False), flush=True)
            if len(batch) < 100:
                complete = True
                if set(rows) != set(targets):
                    raise RuntimeError(f'WB full catalog readback missed {len(set(targets)-set(rows))} target offers')
                save()
                break
            c = body.get('cursor') or {}
            if not c.get('updatedAt') or not c.get('nmID'):
                raise RuntimeError('WB next-page cursor incomplete')
            cursor = {'limit': 100, 'updatedAt': c['updatedAt'], 'nmID': c['nmID']}
            time.sleep(0.55)
    except Exception as exc:
        save(type(exc).__name__)
        raise
    print(json.dumps({'complete': complete, 'catalog_cards': len(seen_nmids),
                      'candidate_offers': len(offers), 'full_cards': len(rows),
                      'no_wb_card': len(missing_cards), 'path': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
