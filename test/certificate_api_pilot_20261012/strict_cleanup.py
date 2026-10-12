"""Strict cleanup of explicitly reviewed proofs; fresh API readback precedes every execution."""
import datetime
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from api_client import BASE, ROOT, Client, digest, now, save
from pilot_upload import norm

FERON = Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
ROOTS = [ROOT / 'output_to_user/certificates', FERON]


def build_plan():
    proof_path = BASE / 'proof_repair_verified.json'
    proof = json.loads(proof_path.read_text())
    cases = proof['verified']
    if not cases or len(cases) > 3:
        raise RuntimeError('This pilot is limited to three explicitly reviewed documents')
    client = Client()
    accepted, blocked = [], []
    for case in cases:
        group = case['group']
        if not case.get('all_known_bindings_accounted_for') or not case.get('number_source') or not case.get('applicability_evidence'):
            raise RuntimeError('Manual identity/applicability/coverage proof missing')
        if group.get('feron_original_sha256') != group['sha256']:
            raise RuntimeError('Original source SHA evidence mismatch')
        if {r['offer'] for r in case['all_workbook_rows_for_source_filename']} != {b['offer_id'] for b in group['bindings']}:
            raise RuntimeError('Incomplete workbook target set')
        if datetime.date.fromisoformat(case['printed_valid_until']) <= datetime.datetime.now(ZoneInfo('Asia/Dubai')).date():
            raise RuntimeError('Document expired')
        certificate = client.call('ozon', '/v1/product/certificate/info', {'certificate_number': case['printed_number']})['result']
        if (norm(certificate['certificate_number']) != norm(case['printed_number']) or certificate['type_code'] != 'declaration'
                or certificate['status_code'] != 'approved' or certificate['issue_date'][:10] != case['printed_registration_date']
                or certificate['expire_date'][:10] != case['printed_valid_until']):
            blocked.append({'number': case['printed_number'], 'reason': 'Ozon certificate not finally approved or metadata mismatch'})
            continue
        live_bindings = client.ozon_bindings(certificate['certificate_id'])
        approved = {(str(b['sku']), str(b['product_id'])) for b in live_bindings if b['product_status_code'] == 'approved'}
        required = {(s, i) for b in group['bindings'] for s in b['ozon_skus'] for i in b['ozon_product_ids']}
        if not required or not required <= approved:
            blocked.append({'number': case['printed_number'], 'reason': 'Missing or pending Ozon target bindings'})
            continue
        wb_readback = []
        issue = None
        for binding in group['bindings']:
            offer = binding['offer_id']
            items = client.call('ozon', '/v3/product/info/list', {'offer_id': [offer]})['items']
            expected = {(s, i) for s in binding['ozon_skus'] for i in binding['ozon_product_ids']}
            actual = {(str(p['sku']), str(p['id'])) for p in items if p['offer_id'] == offer}
            if actual != expected:
                issue = 'Live Ozon offer/ID/SKU mapping differs: ' + offer
                break
            cards = client.wb_cards(offer)
            if not cards:
                issue = 'No WB card: ' + offer
                break
            for card in cards:
                docs = card.get('documents') or {}
                overall = docs.get('overallVerdict') or {}
                exact = [d for d in docs.get('items', []) if d.get('type') == 2 and norm(d.get('number')) == norm(case['printed_number'])]
                valid = [d for d in exact if d.get('startDate', '')[:10] == case['printed_registration_date']
                         and d.get('endDate', '')[:10] == case['printed_valid_until'] and (d.get('verdict') or {}).get('verified') is True
                         and (d.get('verdict') or {}).get('status') == 1]
                if (docs.get('excludeDocuments') is not False or overall.get('isFullyChecked') is not True or overall.get('status') != 1 or not valid):
                    issue = 'WB document/card verification incomplete or failed: ' + offer
                    break
                wb_readback.append({'vendorCode': offer, 'nmID': card['nmID'], 'document': valid[0], 'overallVerdict': overall})
            if issue:
                break
        if issue:
            blocked.append({'number': case['printed_number'], 'reason': issue})
            continue
        for file in group['files']:
            path = Path(file['path'])
            if not path.is_absolute() or path.resolve() != path or not any(path.is_relative_to(root) for root in ROOTS):
                raise RuntimeError('Unsafe source path: ' + str(path))
            if path.suffix.lower() not in ('.pdf', '.jpg', '.jpeg', '.png') or not path.is_file():
                raise RuntimeError('Unexpected/missing source file: ' + str(path))
            if digest(path) != group['sha256'] or path.stat().st_size != file['size']:
                raise RuntimeError('Source changed since reviewed evidence: ' + str(path))
        accepted.append({'number': case['printed_number'], 'sha256': group['sha256'], 'files': group['files'],
                         'source_proof': {'identity': case['number_source'], 'applicability': case['applicability_evidence'],
                                          'workbook_rows': case['all_workbook_rows_for_source_filename']},
                         'ozon_certificate': certificate, 'ozon_required_pairs': sorted(required),
                         'ozon_readback': live_bindings, 'wb_readback': wb_readback, 'verified_at': now()})
        print('Confirmed', case['printed_number'], 'files', len(group['files']), 'offers', len(group['bindings']), flush=True)
    result = {'checked_at': now(), 'proof_file_sha256': digest(proof_path), 'accepted': accepted, 'blocked': blocked,
              'summary': {'documents': len(accepted), 'files': sum(len(g['files']) for g in accepted),
                          'bytes': sum(f['size'] for g in accepted for f in g['files']),
                          'ozon_target_pairs': sum(len(g['ozon_required_pairs']) for g in accepted),
                          'wb_cards': sum(len(g['wb_readback']) for g in accepted)}}
    return result


