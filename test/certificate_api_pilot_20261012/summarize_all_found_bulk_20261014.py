"""Read-only status from complete marketplace snapshots; count unique edges."""
import collections
import datetime as dt
import json
from pathlib import Path
from api_client import now
from reconcile_approved_ozon_docs_to_wb import doc_key, norm_number, OZON_TO_WB_TYPE
from run_all_found_certificates_20261014 import valid_dates, atomic

BASE = Path(__file__).resolve().parent


def main():
    read = lambda name: json.loads((BASE / name).read_text())
    products = read('all_found_ozon_products_snapshot_20261014.json')
    certificates = read('all_found_ozon_certificates_snapshot_20261014.json')
    cards = read('all_found_wb_cards_snapshot_20261014.json')
    manifest = read('all_found_certificates_bulk_manifest_20261014.json')
    if not all(x.get('complete') for x in (products, certificates, cards)):
        raise RuntimeError('Incomplete marketplace snapshot')
    by_sku = collections.defaultdict(list)
    by_offer = collections.defaultdict(list)
    for p in products['products']:
        by_sku[str(p['sku'])].append(p)
    for card in cards['cards']:
        by_offer[card['vendorCode']].append(card)
    blocked = set(manifest['blocked_document_keys'])
    brand_blocks = manifest.get('blocked_binding_brands', {})
    edges = {}
    pending = []
    for cert in certificates['certificates']:
        typ = OZON_TO_WB_TYPE.get(cert.get('type_code'))
        number = cert['certificate_number']
        key = norm_number(number)
        if not typ or cert.get('accordance_type_code') != 'EAEU' or not valid_dates(cert.get('issue_date'), cert.get('expire_date')):
            continue
        active_pending = []
        for binding in cert.get('live_bindings', []):
            matching = by_sku.get(str(binding['sku']), [])
            if len(matching) != 1 or str(matching[0]['product_id']) != str(binding['product_id']):
                continue
            product = matching[0]
            offer = product['offer_id']
            found = by_offer.get(offer, [])
            card = found[0] if len(found) == 1 else None
            brand = (card or {}).get('brand') or 'Без бренда / нет карточки WB'
            in_scope = key not in blocked and brand not in brand_blocks.get(key, [])
            if (cert['status_code'] in ('approved', 'awaiting_verification') and in_scope
                    and binding.get('product_status_code') not in ('approved', 'declined')):
                active_pending.append({'offer_id': offer, 'product_id': product['product_id'], 'sku': product['sku']})
            if cert['status_code'] != 'approved' or binding.get('product_status_code') != 'approved':
                continue
            if not in_scope:
                state = 'scope_blocked'
            elif len(found) != 1:
                state = 'missing_or_ambiguous_wb_card'
            elif (card.get('documents') or {}).get('excludeDocuments') is True:
                state = 'wb_documents_disabled'
            else:
                same = [d for d in (card.get('documents') or {}).get('items', [])
                        if doc_key(d) == (typ, key)
                        and str(d.get('startDate', ''))[:10] == str(cert['issue_date'])[:10]
                        and str(d.get('endDate', ''))[:10] == str(cert['expire_date'])[:10]]
                if len(same) != 1:
                    state = 'missing_or_conflicting_wb_document'
                else:
                    verdict = same[0].get('verdict') or {}
                    if verdict.get('verified') is True and verdict.get('status') == 1 and verdict.get('reason') == 'valid':
                        state = 'both_approved_valid'
                    elif verdict.get('status') == 2:
                        state = 'wb_rejected'
                    else:
                        state = 'wb_pending'
            edge = (offer, typ, key)
            row = {'offer_id': offer, 'brand': brand, 'number': number, 'type': typ, 'state': state}
            prior = edges.get(edge)
            if prior and prior['state'] != state:
                row['state'] = 'conflicting_duplicate_ozon_evidence'
            edges[edge] = row
        if active_pending:
            pending.append({'certificate_id': cert['certificate_id'], 'number': number,
                            'status': cert['status_code'], 'active_pending_bindings': len(active_pending), 'targets': active_pending})
    states = collections.Counter(r['state'] for r in edges.values())
    brands = collections.defaultdict(collections.Counter)
    doc_states = collections.defaultdict(collections.Counter)
    offer_states = collections.defaultdict(collections.Counter)
    for (offer, typ, key), row in edges.items():
        brands[row['brand']][row['state']] += 1
        doc_states[(typ, key)][row['state']] += 1
        offer_states[offer][row['state']] += 1
    result = {'checked_at': now(), 'snapshot_checked_at': {'products': products['checked_at'],
              'ozon_documents': certificates['checked_at'], 'wb_cards': cards['checked_at']},
              'active_ozon_products': len(products['products']), 'wb_cards': len(cards['cards']),
              'ozon_document_records': len(certificates['certificates']),
              'ozon_document_statuses': dict(collections.Counter(c['status_code'] for c in certificates['certificates'])),
              'ozon_current_approved_eaeu_records': sum(c['status_code'] == 'approved'
                and c.get('accordance_type_code') == 'EAEU' and c.get('type_code') in OZON_TO_WB_TYPE
                and valid_dates(c.get('issue_date'), c.get('expire_date')) for c in certificates['certificates']),
              'unique_approved_current_edges': len(edges), 'edge_states': dict(states),
              'documents_with_at_least_one_both_valid_edge': sum(bool(s['both_approved_valid']) for s in doc_states.values()),
              'documents_all_compared_approved_edges_both_valid': sum(set(s) == {'both_approved_valid'} for s in doc_states.values()),
              'offers_with_at_least_one_both_valid_edge': sum(bool(s['both_approved_valid']) for s in offer_states.values()),
              'offers_all_compared_approved_edges_both_valid': sum(set(s) == {'both_approved_valid'} for s in offer_states.values()),
              'unique_offers_missing_wb_card': sum('missing_or_ambiguous_wb_card' in s for s in offer_states.values()),
              'brands': {k: dict(v) for k, v in brands.items()}, 'pending_ozon_records': pending,
              'pending_ozon_active_binding_count': sum(p['active_pending_bindings'] for p in pending),
              'problems': [r for r in edges.values() if r['state'] not in ('both_approved_valid', 'wb_pending')],
              'limitations': 'Full compared approved Ozon bindings only; missing source documents and nonapproved bindings remain outside this successful coverage. Document counts do not prove coverage of all required source products.'}
    atomic(BASE / 'all_found_bulk_status_audit_20261014.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('problems', 'pending_ozon_records')}, ensure_ascii=False))
    print('pending_records', json.dumps([{k: v for k, v in p.items() if k != 'targets'} for p in pending], ensure_ascii=False))


if __name__ == '__main__':
    main()
