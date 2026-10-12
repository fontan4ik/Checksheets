"""Resume only the WB pilot after independently reconciling successful Ozon creates."""
import json
import sys

from api_client import BASE, Client, now, save
from pilot_upload import DOC_FIELDS, FIELDS, PILOTS, canonical_card, norm


def main(execute=False):
    if execute and (BASE / 'wb_resume_execution.json').exists():
        raise RuntimeError('WB write already attempted; inspect readback before retry')
    client = Client()
    payloads = []
    originals = []
    for offer in sorted({p['offer'] for p in PILOTS}):
        cards = client.wb_cards(offer)
        expected = {p['nmID'] for p in PILOTS if p['offer'] == offer}
        if {c['nmID'] for c in cards} != expected:
            raise RuntimeError('Unexpected WB exact target set')
        for card in cards:
            originals.append(card)
            docs = card.get('documents') or {}
            if docs.get('excludeDocuments'):
                raise RuntimeError('Document exclusion needs review')
            items = [{k: d[k] for k in DOC_FIELDS if k in d} for d in docs.get('items', [])]
            additions = []
            for p in PILOTS:
                if p['nmID'] != card['nmID']:
                    continue
                if any(d.get('type') == p['type'] and norm(d.get('number')) == norm(p['number']) for d in items):
                    continue
                additions.append({'type': p['type'], 'number': p['number'], 'startDate': p['issue'] + 'T00:00:00Z',
                                  'endDate': p['expiry'] + 'T00:00:00Z', 'isEndless': False})
            if additions:
                payload = {k: card[k] for k in FIELDS if k in card}
                payload['documents'] = {'items': items + additions, 'excludeDocuments': False}
                payloads.append(payload)
    save('wb_resume_before.json', originals)
    save('wb_update_payload.json', payloads)
    print(json.dumps({'cards': len(payloads), 'documents': sum(len(p['documents']['items']) for p in payloads)}), flush=True)
    if not execute:
        return
    for card in originals:
        fresh = client.wb_cards(card['vendorCode'])
        current = next((c for c in fresh if c['nmID'] == card['nmID']), None)
        if canonical_card(current) != canonical_card(card):
            raise RuntimeError('Substantive concurrent WB card change; rebuild payload')
    state = {'started_at': now(), 'phase': 'prepared', 'cards': len(payloads)}
    save('wb_resume_execution.json', state)
    if payloads:
        body = client.call('wb', '/content/v2/cards/update', payloads, mutation=True)
        state.update(response=body, finished_at=now(), phase='response')
        save('wb_resume_execution.json', state)
        print(json.dumps(body, ensure_ascii=False), flush=True)
        if body.get('error') is not False:
            raise RuntimeError('WB request rejected')


if __name__ == '__main__':
    main('--execute' in sys.argv)
