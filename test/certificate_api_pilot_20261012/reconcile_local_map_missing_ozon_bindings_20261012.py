"""Plan and safely add only missing bindings to existing approved Ozon records."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from api_client import BASE, Client, now, save
from build_bulk_cleanup_candidates_20261012 import norm

LOCAL_MAP = BASE.parents[1] / 'test/certificate_cleanup_20261006/local_map.json'
OZON = BASE / 'ozon_live.json'
PRODUCTS = BASE / 'ozon_products_live.json'
PLAN_NAME = 'ozon_local_map_missing_bindings_20261012_plan.json'
EXEC_NAME = 'ozon_local_map_missing_bindings_20261012_execution.json'


def build_plan() -> dict:
    local = json.loads(LOCAL_MAP.read_text())
    ozon = json.loads(OZON.read_text())
    products = json.loads(PRODUCTS.read_text())
    if not ozon.get('complete') or not products.get('complete'):
        raise RuntimeError('Complete local source map and live Ozon snapshots are required')
    products_by_offer = {str(x.get('offer_id')): x for x in products.get('products') or []}
    records_by_number = defaultdict(list)
    for record in ozon.get('certificates') or []:
        records_by_number[norm(record.get('certificate_number'))].append(record)

    actions, blocked = [], []
    reasons = Counter()
    seen_ids = set()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for group in local.get('groups') or []:
        if not group.get('eligible_for_live_comparison') or group.get('issues'):
            reasons['local_source_or_applicability_proof_ineligible'] += 1
            continue
        numbers = {norm(x) for x in group.get('document_numbers') or [] if x}
        if len(numbers) != 1:
            reasons['legal_document_number_ambiguous'] += 1
            continue
        records = records_by_number.get(next(iter(numbers)), [])
        if len(records) != 1:
            reasons['no_unique_live_ozon_record'] += 1
            continue
        record = records[0]
        if (record.get('status_code') != 'approved' or record.get('accordance_type_code') != 'EAEU'
                or record.get('type_code') not in {'declaration', 'certificate_of_conformity'}
                or str(record.get('expire_date', ''))[:10] < today
                or str(record.get('issue_date', ''))[:10] > today):
            reasons['ozon_record_not_current_approved_eaeu'] += 1
            continue

        required = set()
        offer_pairs = defaultdict(set)
        identity_error = None
        for binding in group.get('bindings') or []:
            offer = str(binding.get('offer_id') or '')
            skus = [str(x) for x in binding.get('ozon_skus') or []]
            pids = [str(x) for x in binding.get('ozon_product_ids') or []]
            if not offer or not skus or not pids:
                identity_error = 'local binding row lacks offer/Product ID/SKU'
                break
            for sku in skus:
                for pid in pids:
                    pair = (pid, sku)
                    required.add(pair)
                    offer_pairs[offer].add(pair)
            live = products_by_offer.get(offer)
            expected = {(pid, sku) for sku in skus for pid in pids}
            actual = {(str(live.get('product_id')), str(live.get('sku')))} if live else set()
            if not live or live.get('is_archived') is not False or actual != expected:
                identity_error = f'current Ozon offer identity differs for {offer}'
                break
        if identity_error or not required:
            reasons[identity_error or 'local_target_set_empty'] += 1
            continue

        source_hashes = set(group.get('expected_sha256s') or [])
        if (source_hashes and source_hashes != {group.get('sha256')}
                or (not source_hashes and group.get('feron_original_sha256') != group.get('sha256'))):
            reasons['source_checksum_proof_missing_or_conflicting'] += 1
            continue
        source_present = False
        for file in group.get('files') or []:
            path = Path(file['path'])
            if (path.is_absolute() and path.exists() and not path.is_symlink()
                    and path.stat().st_size == file.get('size')
                    and hashlib.sha256(path.read_bytes()).hexdigest() == group['sha256']):
                source_present = True
                break
        if not source_present:
            reasons['no_current_local_source_file'] += 1
            continue

        bindings = record.get('live_bindings') or []
        if len(bindings) != int(record.get('live_binding_count', len(bindings))):
            reasons['live_binding_count_mismatch'] += 1
            continue
        by_pair = defaultdict(list)
        for live in bindings:
            by_pair[(str(live.get('product_id')), str(live.get('sku')))].append(live)
        if any(len(rows) != 1 for rows in by_pair.values()):
            reasons['duplicate_live_ozon_product_pair'] += 1
            continue
        extra = set(by_pair) - required
        if extra:
            reasons['live_ozon_binding_outside_local_target_set'] += 1
            continue
        if any((rows[0].get('product_status_code') != 'approved') for rows in by_pair.values()):
            reasons['existing_target_binding_not_approved'] += 1
            continue
        missing = required - set(by_pair)
        if not missing:
            reasons['already_fully_bound_on_ozon'] += 1
            continue
        certificate_id = str(record.get('certificate_id'))
        if certificate_id in seen_ids:
            reasons['duplicate_candidate_certificate_id'] += 1
            continue
        seen_ids.add(certificate_id)
        sku_to_pair = defaultdict(list)
        for product_id, sku in sorted(missing):
            sku_to_pair[sku].append(product_id)
        if any(len(pids) != 1 for pids in sku_to_pair.values()):
            reasons['missing_sku_maps_to_multiple_product_ids'] += 1
            continue
        actions.append({'number': record['certificate_number'], 'certificate_id': record['certificate_id'],
                        'type_code': record['type_code'], 'accordance_type_code': record['accordance_type_code'],
                        'status_code': record['status_code'], 'issue_date': str(record['issue_date'])[:10],
                        'expire_date': str(record['expire_date'])[:10], 'source_sha256': group['sha256'],
                        'source_files': group.get('files') or [],
                        'target_pair_count': len(required), 'already_approved_pairs': len(by_pair),
                        'missing_pairs': [{'product_id': pid, 'sku': sku,
                                           'offer_id': next(offer for offer, pairs in offer_pairs.items()
                                                            if (pid, sku) in pairs)}
                                          for pid, sku in sorted(missing)],
                        'live_bindings_before': bindings,
                        'source_proof': {'document_numbers': group.get('document_numbers'),
                                         'bindings': group.get('bindings'), 'sources': group.get('sources')}})

    return {'checked_at': now(), 'ozon_checked_at': ozon.get('checked_at'),
            'products_checked_at': products.get('checked_at'), 'local_map_sha256': __import__('hashlib').sha256(LOCAL_MAP.read_bytes()).hexdigest(),
            'actions': actions, 'blocked_summary': dict(reasons), 'blocked_documents': blocked,
            'summary': {'records_to_bind': len(actions),
                        'missing_product_bindings': sum(len(x['missing_pairs']) for x in actions),
                        'target_pairs': sum(x['target_pair_count'] for x in actions),
                        'missing_skus': sum(len({p['sku'] for p in x['missing_pairs']}) for x in actions),
                        'blocked_or_skipped_groups': sum(reasons.values()), 'skip_reasons': dict(reasons)}}


def execute(plan: dict) -> None:
    run = {'started_at': now(), 'state': 'prepared', 'actions': [], 'summary': plan['summary']}
    save(EXEC_NAME, run)
    client = Client()
    for action in plan['actions']:
        cert_id = int(action['certificate_id'])
        info_body = client.call('ozon', '/v1/product/certificate/info',
                                {'certificate_number': action['number']})
        info = info_body.get('result')
        if (not isinstance(info, dict) or str(info.get('certificate_id')) != str(cert_id)
                or norm(info.get('certificate_number')) != norm(action['number'])
                or info.get('status_code') != 'approved'
                or info.get('accordance_type_code') != 'EAEU'
                or info.get('type_code') != action['type_code']
                or str(info.get('issue_date', ''))[:10] != action['issue_date']
                or str(info.get('expire_date', ''))[:10] != action['expire_date']):
            run.update({'state': 'stopped_info_mismatch', 'stopped_number': action['number'], 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Live Ozon certificate info changed; no bind was sent for this record')

        current = client.ozon_bindings(cert_id)
        expected = {(str(x['product_id']), str(x['sku'])) for x in action['missing_pairs']}
        expected |= {(str(x['product_id']), str(x['sku'])) for x in action['live_bindings_before']}
        by_pair = defaultdict(list)
        for row in current:
            by_pair[(str(row.get('product_id')), str(row.get('sku')))].append(row)
        if (set(by_pair) - expected or any(len(rows) != 1 for rows in by_pair.values())
                or any(rows[0].get('product_status_code') != 'approved' for rows in by_pair.values())):
            run.update({'state': 'stopped_binding_drift', 'stopped_number': action['number'],
                        'live_bindings': current, 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Live Ozon binding set changed or has a non-approved pair; stopped safely')

        missing_pairs = set(expected) - set(by_pair)
        missing_skus = sorted({sku for _, sku in missing_pairs})
        if not missing_pairs:
            run['actions'].append({'number': action['number'], 'certificate_id': cert_id,
                                   'outcome': 'already_complete_on_fresh_read', 'bindings': current})
            save(EXEC_NAME, run)
            continue
        if len(missing_skus) != len(missing_pairs):
            raise RuntimeError('Missing SKU list is ambiguous; no bind sent')
        detail = {'number': action['number'], 'certificate_id': cert_id,
                  'missing_pairs': sorted(missing_pairs), 'missing_skus': missing_skus,
                  'phase': 'prepared', 'prepared_at': now()}
        run['actions'].append(detail)
        save(EXEC_NAME, run)
        try:
            response = client.call('ozon', '/v1/product/certificate/bind',
                                   {'certificate_id': cert_id, 'skus': missing_skus}, mutation=True)
        except Exception as exc:
            detail.update({'phase': 'uncertain', 'error_type': type(exc).__name__, 'finished_at': now()})
            run.update({'state': 'uncertain_stop', 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Bind result uncertain; reconcile fresh Ozon bindings before any retry') from None
        detail['response'] = response
        detail['phase'] = 'accepted' if response.get('result') is True else 'rejected'
        save(EXEC_NAME, run)
        if response.get('result') is not True:
            run.update({'state': 'rejected_stop', 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Ozon did not accept bind; stop and inspect the fresh state')

        final = client.ozon_bindings(cert_id)
        final_pairs = [(str(x.get('product_id')), str(x.get('sku'))) for x in final]
        final_set = set(final_pairs)
        bad_statuses = {str(x.get('product_status_code')) for x in final} - {
            'approved', 'awaiting_verification', 'background_check'}
        if len(final_pairs) != len(set(final_pairs)) or final_set != expected or bad_statuses:
            detail.update({'phase': 'accepted_but_readback_incomplete', 'final_bindings': final,
                           'finished_at': now()})
            run.update({'state': 'readback_incomplete_stop', 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Ozon bind was accepted but exact approved readback is incomplete')
        binding_states = Counter(str(x.get('product_status_code')) for x in final)
        detail.update({'phase': 'bound_readback_approved' if binding_states == {'approved': len(expected)}
                       else 'bound_readback_waiting_for_ozon_verification',
                       'final_binding_status_counts': dict(binding_states), 'final_bindings': final,
                       'finished_at': now()})
        save(EXEC_NAME, run)

    run.update({'state': 'all_actions_readback_present', 'finished_at': now()})
    save(EXEC_NAME, run)
    print(json.dumps({'state': run['state'], 'actions': len(run['actions']),
                      'missing_pairs_requested': sum(len(x.get('missing_pairs') or []) for x in run['actions']),
                      'binding_status_counts': dict(Counter(status for action in run['actions']
                                                             for row in action.get('final_bindings') or []
                                                             for status in [str(row.get('product_status_code'))])),
                      'finished_at': run['finished_at']}, ensure_ascii=False))


def resume(plan: dict, run: dict) -> None:
    """Reconcile accepted/incomplete requests first, then continue unattempted records."""
    if run.get('state') not in {'readback_incomplete_stop', 'all_actions_readback_present'}:
        raise RuntimeError('Only an accepted/incomplete Ozon binding run can be resumed')
    client = Client()
    prior_by_id = {str(x.get('certificate_id')): x for x in run.get('actions') or []}
    allowed = {'approved', 'awaiting_verification', 'background_check'}
    for action in plan.get('actions') or []:
        cert_id = int(action['certificate_id'])
        action_key = str(cert_id)
        info = client.call('ozon', '/v1/product/certificate/info', {'certificate_number': action['number']}).get('result')
        if (not isinstance(info, dict) or str(info.get('certificate_id')) != action_key
                or norm(info.get('certificate_number')) != norm(action['number'])
                or info.get('status_code') != 'approved' or info.get('accordance_type_code') != 'EAEU'
                or info.get('type_code') != action['type_code']
                or str(info.get('issue_date', ''))[:10] != action['issue_date']
                or str(info.get('expire_date', ''))[:10] != action['expire_date']):
            run.update({'state': 'resume_stopped_info_mismatch', 'stopped_number': action['number'], 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Fresh Ozon info differs; stopped before additional binding')

        current = client.ozon_bindings(cert_id)
        required = {(str(x['product_id']), str(x['sku'])) for x in action['missing_pairs']}
        required |= {(str(x['product_id']), str(x['sku'])) for x in action['live_bindings_before']}
        pairs = [(str(x.get('product_id')), str(x.get('sku'))) for x in current]
        by_pair = defaultdict(list)
        for row in current:
            by_pair[(str(row.get('product_id')), str(row.get('sku')))].append(row)
        if (len(pairs) != len(set(pairs)) or set(by_pair) - required
                or any(rows[0].get('product_status_code') not in allowed for rows in by_pair.values())):
            run.update({'state': 'resume_stopped_binding_drift', 'stopped_number': action['number'],
                        'live_bindings': current, 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Fresh Ozon bindings contain a duplicate, extra, declined, or unknown-status pair')

        previous = prior_by_id.get(action_key)
        missing_pairs = required - set(by_pair)
        if previous:
            # The previous request was accepted. Never repeat it; only reconcile its exact final state.
            if missing_pairs:
                run.update({'state': 'resume_stopped_accepted_pairs_missing', 'stopped_number': action['number'],
                            'missing_pairs': sorted(missing_pairs), 'live_bindings': current, 'finished_at': now()})
                save(EXEC_NAME, run)
                raise RuntimeError('Accepted Ozon bind readback still misses target pairs; no retry was made')
            counts = Counter(str(x.get('product_status_code')) for x in current)
            previous.update({'phase': 'bound_readback_approved' if counts == {'approved': len(required)}
                             else 'bound_readback_waiting_for_ozon_verification',
                             'final_binding_status_counts': dict(counts), 'final_bindings': current,
                             'reconciled_at': now()})
            save(EXEC_NAME, run)
            continue

        if not missing_pairs:
            run.setdefault('actions', []).append({'number': action['number'], 'certificate_id': cert_id,
                'outcome': 'already_complete_on_resume_read', 'final_bindings': current,
                'final_binding_status_counts': dict(Counter(str(x.get('product_status_code')) for x in current)),
                'finished_at': now()})
            prior_by_id[action_key] = run['actions'][-1]
            save(EXEC_NAME, run)
            continue
        if not missing_pairs <= {(str(x['product_id']), str(x['sku'])) for x in action['missing_pairs']}:
            run.update({'state': 'resume_stopped_new_missing_pairs', 'stopped_number': action['number'],
                        'missing_pairs': sorted(missing_pairs), 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('New missing pairs appeared after the saved plan; stopped without writing')
        missing_skus = sorted(sku for _, sku in missing_pairs)
        if len(set(missing_skus)) != len(missing_skus):
            raise RuntimeError('Missing SKUs are not unique; no bind sent')
        detail = {'number': action['number'], 'certificate_id': cert_id,
                  'missing_pairs': sorted(missing_pairs), 'missing_skus': missing_skus,
                  'phase': 'prepared', 'prepared_at': now()}
        run.setdefault('actions', []).append(detail)
        prior_by_id[action_key] = detail
        save(EXEC_NAME, run)
        try:
            response = client.call('ozon', '/v1/product/certificate/bind',
                                   {'certificate_id': cert_id, 'skus': missing_skus}, mutation=True)
        except Exception as exc:
            detail.update({'phase': 'uncertain', 'error_type': type(exc).__name__, 'finished_at': now()})
            run.update({'state': 'resume_uncertain_stop', 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Bind outcome uncertain; fresh readback required before any retry') from None
        detail['response'] = response
        detail['phase'] = 'accepted' if response.get('result') is True else 'rejected'
        save(EXEC_NAME, run)
        if response.get('result') is not True:
            run.update({'state': 'resume_rejected_stop', 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Ozon rejected the bind; inspect live state before more writes')
        final = client.ozon_bindings(cert_id)
        final_pairs = [(str(x.get('product_id')), str(x.get('sku'))) for x in final]
        if (len(final_pairs) != len(set(final_pairs)) or set(final_pairs) != required
                or any(x.get('product_status_code') not in allowed for x in final)):
            detail.update({'phase': 'accepted_but_readback_incomplete', 'final_bindings': final,
                           'finished_at': now()})
            run.update({'state': 'readback_incomplete_stop', 'finished_at': now()})
            save(EXEC_NAME, run)
            raise RuntimeError('Accepted bind did not return the exact expected target pairs')
        counts = Counter(str(x.get('product_status_code')) for x in final)
        detail.update({'phase': 'bound_readback_approved' if counts == {'approved': len(required)}
                       else 'bound_readback_waiting_for_ozon_verification',
                       'final_binding_status_counts': dict(counts), 'final_bindings': final,
                       'finished_at': now()})
        save(EXEC_NAME, run)

    all_statuses = Counter(str(row.get('product_status_code')) for action in run.get('actions') or []
                           for row in action.get('final_bindings') or [])
    run.update({'state': 'all_actions_readback_present', 'binding_status_counts': dict(all_statuses),
                'finished_at': now()})
    save(EXEC_NAME, run)
    print(json.dumps({'state': run['state'], 'actions': len(run.get('actions') or []),
                      'binding_status_counts': dict(all_statuses), 'finished_at': run['finished_at']},
                     ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.resume:
        if not (BASE / PLAN_NAME).exists() or not (BASE / EXEC_NAME).exists():
            raise RuntimeError('Saved Ozon bind plan and execution journal are required to resume')
        resume(json.loads((BASE / PLAN_NAME).read_text()), json.loads((BASE / EXEC_NAME).read_text()))
        return
    if args.execute and (BASE / EXEC_NAME).exists():
        raise RuntimeError('Ozon bind execution already exists; inspect it before any retry')
    plan = build_plan()
    save(PLAN_NAME, plan)
    print(json.dumps(plan['summary'], ensure_ascii=False))
    if args.execute and plan['actions']:
        execute(plan)


if __name__ == '__main__':
    main()
