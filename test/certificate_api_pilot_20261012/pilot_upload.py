"""Explicit four-document pilot. Default is read-only plan; --execute sends missing writes."""
import base64
import collections
import datetime
import json
import re
import sys
from pathlib import Path

from api_client import BASE, ROOT, Client, digest, now, save

PILOTS = [
    {'offer': '14048-1', 'product_id': 6023323036, 'sku': 5523523330, 'nmID': 1514673182,
     'number': 'ЕАЭС N RU Д-CN.РА07.В.18481/22', 'type': 2, 'issue': '2022-10-07', 'expiry': '2027-10-05',
     'file': 'group_2/NAVIGATOR/documents/NAV_declaration_14048_bb50bd4efe46.pdf',
     'sha256': 'bb50bd4efe4688c07913e4153ec1067a8004842f7d22199311f4e8982e33a85e',
     'registry': 'https://pub.fsa.gov.ru/rds/declaration/view/17092904'},
    {'offer': '14320-1', 'product_id': 6023415662, 'sku': 5523622453, 'nmID': 1508521338,
     'number': 'ЕАЭС N RU Д-CN.РА04.В.60713/25', 'type': 2, 'issue': '2025-05-23', 'expiry': '2030-05-22',
     'file': 'group_2/NAVIGATOR/documents/NAV_declaration_14320_3aed124818bf.pdf',
     'sha256': '3aed124818bf8c2bf1ead157f3e3540964881e3abaed4b9b6f67b253ef9ae036',
     'registry': 'https://pub.fsa.gov.ru/rds/declaration/view/20206039'},
    {'offer': 'WTP10-16-03-ZK-K01-1', 'product_id': 5609487591, 'sku': 5171062886, 'nmID': 1301546821,
     'number': 'ЕАЭС N RU Д-CN.РА03.В.40430/26', 'type': 2, 'issue': '2026-04-14', 'expiry': '2031-04-13',
     'file': 'group_2/IEK_GENERICA/documents/Адаптеры-переходники_тройники_._BOYANG_937ed62024.pdf',
     'sha256': 'a368e136b16c9c2674f401170d2d58ec4bce981e6a1b722f861f9e0b23df81b1'},
    {'offer': 'WTP10-16-03-ZK-K01-1', 'product_id': 5609487591, 'sku': 5171062886, 'nmID': 1301546821,
     'number': 'ЕАЭС RU С-CN.АЯ46.В.47896/26', 'type': 1, 'issue': '2026-05-06', 'expiry': '2030-04-27',
     'file': 'group_2/IEK_GENERICA/documents/Адаптеры_-_переходники_тройники_товарного_знака_IEK._BOYANG_89d29602ae.pdf',
     'sha256': 'bcd11f7733154e0d09615636e5c319a34c9382d8e3f500ac7f2a92975ff4e150'},
]

FIELDS = ('nmID', 'vendorCode', 'brand', 'title', 'gtin', 'description', 'dimensions', 'characteristics', 'sizes', 'kizMarked')
DOC_FIELDS = ('id', 'type', 'number', 'productNumber', 'tradeName', 'applicant', 'startDate', 'endDate', 'isEndless')


def norm(number):
    # Preserve country/year; only whitespace/punctuation and visual C/С are equivalent.
    return ''.join(x for x in str(number).upper().replace('С', 'C') if x.isalnum())


def list_certificates(client):
    certs = []
    page = 1
    while True:
        result = client.call('ozon', '/v1/product/certificate/list', {'page': page, 'page_size': 100})['result']
        certs.extend(result['certificates'])
        if page >= result['page_count']:
            if len({c['certificate_id'] for c in certs}) != len(certs):
                raise RuntimeError('Duplicate certificates')
            return certs
        page += 1


