#!/usr/bin/env python3
"""Delete the unique local 41382/26 PDF after current cross-platform confirmation."""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
READBACK = HERE / 'arlight_41382_crossplatform_readback_live_20261021.json'
SOURCE = ROOT / 'output_to_user/certificates/group_1/documents/arlight/F1AD317FA132F2448DFFCC8233E3D0C0.pdf'
RECEIPT = HERE / 'arlight_41382_local_pdf_cleanup_receipt_20261021.json'
JOURNAL = HERE / 'arlight_41382_local_pdf_cleanup_journal_20261021.jsonl'
EXPECTED = 'f21eee1e430f86bbef6f7570767243bf27dfe3fe7b7648e58ff7a1b87b04e193'
NUMBER = 'ЕАЭС N RU Д-RU.РА08.В.41382/26'


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if RECEIPT.exists() or JOURNAL.exists():
        raise RuntimeError('cleanup_receipt_exists_inspect_first')

    result = json.loads(READBACK.read_text(encoding='utf-8'))
    if not result.get('read_only') or result.get('number') != NUMBER or result.get('fsa_record_id') != 21895502:
        raise RuntimeError('crossplatform_readback_identity_not_confirmed')

    ozon = result.get('ozon') or {}
    wb = result.get('wildberries') or {}
    if (ozon.get('certificate_status') != 'approved'
            or ozon.get('target_count') != 339
            or ozon.get('binding_count') != 339
            or ozon.get('exact_target_binding_count') != 339
            or ozon.get('identity_mismatch_count') != 0
            or ozon.get('scope_mismatch_count') != 0
            or ozon.get('binding_status_counts') != {'approved': 339}):
        raise RuntimeError('Ozon_confirmation_gate_failed')
    if (wb.get('target_count') != 339
            or wb.get('exact_cards_found') != 339
            or wb.get('exact_document_cards') != 339
            or wb.get('valid_document_cards') != 339):
        raise RuntimeError('WB_confirmation_gate_failed')
    if not SOURCE.is_file() or SOURCE.stat().st_size != 555914 or sha(SOURCE) != EXPECTED:
        raise RuntimeError('source_file_identity_or_hash_mismatch')

    assignments = ROOT / 'test/certificate_completion_20261020/all_confirmed_source_assignments_live_20261021.csv'
    with assignments.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    hits = [row for row in rows if SOURCE.name in (row.get('source_files') or '')]
    if len(hits) != 368 or {row.get('number') for row in hits} != {'RU Д-RU.PA08.B.41382/26'}:
        raise RuntimeError('source_file_assignment_usage_changed')

    identical = []
    for folder in [ROOT / 'output_to_user/certificates',
                   ROOT / 'test/certificate_completion_20261020/source_docs',
                   ROOT / 'test/certificate_api_pilot_20261012']:
        for path in folder.rglob('*.pdf'):
            if path.is_file() and sha(path) == EXPECTED:
                identical.append(str(path))
    if identical != [str(SOURCE)]:
        raise RuntimeError(f'identical_local_copy_set_changed:{identical}')

    size = SOURCE.stat().st_size
    deleted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    SOURCE.unlink()
    if SOURCE.exists():
        raise RuntimeError('source_file_still_exists_after_unlink')

    receipt = {
        'deleted_at_utc': deleted_at,
        'number': NUMBER,
        'fsa_record_id': 21895502,
        'fsa_status': 'Действует; confirmed live via FSA UI on 2026-10-21',
        'source_path': str(SOURCE),
        'sha256': EXPECTED,
        'bytes_deleted': size,
        'identical_copies_before_delete': identical,
        'assignment_rows_using_file': len(hits),
        'assignment_number_set': sorted({row['number'] for row in hits}),
        'ozon_certificate_id': 5625289,
        'ozon_approved_target_bindings': 339,
        'wb_target_cards': 339,
        'wb_exact_document_cards': 339,
        'wb_valid_verdicts': 339,
        'out_of_scope_source_assignments_excluded_by_tnved': 29,
        'source_deleted_only_after_both_platform_readbacks': True,
        'evidence_file': str(READBACK),
    }
    temp = RECEIPT.with_suffix('.tmp')
    temp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(RECEIPT)
    with JOURNAL.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'phase': 'deleted', 'receipt': str(RECEIPT), 'at_utc': deleted_at,
                                 'sha256': EXPECTED, 'bytes': size}, ensure_ascii=False) + '\n')

    result['source_pdf_deleted'] = True
    result['source_pdf_cleanup_receipt'] = str(RECEIPT)
    result['source_pdf_deleted_at_utc'] = deleted_at
    temp = READBACK.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(READBACK)

    summary = HERE / 'post_upload_reconciliation_20261020.json'
    summary_data = json.loads(summary.read_text(encoding='utf-8'))
    continuation = summary_data.get('latest_continuation') or {}
    continuation['checked_at_utc'] = deleted_at
    continuation['local_source_files_deleted_in_continuation'] = int(
        continuation.get('local_source_files_deleted_in_continuation') or 0) + 1
    continuation['local_source_file_bytes_deleted_in_continuation'] = int(
        continuation.get('local_source_file_bytes_deleted_in_continuation') or 0) + size
    continuation['arlight_41382_26'] = {
        'number': NUMBER,
        'fsa_record_id': 21895502,
        'fsa_status': 'active',
        'issue_date': '2026-09-16',
        'expiry_date': '2031-09-15',
        'ozon_certificate_id': 5625289,
        'ozon_status': 'approved',
        'ozon_target_bindings': 339,
        'ozon_approved_bindings': 339,
        'tnved_scope_exclusions': 29,
        'wb_target_cards': 339,
        'wb_exact_documents': 339,
        'wb_valid': 339,
        'source_pdf_deleted': True,
        'source_pdf_bytes_deleted': size,
        'evidence_files': [
            'arlight_41382_crossplatform_readback_live_20261021.json',
            'arlight_41382_local_pdf_cleanup_receipt_20261021.json',
        ],
    }
    continuation['overall_coverage_complete'] = False
    summary_data['latest_continuation'] = continuation
    temp = summary.with_suffix('.tmp')
    temp.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(summary)

    markdown = HERE / 'post_upload_reconciliation_20261020.md'
    body = markdown.read_text(encoding='utf-8')
    heading = '## Continued — Arlight 41382/26 — 2026-10-21'
    if heading not in body:
        body += (
            '\n\n' + heading + '\n\n'
            '- Live FSA record 21895502 remains active through 15.09.2031; its product scope lists Arlight lighting series SP, IM, MS, LTD, LGD, DL, ALT, CL, LT and LTM.\n'
            '- Fresh Ozon readback confirms record 5625289 is approved and all 339 in-scope offers have exact approved bindings with matching product/SKU identity and TN VED. The 29 remaining source assignments use code 9405190039, which the FSA record does not list, and were excluded.\n'
            '- The latest complete WB catalog read confirms exact declaration metadata and a valid verdict on all 339 in-scope cards. The local source PDF had one unique copy and was referenced only by 368 rows for this declaration. After confirming both platforms, deleted its 555,914-byte local copy. Receipt: `arlight_41382_local_pdf_cleanup_receipt_20261021.json`.\n'
            '- Evidence: `arlight_41382_crossplatform_readback_live_20261021.json`. Overall all-brand/all-product completion remains incomplete.\n'
        )
        markdown.write_text(body, encoding='utf-8')

    print(json.dumps({'deleted': True, 'path': str(SOURCE), 'sha256': EXPECTED, 'bytes': size,
                      'ozon_approved_links': 339, 'wb_valid_cards': 339,
                      'receipt': str(RECEIPT)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
