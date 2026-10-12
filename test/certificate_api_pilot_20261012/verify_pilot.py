"""Fresh readback only: acceptance and final application are reported separately."""
import json
import sys
from pathlib import Path

from api_client import BASE, Client, now, save
from pilot_upload import FIELDS, PILOTS, canonical_card, list_certificates, norm


def main():
    client = Client()
    certs = list_certificates(client)
    before = {c['nmID']: c for c in json.loads((BASE / 'wb_resume_before.json').read_text())}
    cards = {}
    for offer in sorted({p['offer'] for p in PILOTS}):
        cards.update({c['nmID']: c for c in client.wb_cards(offer)})
    result = {'checked_at': now(), 'pilots': [], 'card_preservation': []}
    for nm, source in before.items():
        current = cards.get(nm)
        differences = []
        if current:
            a, b = canonical_card(source), canonical_card(current)
            differences = [k for k in FIELDS + ('photos', 'video', 'tags', 'needKiz', 'subjectID', 'imtID', 'nmUUID') if k != 'characteristics' and a.get(k) != b.get(k)]
            old_chars = {c['id']: c for c in a.get('characteristics', [])}
            new_chars = {c['id']: c for c in b.get('characteristics', [])}
            # WB mirrors document metadata into these three document characteristics.
            expected_doc_ids = {15001135, 15001137, 15001138}
            changed_original = [cid for cid, c in old_chars.items() if new_chars.get(cid) != c]
            unexpected_added = [cid for cid in new_chars.keys() - old_chars.keys() if cid not in expected_doc_ids]
            if changed_original or unexpected_added:
                differences.append('characteristics')
            document_attribute_additions = [new_chars[cid] for cid in new_chars.keys() - old_chars.keys() if cid in expected_doc_ids]
        else:
            document_attribute_additions = []
        result['card_preservation'].append({'nmID': nm, 'present': current is not None, 'changed_unrelated_fields': differences,
                                            'server_added_document_characteristics': document_attribute_additions})
    for p in PILOTS:
        matches = [c for c in certs if norm(c['certificate_number']) == norm(p['number']) and c['type_code'] == ('declaration' if p['type'] == 2 else 'certificate_of_conformity')]
        ozon = []
        for certificate in matches:
            bindings = client.ozon_bindings(certificate['certificate_id'])
            exact = [b for b in bindings if b['product_id'] == p['product_id'] and b['sku'] == p['sku']]
            ozon.append({'certificate': certificate, 'target_bindings': exact, 'all_bindings': bindings})
        card = cards.get(p['nmID']) or {}
        documents = card.get('documents') or {}
        items = [d for d in documents.get('items', []) if d.get('type') == p['type'] and norm(d.get('number')) == norm(p['number'])]
        ozon_final = any(r['certificate']['status_code'] == 'approved' and any(b['product_status_code'] == 'approved' for b in r['target_bindings']) for r in ozon)
        overall = documents.get('overallVerdict') or {}
        wb_final = (documents.get('excludeDocuments') is False and overall.get('isFullyChecked') is True and overall.get('status') == 1 and
                    any(d.get('startDate', '')[:10] == p['issue'] and d.get('endDate', '')[:10] == p['expiry'] and
                        (d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('status') == 1 for d in items))
        result['pilots'].append({'spec': p, 'ozon': ozon, 'wb_documents': documents, 'wb_exact_items': items,
                                 'ozon_final': ozon_final, 'wb_final': wb_final, 'both_final': ozon_final and wb_final})
        print(json.dumps({'offer': p['offer'], 'number': p['number'], 'ozon_doc_status': [r['certificate']['status_code'] for r in ozon],
                          'ozon_binding_status': [b['product_status_code'] for r in ozon for b in r['target_bindings']],
                          'wb_exact_items': len(items), 'wb_verdicts': [d.get('verdict') for d in items], 'wb_overall': overall,
                          'both_final': ozon_final and wb_final}, ensure_ascii=False), flush=True)
    result['all_unrelated_card_fields_preserved'] = all(r['present'] and not r['changed_unrelated_fields'] for r in result['card_preservation'])
    save('pilot_verification_latest.json', result)
    stamp = result['checked_at'].replace(':', '').replace('.', '').replace('+', '_')
    save('pilot_verification_' + stamp + '.json', result)
    print('preserved:', result['all_unrelated_card_fields_preserved'], flush=True)


if __name__ == '__main__':
    main()
