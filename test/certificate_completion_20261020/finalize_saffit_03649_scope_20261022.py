from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/Volumes/жесткач/Code2/Checksheets_Project/Checksheets')
BASE = ROOT / 'test/certificate_completion_20261020'
preflight_path = BASE / 'saffit_03649_scope_preflight_v3_20261022.json'
readback_path = BASE / 'saffit_03649_scope_delayed_readback_20261022.json'
state_path = BASE / 'saffit_03649_scope_execution_20261022.json'
addendum_path = BASE / 'postwrite_coverage_addendum_20261022.json'
source_path = ROOT / 'output_to_user/certificates/group_2/SAFFIT/documents/FSA_extract_18059184_03649_23.pdf'
final_path = BASE / 'saffit_03649_final_crossplatform_readback_20261022.json'

pre = json.loads(preflight_path.read_text())
rb = json.loads(readback_path.read_text())
state = json.loads(state_path.read_text())
add = json.loads(addendum_path.read_text())
expected_sha = pre['source_pdf_sha256']
assert pre['target_count'] == pre['ozon_eligible_targets'] == pre['wb_eligible_targets'] == 5
assert pre['scope']['all_five_models_match'] is True
assert pre['tnved_discrepancy_documented'] is True
assert rb['ozon_record_status'] == 'approved'
assert rb['ozon_expected_bindings'] == rb['ozon_visible_bindings'] == 5
assert rb['ozon_all_expected_pairs_visible'] is True
assert rb['ozon_binding_status_counts'] == {'approved': 5}
assert rb['wb_target_cards'] == rb['wb_cards_with_exact_declaration'] == 5
assert rb['wb_document_verdict_counts'] == {'valid': 2, 'pending_review_or_unverified': 3}
assert rb['wb_previous_documents_preserved'] and rb['wb_unrelated_card_fields_preserved']
assert rb['wb_left_for_marketplace_review'] is True and not rb['failures']
assert len(rb['cards']) == 5 and all(c['exact_declaration_count'] == 1 for c in rb['cards'])
assert all(c['prior_documents_preserved'] and c['unrelated_card_fields_preserved'] for c in rb['cards'])
assert source_path.is_file()
actual_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
assert actual_sha == expected_sha == rb.get('source_pdf_sha256', expected_sha)

# Remove only byte-identical local copies of this verified source document.
matching = []
for path in ROOT.rglob('*.pdf'):
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha:
        matching.append(path)
assert source_path in matching, 'verified source absent from matching hash set'

now = datetime.now(timezone.utc).isoformat()
proof = {
    'checked_at_utc': now,
    'document_number': 'ЕАЭС N RU Д-CN.РА07.В.03649/23',
    'source_pdf_sha256': expected_sha,
    'source_files_matching_hash': [str(p) for p in matching],
    'ozon': {
        'certificate_id': rb['ozon_certificate_id'],
        'record_status': rb['ozon_record_status'],
        'exact_expected_bindings': rb['ozon_expected_bindings'],
        'exact_visible_bindings': rb['ozon_visible_bindings'],
        'binding_status_counts': rb['ozon_binding_status_counts'],
    },
    'wb': {
        'target_cards': rb['wb_target_cards'],
        'cards_with_exact_declaration': rb['wb_cards_with_exact_declaration'],
        'verdict_counts': rb['wb_document_verdict_counts'],
        'left_for_marketplace_review': rb['wb_left_for_marketplace_review'],
        'previous_documents_preserved': rb['wb_previous_documents_preserved'],
        'unrelated_card_fields_preserved': rb['wb_unrelated_card_fields_preserved'],
    },
    'tnved_discrepancy_documented': pre['tnved_discrepancy_documented'],
    'preflight_artifact': str(preflight_path),
    'delayed_readback_artifact': str(readback_path),
    'source_cleanup_basis': 'All five exact Ozon bindings are approved and all five WB cards show the exact declaration metadata; three WB verdicts remain pending and were left for marketplace review.',
    'deletion_pending': True,
}
final_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')

removed = []
for path in matching:
    path.unlink()
    removed.append(str(path))
proof['deleted_files'] = removed
proof['deletion_pending'] = False
proof['local_source_files_deleted'] = True
proof['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
final_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')

state['phase'] = 'cross_marketplace_readback_complete_sources_cleaned'
state['local_source_files_deleted'] = True
state['finished_at_utc'] = proof['checked_at_utc']
state['final_readback_artifact'] = str(final_path)
state['source_cleanup'] = {'deleted_files': removed, 'source_sha256': expected_sha, 'basis': proof['source_cleanup_basis']}
state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')

entry = {
    'brand': 'Saffit',
    'document_number': 'ЕАЭС N RU Д-CN.РА07.В.03649/23',
    'type': 'declaration',
    'source_sha256': expected_sha,
    'ozon_certificate_id': rb['ozon_certificate_id'],
    'ozon_record_status': rb['ozon_record_status'],
    'ozon_exact_bindings': rb['ozon_visible_bindings'],
    'ozon_binding_status_counts': rb['ozon_binding_status_counts'],
    'wb_exact_cards': rb['wb_cards_with_exact_declaration'],
    'wb_valid_cards': rb['wb_document_verdict_counts']['valid'],
    'wb_review_pending_cards': rb['wb_document_verdict_counts']['pending_review_or_unverified'],
    'wb_review_state_changed_by_agent': False,
    'wb_left_for_marketplace_review': True,
    'tnved_discrepancy_documented': True,
    'local_source_pdf_deleted': True,
    'verification_artifacts': [preflight_path.name, readback_path.name, final_path.name],
}
entries = add.setdefault('post_snapshot_writes', [])
entries[:] = [e for e in entries if e.get('document_number') != entry['document_number']]
entries.append(entry)
add.setdefault('verification_artifacts', {})['saffit_03649_final_readback'] = str(final_path)
add.setdefault('local_source_cleanup', {})['saffit_03649_20261022'] = {
    'deleted_files': [
        {'source_file': str(Path(p).relative_to(ROOT)), 'sha256': expected_sha, 'document_number': entry['document_number'], 'deleted': True}
        for p in removed
    ],
    'checked_at_utc': proof['checked_at_utc'],
    'basis': proof['source_cleanup_basis'],
}
add['complete'] = False
add['local_source_pdfs_deleted'] = False
add['checked_at_utc'] = proof['checked_at_utc']
addendum_path.write_text(json.dumps(add, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'final_artifact': str(final_path), 'deleted': removed, 'ozon_approved': 5, 'wb_exact': 5, 'wb_valid': 2, 'wb_pending': 3, 'overall_complete': add['complete']}, ensure_ascii=False, indent=2))
