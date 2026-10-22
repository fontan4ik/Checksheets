"""Fresh full-catalog WB readback for every candidate cleanup product."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from network_bypass import SourceAddressAdapter

OUT = BASE / 'wb_bulk_cleanup_targets_full_20261012.json'


def main() -> None:
    if OUT.exists():
        raise RuntimeError('WB bulk-cleanup scan already exists; inspect it before retry')
    candidate = json.loads((BASE / 'bulk_cleanup_candidates_20261012.json').read_text())
    if not candidate.get('complete'):
        raise RuntimeError('Candidate set is incomplete')
    targets = dict(candidate['target_offers'])
    update_plan = json.loads((BASE / 'wb_ozon_reconciliation_fullcard_plan_20261012.json').read_text())
    for update in update_plan.get('updates') or []:
        offer = update['offer_id']
        expected = str(update['nmID'])
        if offer in targets and str(targets[offer]['nmID']) != expected:
            raise RuntimeError(f'Conflicting expected WB nmID for {offer}')
        targets.setdefault(offer, {'nmID': expected, 'brand': None})

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

    header = {'Authorization': match.group(1), 'Content-Type': 'application/json'}
    rows: dict[str, dict] = {}
    seen_nmids = set()
    page = 0
    cursor = {'limit': 100}
    started = datetime.now(timezone.utc).isoformat()
    complete = False

    def save(error: str | None = None) -> None:
        state = {'started_at': started, 'checked_at': datetime.now(timezone.utc).isoformat(),
                 'complete': complete, 'pages': page, 'catalog_cards': len(seen_nmids),
                 'target_count': len(targets), 'targets_found': len(rows), 'cursor': cursor,
                 'cards_by_offer': rows}
        if error:
            state['error_type'] = error
        tmp = OUT.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':')))
        tmp.replace(OUT)

    try:
        while True:
            payload = {'settings': {'sort': {'ascending': True}, 'cursor': cursor,
                                    'filter': {'withPhoto': -1}}}
            for attempt in range(8):
                response = session.post('https://content-api.wildberries.ru/content/v2/get/cards/list',
                                        headers=header, json=payload, timeout=90)
                if response.status_code == 429:
                    time.sleep(min(60, 5 * (attempt + 1)))
                    continue
                response.raise_for_status()
                break
            else:
                raise RuntimeError('WB rate limit retry exhausted')
            body = response.json()
            if body.get('error') or not isinstance(body.get('cards'), list):
                raise RuntimeError('WB returned invalid full-card page')
            batch = body['cards']
            page += 1
            if body.get('cursor', {}).get('total') != len(batch):
                raise RuntimeError('WB cursor total/card count mismatch')
            for card in batch:
                nm_id, offer = card.get('nmID'), card.get('vendorCode')
                if not nm_id or not offer:
                    raise RuntimeError('WB card identity missing')
                if nm_id in seen_nmids:
                    raise RuntimeError(f'Duplicate WB nmID {nm_id}')
                seen_nmids.add(nm_id)
                if offer in targets:
                    if offer in rows:
                        raise RuntimeError(f'Duplicate exact WB vendorCode {offer}')
                    if str(nm_id) != str(targets[offer]['nmID']):
                        raise RuntimeError(f'WB nmID changed for {offer}')
                    rows[offer] = card
            if page % 50 == 0:
                save()
                print(json.dumps({'pages': page, 'catalog_cards': len(seen_nmids),
                                  'targets_found': len(rows), 'target_count': len(targets)}, ensure_ascii=False), flush=True)
            if len(batch) < 100:
                complete = True
                missing = set(targets) - set(rows)
                if missing:
                    raise RuntimeError(f'Full WB catalog missing {len(missing)} target offers')
                save()
                break
            current = body.get('cursor') or {}
            if not current.get('updatedAt') or not current.get('nmID'):
                raise RuntimeError('WB next-page cursor incomplete')
            cursor = {'limit': 100, 'updatedAt': current['updatedAt'], 'nmID': current['nmID']}
            time.sleep(0.55)
    except Exception as exc:
        save(type(exc).__name__)
        raise
    print(json.dumps({'complete': complete, 'pages': page, 'catalog_cards': len(seen_nmids),
                      'target_count': len(targets), 'targets_found': len(rows), 'path': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
