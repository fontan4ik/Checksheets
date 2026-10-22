"""Move only hash-mapped certificate files with fresh final approval on Ozon and WB."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from api_client import BASE, ROOT, now, save
from build_bulk_cleanup_candidates_20261012 import norm

FERON = Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
ROOTS = [ROOT / 'output_to_user/certificates', BASE, FERON]
INPUTS = {
    'candidates': BASE / 'bulk_cleanup_candidates_20261012.json',
    'ozon': BASE / 'ozon_live.json',
    'products': BASE / 'ozon_products_live.json',
    'wb': BASE / 'wb_bulk_cleanup_targets_full_20261012.json',
}
PLAN_NAME = 'cleanup_all_fully_applied_20261012_plan.json'
RESULT_NAME = 'cleanup_all_fully_applied_20261012_result.json'
JOURNAL_NAME = 'cleanup_all_fully_applied_20261012_journal.jsonl'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def age_minutes(value: str) -> float:
    timestamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (dt.datetime.now(dt.timezone.utc) - timestamp.astimezone(dt.timezone.utc)).total_seconds() / 60


def live_inputs() -> dict:
    data = {key: json.loads(path.read_text()) for key, path in INPUTS.items()}
    if any(not item.get('complete') for item in data.values()):
        raise RuntimeError('All candidate, Ozon, product, and WB reads must be complete')
    if age_minutes(data['ozon'].get('checked_at', '')) > 30:
        raise RuntimeError('Ozon certificate/binding snapshot is older than 30 minutes')
    if age_minutes(data['products'].get('checked_at', '')) > 30:
        raise RuntimeError('Ozon product identity snapshot is older than 30 minutes')
    if age_minutes(data['wb'].get('checked_at', '')) > 30:
        raise RuntimeError('WB full-card snapshot is older than 30 minutes')
    return data


def build_plan() -> dict:
    data = live_inputs()
    cert_by_number = defaultdict(list)
    for cert in data['ozon'].get('certificates') or []:
        cert_by_number[norm(cert.get('certificate_number'))].append(cert)
    product_by_offer = {str(x.get('offer_id')): x for x in data['products'].get('products') or []}
    card_by_offer = data['wb'].get('cards_by_offer') or {}
    accepted, blocked = [], []
    reason_counts = Counter()

    for item in data['candidates'].get('candidate_groups') or []:
        number = item['number']
        key = norm(number)
        source = item['source_proof']
        required = {(str(product_id), str(sku))
                    for binding in source.get('bindings') or []
                    for product_id in binding.get('ozon_product_ids') or []
                    for sku in binding.get('ozon_skus') or []}
        records = cert_by_number.get(key) or []
        record_ids = {str(x.get('certificate_id')) for x in records}
        expected_ids = {str(x) for x in item.get('certificate_ids') or []}
        problem = None
        if not required or len(required) != item.get('target_pairs'):
            problem = 'local target pair count is incomplete or duplicated'
        elif not records or record_ids != expected_ids:
            problem = 'live Ozon certificate IDs differ from the reviewed local/live map'
        elif any(x.get('status_code') != 'approved' or x.get('accordance_type_code') != 'EAEU'
                 or str(x.get('issue_date', ''))[:10] != item['issue_date']
                 or str(x.get('expire_date', ''))[:10] != item['expire_date'] for x in records):
            problem = 'Ozon certificate is not finally approved with exact EAEU metadata'
        else:
            bindings = [b for cert in records for b in cert.get('live_bindings') or []]
            all_pairs = [(str(b.get('product_id')), str(b.get('sku'))) for b in bindings]
            approved_pairs = {(str(b.get('product_id')), str(b.get('sku'))) for b in bindings
                              if b.get('product_status_code') == 'approved'}
            if (len(all_pairs) != len(set(all_pairs)) or set(all_pairs) != required
                    or approved_pairs != required or len(all_pairs) != len(required)):
                problem = 'Ozon approved binding set has missing, pending, declined, extra, or duplicate products'

        wb_type = None
        if not problem:
            type_codes = {str(x.get('type_code', '')).lower() for x in records}
            wb_type = 2 if type_codes == {'declaration'} else 1 if type_codes == {'certificate_of_conformity'} else None
            if wb_type != int(item['type']):
                problem = 'Ozon document type differs from the reviewed WB type'

        product_readback = []
        wb_readback = []
        if not problem:
            targets_by_offer = defaultdict(list)
            for target in item.get('targets') or []:
                targets_by_offer[str(target['offer_id'])].append(target)
            for offer, targets in targets_by_offer.items():
                expected_ids_for_offer = {(str(t['product_id']), str(t['sku'])) for t in targets}
                live_product = product_by_offer.get(offer)
                actual_identity = {(str(live_product.get('product_id')), str(live_product.get('sku')))} if live_product else set()
                if (not live_product or live_product.get('is_archived') is not False
                        or actual_identity != expected_ids_for_offer):
                    problem = f'Current Ozon offer/product identity changed for {offer}'
                    break
                product_readback.append({'offer_id': offer, **live_product})

                card = card_by_offer.get(offer)
                if (not card or card.get('vendorCode') != offer
                        or str(card.get('nmID')) != str(targets[0]['wb_nmID'])):
                    problem = f'Current exact WB card identity changed or is missing for {offer}'
                    break
                documents = card.get('documents') or {}
                exact = [x for x in documents.get('items') or []
                         if int(x.get('type', 0)) == wb_type and norm(x.get('number')) == key
                         and str(x.get('startDate', ''))[:10] == item['issue_date']
                         and str(x.get('endDate', ''))[:10] == item['expire_date']]
                if (len(exact) != 1 or documents.get('excludeDocuments') is not False
                        or (exact[0].get('verdict') or {}).get('verified') is not True
                        or (exact[0].get('verdict') or {}).get('status') != 1
                        or (exact[0].get('verdict') or {}).get('reason') != 'valid'
                        or (documents.get('overallVerdict') or {}).get('isFullyChecked') is not True
                        or (documents.get('overallVerdict') or {}).get('status') != 1):
                    problem = f'WB document or overall card verdict is not finally valid for {offer}'
                    break
                wb_readback.append({'offer_id': offer, 'nmID': card['nmID'],
                                    'document': exact[0], 'overallVerdict': documents['overallVerdict']})

        files = item['source_files']
        if not problem:
            for file in files:
                path = Path(file['path'])
                if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
                        or not any(path.is_relative_to(root) for root in ROOTS)
                        or path.suffix.lower() not in {'.pdf', '.jpg', '.jpeg', '.png'}
                        or not path.is_file() or path.stat().st_size != file['size']
                        or sha(path) != item['source_sha256']):
                    problem = f'Local source/hash proof changed: {path}'
                    break

        if problem:
            blocked.append({'number': number, 'source_sha256': item['source_sha256'], 'reason': problem})
            reason_counts[problem.split(' for ')[0]] += 1
            continue
        accepted.append({'number': number, 'type': wb_type, 'issue_date': item['issue_date'],
                         'expire_date': item['expire_date'], 'source_sha256': item['source_sha256'],
                         'certificate_ids': sorted(record_ids), 'required_ozon_pairs': sorted(required),
                         'source_proof': source, 'local_files': files,
                         'ozon_readback': records, 'ozon_bindings': bindings,
                         'ozon_products_readback': product_readback, 'wb_readback': wb_readback,
                         'verified_at': now()})

    return {'checked_at': now(), 'candidate_plan_checked_at': data['candidates']['checked_at'],
            'ozon_checked_at': data['ozon']['checked_at'], 'ozon_products_checked_at': data['products']['checked_at'],
            'wb_checked_at': data['wb']['checked_at'], 'accepted': accepted, 'blocked': blocked,
            'summary': {'documents': len(accepted),
                        'files': sum(len(x['local_files']) for x in accepted),
                        'bytes': sum(f['size'] for x in accepted for f in x['local_files']),
                        'ozon_product_document_pairs': sum(len(x['required_ozon_pairs']) for x in accepted),
                        'wb_cards': sum(len(x['wb_readback']) for x in accepted),
                        'blocked_documents': len(blocked), 'blocked_reasons': dict(reason_counts)}}


def execute(plan: dict) -> None:
    trash = Path.home() / '.Trash' / ('Документы_подтверждены_на_Ozon_и_WB_' +
                                      dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    trash.mkdir(parents=True, exist_ok=False)
    journal = BASE / JOURNAL_NAME
    moved = []
    with journal.open('x') as stream:
        for group in plan['accepted']:
            for file in group['local_files']:
                source = Path(file['path'])
                root = next(root for root in ROOTS if source.is_relative_to(root))
                destination = trash / file['label'] / file['relative_path']
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (not source.is_file() or source.is_symlink() or source.resolve() != source
                        or source.stat().st_size != file['size'] or sha(source) != group['source_sha256']
                        or destination.exists()):
                    raise RuntimeError(f'Local certificate changed immediately before move: {source}')
                entry = {'source': str(source), 'trash_path': str(destination), 'number': group['number'],
                         'source_sha256': group['source_sha256'], 'size': file['size'],
                         'certificate_ids': group['certificate_ids'],
                         'ozon_product_document_pairs': len(group['required_ozon_pairs']),
                         'wb_nmids': [x['nmID'] for x in group['wb_readback']]}
                stream.write(json.dumps({**entry, 'phase': 'prepared', 'at': now()}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
                os.rename(source, destination)
                if (source.exists() or destination.stat().st_size != file['size']
                        or sha(destination) != group['source_sha256']):
                    raise RuntimeError(f'Local certificate move verification failed: {destination}')
                stream.write(json.dumps({**entry, 'phase': 'verified_moved', 'at': now()}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
                moved.append(entry)
    result = {'completed_at': now(), 'trash_directory': str(trash), 'summary': plan['summary'],
              'verified_moved_files': len(moved), 'moved': moved, 'blocked': plan['blocked']}
    save(RESULT_NAME, result)
    print(json.dumps({'verified_moved_files': len(moved), 'trash_directory': str(trash),
                      'documents': plan['summary']['documents'], 'ozon_pairs': plan['summary']['ozon_product_document_pairs'],
                      'wb_cards': plan['summary']['wb_cards']}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute and ((BASE / RESULT_NAME).exists() or (BASE / JOURNAL_NAME).exists()):
        raise RuntimeError('Bulk cleanup already attempted; recover from the write-ahead journal before retrying')
    plan = build_plan()
    save(PLAN_NAME, plan)
    print(json.dumps(plan['summary'], ensure_ascii=False))
    if args.execute and plan['accepted']:
        execute(plan)


if __name__ == '__main__':
    main()