def main(execute=False):
    if execute and ((BASE / 'strict_cleanup_result.json').exists() or (BASE / 'strict_cleanup_journal.jsonl').exists()):
        raise RuntimeError('Cleanup already attempted; recover from journal rather than replay')
    plan = build_plan()
    save('strict_cleanup_plan.json', plan)
    print(json.dumps(plan['summary']), flush=True)
    if not execute or not plan['accepted']:
        return
    if digest(BASE / 'proof_repair_verified.json') != plan['proof_file_sha256']:
        raise RuntimeError('Reviewed proof changed during preflight')
    timestamp = datetime.datetime.now(ZoneInfo('Asia/Dubai')).strftime('%Y-%m-%d_%H%M%S')
    trash = Path.home() / '.Trash' / ('Подтверждены_на_Ozon_и_WB_' + timestamp)
    trash.mkdir(parents=True, exist_ok=False)
    moved = []
    with (BASE / 'strict_cleanup_journal.jsonl').open('x') as journal:
        for group in plan['accepted']:
            for file in group['files']:
                source = Path(file['path'])
                root = next(root for root in ROOTS if source.is_relative_to(root))
                label = 'FERON' if root == FERON else 'Checksheets'
                destination = trash / label / source.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != source or source.stat().st_size != file['size'] or digest(source) != group['sha256'] or destination.exists():
                    raise RuntimeError('Source changed before move or target exists')
                entry = {'source': str(source), 'trash_path': str(destination), 'number': group['number'],
                         'sha256': group['sha256'], 'size': file['size'], 'certificate_id': group['ozon_certificate']['certificate_id'],
                         'ozon_target_pairs': group['ozon_required_pairs'], 'wb_nmids': [c['nmID'] for c in group['wb_readback']]}
                journal.write(json.dumps({**entry, 'phase': 'prepared', 'at': now()}, ensure_ascii=False) + '\n')
                journal.flush()
                os.fsync(journal.fileno())
                os.rename(source, destination)
                if source.exists() or digest(destination) != group['sha256'] or destination.stat().st_size != file['size']:
                    raise RuntimeError('Move verification failed; see prepared journal entry')
                journal.write(json.dumps({**entry, 'phase': 'verified_moved', 'at': now()}, ensure_ascii=False) + '\n')
                journal.flush()
                os.fsync(journal.fileno())
                moved.append(entry)
    result = {'completed_at': now(), 'trash_directory': str(trash), 'summary': plan['summary'],
              'verified_moved_files': len(moved), 'moved': moved, 'blocked': plan['blocked']}
    save('strict_cleanup_result.json', result)
    print(json.dumps({'verified_moved_files': len(moved), 'trash_directory': str(trash)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main('--execute' in sys.argv)
