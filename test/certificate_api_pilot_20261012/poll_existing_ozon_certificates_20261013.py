from __future__ import annotations
import collections, json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now, save
from prepare_feron_01381 import bindings

CASES = [
    ('feron_00909_ozon_verification.json', 'ЕАЭС N RU Д-CN.РА10.В.00909/23'),
    ('feron_01324_ozon_verification.json', None),
    ('feron_01854_verification_20261012.json', 'ЕАЭС RU С-CN.НА83.В.01854/22'),
    ('feron_02773_live_verification.json', None),
    ('feron_04998_ozon_verification.json', None),
    ('feron_53525_bind_execution_20261012.json', None),
    ('feron_53551_ozon_verification.json', None),
    ('feron_54301_ozon_verification.json', None),
    ('feron_87126_ozon_verification.json', None),
    ('feron_87137_ozon_verification.json', None),
    ('feron_87165_ozon_verification.json', None),
    ('feron_87180_ozon_verification.json', None),
]

def baseline(path: str):
    d = json.loads((BASE / path).read_text(encoding='utf-8'))
    if path == 'feron_53525_bind_execution_20261012.json':
        return d, str(d['certificate_id']), str(d['ozon_number']), int(d['final_binding_count']), None
    if path == 'feron_01854_verification_20261012.json':
        o = d['ozon']
        return d, str(o['certificate_id']), str(d['certificate']['number_from_scan_and_wb']), int(o['actual_bindings_count']), None
    if path == 'feron_02773_live_verification.json':
        o = d['ozon']
        return d, str(o['certificate_id']), str(d['certificate']['canonical_number']), int(o['bound_sku_count']), None
    cid = str(d.get('certificate_id') or d.get('ozon', {}).get('certificate_id'))
    number = (d.get('stored_number') or d.get('ozon_stored_number') or d.get('number')
              or d.get('ozon', {}).get('stored_number'))
    rows = d.get('bindings') or d.get('live_bindings') or []
    if not isinstance(rows, list):
        rows = []
    if not number and d.get('certificate_info'):
        number = d['certificate_info'].get('certificate_number')
    if not number and d.get('certificate', {}).get('number_from_scan_and_wb'):
        number = d['certificate']['number_from_scan_and_wb']
    if not number and d.get('ozon', {}).get('certificate_number'):
        number = d['ozon']['certificate_number']
    expected_count = len(rows) if rows else int(d.get('binding_count') or d.get('live_binding_count') or d.get('target_count') or d.get('target_skus') or 0)
    expected_ids = {str(x.get('sku')): str(x.get('product_id')) for x in rows
                    if x.get('sku') is not None and x.get('product_id') is not None}
    return d, cid, str(number), expected_count, expected_ids or None

client = Client()
result = {'checked_at_utc': now(), 'method': 'read-only certificate info + complete last_id-paginated binding readback', 'records': []}
for path, override_number in CASES:
    d, cid, number, expected_count, expected_ids = baseline(path)
    if override_number: number = override_number
    if cid in {'None', ''} or not number:
        result['records'].append({'source': path, 'outcome': 'baseline_missing_identity'})
        continue
    try:
        info = client.call('ozon', '/v1/product/certificate/info', {'certificate_number': number}).get('result')
    except RuntimeError as exc:
        result['records'].append({'source': path, 'certificate_id': str(cid), 'number_queried': number, 'outcome': 'info_lookup_failed', 'error': str(exc)})
        save('feron_existing_ozon_status_poll_20261013.json', result)
        print(json.dumps(result['records'][-1], ensure_ascii=False), flush=True)
        continue
    if not isinstance(info, dict):
        raise RuntimeError(f'Unexpected certificate info for {path}: {type(info).__name__}')
    live = bindings(client, int(cid))
    status_counts = collections.Counter(str(x.get('product_status_code') or 'MISSING') for x in live)
    live_ids = {str(x.get('sku')): str(x.get('product_id')) for x in live if x.get('sku') is not None and x.get('product_id') is not None}
    missing_ids = sorted(set(expected_ids or {}) - set(live_ids)) if expected_ids else None
    extra_ids = sorted(set(live_ids) - set(expected_ids or {})) if expected_ids else None
    id_mismatches = ([{'sku': sku, 'expected_product_id': expected_ids[sku], 'live_product_id': live_ids.get(sku)}
                      for sku in sorted(set(expected_ids or {}) & set(live_ids)) if expected_ids[sku] != live_ids.get(sku)]
                     if expected_ids else None)
    record = {
        'source': path, 'certificate_id': str(cid), 'number_queried': number,
        'live_number': info.get('certificate_number'), 'record_status': info.get('status_code'),
        'rejection_reason_code': info.get('rejection_reason_code'),
        'verification_comment': info.get('verification_comment'),
        'live_issue_date': info.get('issue_date'), 'live_expire_date': info.get('expire_date'),
        'expected_binding_count_from_prior_audit': expected_count,
        'live_binding_count': len(live), 'binding_status_counts': dict(status_counts),
        'binding_count_matches_prior_audit': len(live) == expected_count,
        'identity_mapping_checked': expected_ids is not None,
        'missing_skus_vs_prior_audit': missing_ids,
        'unexpected_skus_vs_prior_audit': extra_ids,
        'product_id_mismatches_vs_prior_audit': id_mismatches,
        'all_live_bindings_approved': bool(live) and set(status_counts) == {'approved'},
        'bindings': [{'sku': str(x.get('sku')), 'product_id': str(x.get('product_id')),
                      'status': x.get('product_status_code')} for x in live],
    }
    result['records'].append(record)
    save('feron_existing_ozon_status_poll_20261013.json', result)
    print(json.dumps({k:v for k,v in record.items() if k != 'bindings'}, ensure_ascii=False), flush=True)
save('feron_existing_ozon_status_poll_20261013.json', result)
print('SAVED', BASE / 'feron_existing_ozon_status_poll_20261013.json', flush=True)
