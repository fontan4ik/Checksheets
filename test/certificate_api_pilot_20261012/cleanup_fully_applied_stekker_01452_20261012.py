"""Move only the fully approved STEKKER 01452/23 copies to macOS Trash."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from api_client import BASE, ROOT, Client, now, save
from pilot_upload import norm

FERON = Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
NUMBER = 'ЕАЭС N RU Д-CN.PA07.B.01452/23'
PLAN = BASE / 'stekker_reconciliation_plan.json'
OZON_PRODUCTS = BASE / 'ozon_products_live.json'
RESULT_NAME = 'cleanup_stekker_01452_20261012_result.json'
PLAN_NAME = 'cleanup_stekker_01452_20261012_plan.json'
JOURNAL_NAME = 'cleanup_stekker_01452_20261012_journal.jsonl'
ROOTS = [ROOT / 'output_to_user/certificates', BASE, FERON]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def scan_exact_copies(expected_hashes: set[str]) -> list[dict]:
    found = []
    for root in ROOTS:
        if not root.exists():
            continue
        for directory, _, filenames in os.walk(root):
            for filename in filenames:
                path = Path(directory) / filename
                try:
                    if path.stat().st_size > 20_000_000:
                        continue
                    file_hash = digest(path)
                except OSError:
                    continue
                if file_hash not in expected_hashes:
                    continue
                if not path.is_absolute() or path.resolve() != path or not any(path.is_relative_to(r) for r in ROOTS):
                    raise RuntimeError(f'Unsafe duplicate source path: {path}')
                if root == ROOT / 'output_to_user/certificates':
                    label = 'output_to_user/certificates'
                elif root == BASE:
                    label = 'test/certificate_api_pilot_20261012'
                else:
                    label = 'Документы_качества_Feron'
                found.append({'path': str(path), 'label': label,
                              'relative_path': str(path.relative_to(root)),
                              'sha256': file_hash, 'size': path.stat().st_size})
    return sorted(found, key=lambda row: row['path'])


def build_plan() -> dict:
    source = json.loads(PLAN.read_text())
    products = json.loads(OZON_PRODUCTS.read_text())
    if not source.get('complete') or not products.get('complete'):
        raise RuntimeError('Complete STEKKER source map and current Ozon products are required')
    docs = [x for x in source.get('documents') or [] if norm(x.get('number')) == norm(NUMBER)]
    if len(docs) != 1:
        raise RuntimeError('Expected exactly one reviewed STEKKER 01452/23 source group')
    document = docs[0]
    targets = {(str(x['product_id']), str(x['sku'])) for x in document.get('target_pairs') or []}
    offers = {str(x['offer_id']): x for x in document.get('target_pairs') or []}
    if len(targets) != 10 or len(offers) != 10:
        raise RuntimeError('The reviewed 01452/23 target set changed; stop cleanup')

    by_offer = {str(x.get('offer_id') or ''): x for x in products.get('products') or []}
    for offer, expected in offers.items():
        live = by_offer.get(offer)
        if (not live or live.get('is_archived') is not False
                or str(live.get('product_id')) != str(expected['product_id'])
                or str(live.get('sku')) != str(expected['sku'])):
            raise RuntimeError(f'Current Ozon product identity differs for {offer}')

    listed = json.loads((BASE / 'ozon_live.json').read_text()).get('certificates') or []
    listed_match = [x for x in listed if str(x.get('certificate_id')) == '5606380']
    if len(listed_match) != 1 or norm(listed_match[0].get('certificate_number')) != norm(NUMBER):
        raise RuntimeError('Fresh Ozon listing does not uniquely identify the reviewed certificate')
    canonical_number = str(listed_match[0]['certificate_number'])
    client = Client()
    info_body = client.call('ozon', '/v1/product/certificate/info', {'certificate_number': canonical_number})
    certificate = info_body.get('result')
    if not isinstance(certificate, dict):
        raise RuntimeError('Ozon did not return certificate details')
    if (norm(certificate.get('certificate_number')) != norm(NUMBER)
            or certificate.get('type_code') != 'declaration'
            or certificate.get('accordance_type_code') != 'EAEU'
            or certificate.get('status_code') != 'approved'
            or str(certificate.get('issue_date', ''))[:10] != str(document['issue_date'])[:10]
            or str(certificate.get('expire_date', ''))[:10] != str(document['expire_date'])[:10]):
        raise RuntimeError('Ozon certificate is not finally approved with exact source metadata')
    bindings = client.ozon_bindings(certificate['certificate_id'])
    live_pairs = {(str(x.get('product_id')), str(x.get('sku'))) for x in bindings
                  if x.get('product_status_code') == 'approved'}
    all_pairs = {(str(x.get('product_id')), str(x.get('sku'))) for x in bindings}
    if (all_pairs != targets or live_pairs != targets or len(bindings) != len(targets)):
        raise RuntimeError('Ozon bindings are pending, declined, duplicated, missing, or outside the reviewed targets')

    wb_readback = []
    for offer, expected in offers.items():
        cards = client.wb_cards(offer)
        expected_nmids = [str(x) for x in expected.get('wb_nmIDs') or []]
        if (len(cards) != 1 or cards[0].get('vendorCode') != offer
                or (expected_nmids and str(cards[0].get('nmID')) not in expected_nmids)):
            raise RuntimeError(f'WB exact card is missing or changed for {offer}')
        card = cards[0]
        documents = card.get('documents') or {}
        overall = documents.get('overallVerdict') or {}
        exact = [x for x in documents.get('items') or []
                 if int(x.get('type', 0)) == 2 and norm(x.get('number')) == norm(NUMBER)
                 and str(x.get('startDate', ''))[:10] == str(document['issue_date'])[:10]
                 and str(x.get('endDate', ''))[:10] == str(document['expire_date'])[:10]
                 and (x.get('verdict') or {}).get('verified') is True
                 and (x.get('verdict') or {}).get('status') == 1
                 and (x.get('verdict') or {}).get('reason') == 'valid']
        if (len(exact) != 1 or documents.get('excludeDocuments') is not False
                or overall.get('isFullyChecked') is not True or overall.get('status') != 1):
            raise RuntimeError(f'WB exact document/card is not finally valid for {offer}')
        wb_readback.append({'offer_id': offer, 'nmID': card['nmID'], 'document': exact[0],
                            'overallVerdict': overall})

    upload = json.loads((BASE / 'stekker_reconciliation_execution.json').read_text())
    derivative = (upload.get('pdf_derivative_audit') or {}).get(NUMBER)
    if not derivative:
        raise RuntimeError('Reviewed Ozon PDF derivative proof is missing')
    originals = [document['absolute_source_file']]
    hashes = {document['source_sha256']}
    derivative_path = Path(derivative['upload_file'])
    if not derivative_path.is_absolute() or not derivative_path.is_file():
        raise RuntimeError('Uploaded PDF derivative is missing')
    if digest(derivative_path) != derivative['upload_sha256']:
        raise RuntimeError('Uploaded PDF derivative SHA-256 differs from reviewed proof')
    hashes.add(derivative['upload_sha256'])
    if digest(Path(document['absolute_source_file'])) != document['source_sha256']:
        raise RuntimeError('Original declaration SHA-256 differs from reviewed proof')

    files = scan_exact_copies(hashes)
    expected_paths = set(originals + [str(derivative_path)])
    if not expected_paths <= {x['path'] for x in files}:
        raise RuntimeError('One or more reviewed local declaration files were not found in the exact-hash scan')
    result = {
        'checked_at': now(), 'number': NUMBER, 'certificate_id': certificate['certificate_id'],
        'ozon_certificate_status': certificate['status_code'], 'ozon_target_pairs': len(targets),
        'ozon_approved_pairs': len(live_pairs), 'wb_target_cards': len(wb_readback),
        'wb_all_exact_documents_finally_valid': True, 'source_plan_checked_at': source.get('checked_at'),
        'ozon_products_checked_at': products.get('checked_at'), 'source_sha256': document['source_sha256'],
        'upload_pdf_sha256': derivative['upload_sha256'], 'files': files,
        'ozon_certificate_readback': certificate, 'ozon_binding_readback': bindings,
        'wb_readback': wb_readback,
        'rule': 'Move only exact-hash source/derivative copies after all 10 Ozon pairs and all 10 WB documents are finally approved/valid.',
    }
    return result


def execute(plan: dict) -> None:
    trash = Path.home() / '.Trash' / ('Документ_01452_23_применён_на_Ozon_и_WB_' +
                                       dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    trash.mkdir(parents=True, exist_ok=False)
    journal_path = BASE / JOURNAL_NAME
    moved = []
    with journal_path.open('x') as journal:
        for file in plan['files']:
            source = Path(file['path'])
            root = next(root for root in ROOTS if source.is_relative_to(root))
            destination = trash / file['label'] / file['relative_path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (not source.is_file() or source.resolve() != source or source.stat().st_size != file['size']
                    or digest(source) != file['sha256'] or destination.exists()):
                raise RuntimeError(f'Local certificate changed before move: {source}')
            entry = {'source': str(source), 'trash_path': str(destination), 'number': NUMBER,
                     'sha256': file['sha256'], 'size': file['size'], 'certificate_id': plan['certificate_id'],
                     'ozon_target_pairs': plan['ozon_target_pairs'], 'wb_nmids': [x['nmID'] for x in plan['wb_readback']]}
            journal.write(json.dumps({**entry, 'phase': 'prepared', 'at': now()}, ensure_ascii=False) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            os.rename(source, destination)
            if source.exists() or destination.stat().st_size != file['size'] or digest(destination) != file['sha256']:
                raise RuntimeError(f'Move verification failed: {destination}')
            journal.write(json.dumps({**entry, 'phase': 'verified_moved', 'at': now()}, ensure_ascii=False) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            moved.append(entry)
    plan.update({'completed_at': now(), 'trash_directory': str(trash),
                 'files_moved_to_trash': len(moved), 'moved': moved})
    save(RESULT_NAME, plan)
    print(json.dumps({'number': NUMBER, 'certificate_id': plan['certificate_id'],
                      'ozon_pairs': plan['ozon_approved_pairs'], 'wb_cards': plan['wb_target_cards'],
                      'files_moved_to_trash': len(moved), 'trash_directory': str(trash)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute and ((BASE / RESULT_NAME).exists() or (BASE / JOURNAL_NAME).exists()):
        raise RuntimeError('Cleanup was already attempted; recover from its journal before retrying')
    plan = build_plan()
    save(PLAN_NAME, plan)
    print(json.dumps({'number': NUMBER, 'certificate_id': plan['certificate_id'],
                      'ozon_pairs': plan['ozon_approved_pairs'], 'wb_cards': plan['wb_target_cards'],
                      'files': len(plan['files']), 'all_wb_documents_valid': plan['wb_all_exact_documents_finally_valid']},
                     ensure_ascii=False))
    if args.execute:
        execute(plan)


if __name__ == '__main__':
    main()