def main(execute=False):
    if execute and (BASE / 'pilot_execution.json').exists():
        raise RuntimeError('Pilot already attempted; reconcile journal before another execution')
    client = Client()
    certs = list_certificates(client)
    by_number = collections.defaultdict(list)
    for c in certs:
        by_number[norm(c['certificate_number'])].append(c)
    cards = {}
    for offer in sorted({p['offer'] for p in PILOTS}):
        found = client.wb_cards(offer)
        expected = {p['nmID'] for p in PILOTS if p['offer'] == offer}
        if {c['nmID'] for c in found} != expected:
            raise RuntimeError('Unexpected/missing WB exact cards: ' + offer)
        cards.update({c['nmID']: c for c in found})
        info = client.call('ozon', '/v3/product/info/list', {'offer_id': [offer]})['items']
        spec = next(p for p in PILOTS if p['offer'] == offer)
        if len(info) != 1 or info[0]['id'] != spec['product_id'] or info[0]['sku'] != spec['sku'] or info[0].get('is_archived'):
            raise RuntimeError('Ozon live mapping mismatch: ' + offer)
    save('pilot_cards_preflight.json', list(cards.values()))
    plan = {'checked_at': now(), 'pilots': [], 'wb_payloads': []}
    for p in PILOTS:
        path = ROOT / 'output_to_user/certificates' / p['file']
        if not path.is_file() or path.is_symlink() or digest(path) != p['sha256']:
            raise RuntimeError('File missing/changed: ' + str(path))
        if datetime.date.fromisoformat(p['expiry']) <= datetime.date(2026, 10, 12):
            raise RuntimeError('Expired document')
        matches = by_number.get(norm(p['number']), [])
        desired_type = 'declaration' if p['type'] == 2 else 'certificate_of_conformity'
        if any(c['type_code'] != desired_type for c in matches):
            raise RuntimeError('Conflicting Ozon document type')
        approved = [c for c in matches if c['status_code'] == 'approved']
        if matches and not approved:
            raise RuntimeError('Existing pending/rejected Ozon document; do not duplicate')
        action = 'create'
        cid = None
        if approved:
            bindings = [(c, client.ozon_bindings(c['certificate_id'])) for c in approved]
            exact = [(c, b) for c, rows in bindings for b in rows if b['sku'] == p['sku'] and b['product_id'] == p['product_id']]
            if exact:
                cid = exact[0][0]['certificate_id']
                action = 'already_bound'
            else:
                cid = approved[0]['certificate_id']
                action = 'bind'
        plan['pilots'].append({**p, 'ozon_action': action, 'certificate_id': cid, 'file_size': path.stat().st_size})
    for nm, card in cards.items():
        documents = card.get('documents') or {}
        if documents.get('excludeDocuments'):
            raise RuntimeError('Card explicitly excludes documents; requires separate review')
        old = documents.get('items') or []
        items = [{k: d[k] for k in DOC_FIELDS if k in d} for d in old]
        additions = []
        for p in PILOTS:
            if p['nmID'] != nm:
                continue
            existing = [d for d in items if norm(d.get('number')) == norm(p['number']) and d.get('type') == p['type']]
            if existing:
                if any(d.get('startDate', '')[:10] != p['issue'] or d.get('endDate', '')[:10] != p['expiry'] for d in existing):
                    raise RuntimeError('Existing WB document dates conflict')
                continue
            additions.append({'type': p['type'], 'number': p['number'], 'startDate': p['issue'] + 'T00:00:00Z',
                              'endDate': p['expiry'] + 'T00:00:00Z', 'isEndless': False})
        payload = {k: card[k] for k in FIELDS if k in card}
        payload['documents'] = {'items': items + additions, 'excludeDocuments': False}
        if additions:
            plan['wb_payloads'].append({'nmID': nm, 'vendorCode': card['vendorCode'], 'additions': additions, 'payload': payload})
    save('pilot_plan.json', plan)
    print(json.dumps({'ozon_actions': dict(collections.Counter(p['ozon_action'] for p in plan['pilots'])),
                      'wb_cards_to_update': len(plan['wb_payloads']), 'wb_document_additions': sum(len(p['additions']) for p in plan['wb_payloads'])}, ensure_ascii=False), flush=True)
    if not execute:
        return
    state = {'started_at': now(), 'results': []}
    save('pilot_execution.json', state)
    for p in plan['pilots']:
        action = p['ozon_action']
        if action == 'already_bound':
            continue
        if action == 'bind':
            body = client.call('ozon', '/v1/product/certificate/bind', {'certificate_id': p['certificate_id'], 'skus': [str(p['sku'])]}, mutation=True)
            if body.get('result') is not True:
                raise RuntimeError('Bind not accepted')
        else:
            path = ROOT / 'output_to_user/certificates' / p['file']
            if digest(path) != p['sha256']:
                raise RuntimeError('File changed before upload')
            expiry = datetime.date.fromisoformat(p['expiry'])
            params = {'name': 'Декларация о соответствии № ' + p['number'], 'certificate_type': 'DECLARATION',
                      'certificate_country': 'RU', 'accordance_type': 'EAEU', 'number': p['number'],
                      'issue_date': p['issue'] + 'T00:00:00Z', 'expired_date': {'date': {'day': expiry.day, 'month': expiry.month, 'year': expiry.year}},
                      'skus': [str(p['sku'])], 'product_type': 'UNKNOWN',
                      'files': [{'file_content': base64.b64encode(path.read_bytes()).decode('ascii'), 'name': path.name}],
                      'link_to_registry': p['registry']}
            body = client.call('ozon', '/v2/product/certificate/create', {'params': params}, mutation=True)
        state['results'].append({'platform': 'ozon', 'offer': p['offer'], 'number': p['number'], 'action': action, 'response': body})
        save('pilot_execution.json', state)
        print('Ozon', p['offer'], action, json.dumps(body, ensure_ascii=False)[:2000], flush=True)
        if action == 'create' and (not body.get('certificate_id') or body.get('status') != 'COMPLETED' or any(x.get('state') == 'INVALID' for x in body.get('params', []))):
            raise RuntimeError('Create incomplete; reconcile before continuing')
    payloads = []
    for row in plan['wb_payloads']:
        fresh = client.wb_cards(row['vendorCode'])
        current = next((c for c in fresh if c['nmID'] == row['nmID']), None)
        if current != cards[row['nmID']]:
            raise RuntimeError('WB card changed since preflight; rebuild rather than overwrite')
        payloads.append(row['payload'])
    if payloads:
        save('wb_update_payload.json', payloads)
        body = client.call('wb', '/content/v2/cards/update', payloads, mutation=True)
        state['results'].append({'platform': 'wb', 'cards': len(payloads), 'documents_added': sum(len(r['additions']) for r in plan['wb_payloads']), 'response': body})
        save('pilot_execution.json', state)
        print('WB', json.dumps(body, ensure_ascii=False), flush=True)
        if body.get('error') is not False:
            raise RuntimeError('WB update not accepted')
    state['finished_at'] = now()
    save('pilot_execution.json', state)


if __name__ == '__main__':
    main('--execute' in sys.argv)
