"""Verify all local-map binding repairs against a fresh complete Ozon audit."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from api_client import BASE, now, save
from build_bulk_cleanup_candidates_20261012 import norm

PLAN = BASE / 'ozon_local_map_missing_bindings_20261012_plan.json'
LIVE = BASE / 'ozon_live.json'
OUT = 'ozon_local_map_missing_bindings_20261012_verification.json'


def main() -> None:
    plan, live = json.loads(PLAN.read_text()), json.loads(LIVE.read_text())
    if not live.get('complete'):
        raise RuntimeError('Complete fresh Ozon certificate/binding audit is required')
    by_id = {str(x.get('certificate_id')): x for x in live.get('certificates') or []}
    result_rows = []
    global_statuses = Counter()
    unresolved = []
    for action in plan.get('actions') or []:
        record = by_id.get(str(action['certificate_id']))
        if not record:
            raise RuntimeError(f'Certificate ID disappeared from Ozon list: {action["certificate_id"]}')
        expected = {(str(x['product_id']), str(x['sku'])) for x in action['missing_pairs']}
        expected |= {(str(x['product_id']), str(x['sku'])) for x in action['live_bindings_before']}
        current = record.get('live_bindings') or []
        pairs = [(str(x.get('product_id')), str(x.get('sku'))) for x in current]
        if len(pairs) != len(set(pairs)):
            raise RuntimeError(f'Duplicate live product pair for {action["number"]}')
        current_set = set(pairs)
        missing, extra = expected-current_set, current_set-expected
        statuses = Counter(str(x.get('product_status_code')) for x in current)
        global_statuses.update(statuses)
        mismatch = (norm(record.get('certificate_number')) != norm(action['number'])
                    or record.get('status_code') != 'approved'
                    or record.get('accordance_type_code') != 'EAEU'
                    or record.get('type_code') != action['type_code']
                    or str(record.get('issue_date', ''))[:10] != action['issue_date']
                    or str(record.get('expire_date', ''))[:10] != action['expire_date'])
        if missing or extra or mismatch:
            raise RuntimeError(f'Ozon record or exact pair set changed for {action["number"]}')
        declined = [x for x in current if x.get('product_status_code') == 'declined']
        pending = [x for x in current if x.get('product_status_code') in {'background_check', 'awaiting_verification'}]
        result_rows.append({'number': action['number'], 'certificate_id': action['certificate_id'],
                            'record_status': record['status_code'], 'expected_pairs': len(expected),
                            'pairs_readback': len(current), 'binding_status_counts': dict(statuses),
                            'declined_pairs': declined, 'pending_pairs': pending})
        if declined or pending:
            unresolved.append({'number': action['number'], 'declined_pairs': declined, 'pending_pairs': pending})
    result = {'checked_at': live['checked_at'], 'complete': True,
              'records_checked': len(result_rows), 'target_pairs': sum(x['expected_pairs'] for x in result_rows),
              'binding_status_counts': dict(global_statuses), 'unresolved_records': unresolved,
              'records': result_rows}
    save(OUT, result)
    print(json.dumps({k: result[k] for k in ('checked_at', 'complete', 'records_checked',
          'target_pairs', 'binding_status_counts', 'unresolved_records')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
