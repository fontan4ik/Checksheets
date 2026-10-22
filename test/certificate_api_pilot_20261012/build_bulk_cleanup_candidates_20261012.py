"""Prepare only locally proven documents that passed the current cross-marketplace audit."""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from api_client import BASE, ROOT, now, save

FERON = Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
LOCAL_MAP = ROOT / 'test/certificate_cleanup_20261006/local_map.json'
AUDIT = BASE / 'brand_certificate_coverage_audit_20261012.json'
OUT = 'bulk_cleanup_candidates_20261012.json'
ROOTS = [ROOT / 'output_to_user/certificates', BASE, FERON]
TR = str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'M','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Д':'D'})


def norm(number: object) -> str:
    text = re.sub(r'^(?:ЕАЭС|EAEU|EAEC|EAC)\s*', '', str(number).upper())
    text = re.sub(r'^(?:N|№)\s*', '', text)
    return ''.join(c for c in text.translate(TR) if c.isalnum())


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def label_for(path: Path, root: Path) -> str:
    if root == ROOT / 'output_to_user/certificates':
        return 'output_to_user/certificates'
    if root == BASE:
        return 'test/certificate_api_pilot_20261012'
    return 'Документы_качества_Feron'


def main() -> None:
    local = json.loads(LOCAL_MAP.read_text())
    audit = json.loads(AUDIT.read_text())
    if not audit.get('complete'):
        raise RuntimeError('Current all-brand coverage audit is incomplete')
    docs_by_number = defaultdict(list)
    for doc in audit['documents']:
        if doc.get('all_targets_valid_on_wb') is True:
            docs_by_number[norm(doc['number'])].append(doc)

    mapped = []
    reason_counts = Counter()
    local_counts = Counter()
    for group in local.get('groups') or []:
        if not group.get('eligible_for_live_comparison'):
            reason_counts['local_proof_ineligible'] += 1
            continue
        if group.get('issues'):
            reason_counts['local_mapping_has_issues'] += 1
            continue
        legal_numbers = {norm(number) for number in group.get('document_numbers') or [] if number}
        if len(legal_numbers) != 1:
            reason_counts['local_number_ambiguous'] += 1
            continue
        key = next(iter(legal_numbers))
        docs = docs_by_number.get(key) or []
        if len(docs) != 1:
            reason_counts['no_unique_final_cross_marketplace_document'] += 1
            continue
        doc = docs[0]
        local_pairs = {(str(product_id), str(sku))
                       for binding in group.get('bindings') or []
                       for product_id in binding.get('ozon_product_ids') or []
                       for sku in binding.get('ozon_skus') or []}
        live_pairs = {(str(target['product_id']), str(target['sku'])) for target in doc.get('targets') or []}
        if not local_pairs or local_pairs != live_pairs:
            reason_counts['local_and_live_target_sets_differ'] += 1
            continue
        hashes = set(group.get('expected_sha256s') or [])
        if (hashes and hashes != {group['sha256']}) or (not hashes and group.get('feron_original_sha256') != group['sha256']):
            reason_counts['checksum_proof_missing_or_conflicting'] += 1
            continue
        source_files = []
        for row in group.get('files') or []:
            path = Path(row['path'])
            if (not path.is_absolute() or path.resolve() != path
                    or not any(path.is_relative_to(root) for root in ROOTS)
                    or path.suffix.lower() not in {'.pdf', '.jpg', '.jpeg', '.png'}):
                raise RuntimeError(f'Unexpected mapped local path: {path}')
            if (not path.is_file() or path.stat().st_size != row['size']
                    or sha(path) != group['sha256']):
                continue
            source_files.append({'path': str(path), 'size': row['size'], 'sha256': group['sha256'],
                                 'label': label_for(path, next(root for root in ROOTS if path.is_relative_to(root))),
                                 'relative_path': str(path.relative_to(next(root for root in ROOTS if path.is_relative_to(root))))})
        if not source_files:
            reason_counts['no_current_source_files'] += 1
            continue
        mapped.append({'number': doc['number'], 'type': doc['type'], 'issue_date': doc['issue_date'],
                       'expire_date': doc['expire_date'], 'certificate_ids': doc['certificate_ids'],
                       'target_pairs': doc['target_pairs'], 'targets': doc['targets'],
                       'source_sha256': group['sha256'], 'source_proof': group,
                       'source_files': source_files})

    # Add same-hash local copies only inside the three audited roots; keep every unrelated hash untouched.
    hashes = {row['source_sha256'] for row in mapped}
    size_by_hash = {row['source_sha256']: {f['size'] for f in row['source_files']} for row in mapped}
    all_files = {row['source_sha256']: {f['path'] for f in row['source_files']} for row in mapped}
    sizes = {size for values in size_by_hash.values() for size in values}
    for root in ROOTS:
        if not root.exists():
            continue
        for directory, _, names in os.walk(root):
            for name in names:
                path = Path(directory) / name
                try:
                    size = path.stat().st_size
                    if (size not in sizes or size > 30_000_000 or path.is_symlink()
                            or path.suffix.lower() not in {'.pdf', '.jpg', '.jpeg', '.png'}):
                        continue
                    digest = sha(path)
                except OSError:
                    continue
                if digest not in hashes or str(path) in all_files[digest]:
                    continue
                root_used = next((r for r in ROOTS if path.is_relative_to(r)), None)
                if root_used is None or path.resolve() != path:
                    raise RuntimeError(f'Unsafe exact-hash copy path: {path}')
                all_files[digest].add(str(path))
                group = next(row for row in mapped if row['source_sha256'] == digest)
                group['source_files'].append({'path': str(path), 'size': size, 'sha256': digest,
                                              'label': label_for(path, root_used),
                                              'relative_path': str(path.relative_to(root_used))})

    # A second local file group for the same legal number is ambiguous even when both map to the same target set.
    local_owners = defaultdict(list)
    for item in mapped:
        local_owners[norm(item['number'])].append(item)
    final = []
    for item in mapped:
        if len(local_owners[norm(item['number'])]) != 1:
            reason_counts['multiple_local_hash_groups_for_number'] += 1
            continue
        final.append(item)

    offers = {}
    for item in final:
        for target in item['targets']:
            previous = offers.get(target['offer_id'])
            if previous and str(previous['nmID']) != str(target['wb_nmID']):
                raise RuntimeError(f'Conflicting WB nmID for offer {target["offer_id"]}')
            offers[target['offer_id']] = {'nmID': str(target['wb_nmID']), 'brand': target.get('brand')}
    plan = {'checked_at': now(), 'source_audit_checked_at': audit.get('checked_at'),
            'local_map_path': str(LOCAL_MAP), 'audit_path': str(AUDIT), 'complete': True,
            'candidate_groups': final, 'target_offers': offers,
            'summary': {'groups': len(final), 'unique_targets': len(offers),
                        'ozon_product_document_pairs': sum(x['target_pairs'] for x in final),
                        'local_files': sum(len(x['source_files']) for x in final),
                        'bytes': sum(f['size'] for x in final for f in x['source_files']),
                        'retained_reason_counts': dict(reason_counts)}}
    # Brand counts come from the current live target sets.
    brands = Counter(target.get('brand') or '(brand attribute absent)' for item in final for target in item['targets'])
    plan['summary']['target_brands'] = dict(brands)
    save(OUT, plan)
    print(json.dumps(plan['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
