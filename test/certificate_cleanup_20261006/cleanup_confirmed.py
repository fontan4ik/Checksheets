import collections
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJECT = BASE.parents[1]
FERON = Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
ROOTS = [PROJECT / 'output_to_user/certificates', FERON]
TR = str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'M','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Д':'D'})

def norm(number):
    s = re.sub(r'^(?:ЕАЭС|EAEU|EAEC|EAC)\s*', '', str(number).upper())
    s = re.sub(r'^(?:N|№)\s*', '', s)
    return ''.join(c for c in s.translate(TR) if c.isalnum())

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def load(name):
    return json.loads((BASE / name).read_text())

def write(name, data):
    path = BASE / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)

def plan():
    local, ozon, wb = load('local_map.json'), load('ozon_live.json'), load('wb_live.json')
    if not ozon['complete'] or not wb['complete']:
        raise RuntimeError('Live readback incomplete; no cleanup allowed')
    certs = collections.defaultdict(list)
    for c in ozon['certificates']:
        certs[norm(c['certificate_number'])].append(c)
    cards = collections.defaultdict(list)
    for c in wb['cards']:
        cards[c['vendorCode']].append(c)
    decisions = []
    for g in local['groups']:
        record = {'sha256': g['sha256'], 'numbers': g['document_numbers'], 'files': g['files'], 'decision': 'keep'}
        decisions.append(record)
        if not g['eligible_for_live_comparison']:
            record['reason'] = 'incomplete_or_ambiguous_local_proof'
            continue
        keys = {norm(n) for n in g['document_numbers']}
        if len(keys) != 1:
            record['reason'] = 'ambiguous_document_number'
            continue
        key = next(iter(keys))
        approved = [c for c in certs.get(key, []) if c['status_code'] == 'approved']
        if not approved:
            record['reason'] = 'no_approved_ozon_document'
            continue
        types = {c['type_code'].lower() for c in approved}
        if len(types) != 1:
            record['reason'] = 'ambiguous_document_type'
            continue
        wb_type = 2 if 'declaration' in next(iter(types)) else 1
        bound = {(str(b['sku']), str(b['product_id'])) for c in approved for b in c['live_bindings'] if b['product_status_code'] in ('approved', 'background_check')}
        required = {(s, i) for b in g['bindings'] for s in b['ozon_skus'] for i in b['ozon_product_ids']}
        if not required or not required <= bound:
            record['reason'] = 'unconfirmed_ozon_product_bindings'
            record['missing_ozon_pairs'] = sorted(required - bound)
            continue
        wb_missing, wb_checked = [], 0
        for b in g['bindings']:
            for c in cards.get(b['offer_id'], []):
                wb_checked += 1
                documents = c.get('documents') or {}
                good = not documents.get('excludeDocuments') and any(
                    norm(item.get('number', '')) == key and item.get('type') == wb_type
                    and (item.get('verdict') or {}).get('verified') is True
                    and (item.get('verdict') or {}).get('status') == 1
                    and (item.get('verdict') or {}).get('reason') == 'valid'
                    for item in documents.get('items', [])
                )
                if not good:
                    wb_missing.append({'offer_id': b['offer_id'], 'nmID': c['nmID']})
        if wb_missing:
            record['reason'] = 'unconfirmed_or_invalid_wb_document'
            record['missing_wb_cards'] = wb_missing
            continue
        proof = g.get('expected_sha256s', [])
        if (proof and set(proof) != {g['sha256']}) or (not proof and g.get('feron_original_sha256') != g['sha256']):
            record['reason'] = 'missing_or_conflicting_checksum_proof'
            continue
        if any(Path(f['path']).suffix.lower() not in ('.pdf', '.jpg', '.jpeg', '.png') for f in g['files']):
            record['reason'] = 'unsupported_document_file'
            continue
        record.update(decision='move_to_trash', reason='approved_ozon_and_all_existing_marketplace_bindings_confirmed', ozon_certificate_ids=[c['certificate_id'] for c in approved], ozon_pairs=len(required), wb_cards=wb_checked)
    result = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'ozon_checked_at': ozon['checked_at'], 'wb_checked_at': wb['checked_at'], 'criteria': 'Ozon certificate approved; every source SKU/product pair stored with approved/background_check; every existing WB article card has exact type+number, verified valid verdict. Ambiguous or pending cases retained.', 'decisions': decisions}
    summary = collections.Counter(r['reason'] for r in decisions)
    moving = [r for r in decisions if r['decision'] == 'move_to_trash']
    result['summary'] = {'document_hash_groups_to_move': len(moving), 'files_to_move': sum(len(r['files']) for r in moving), 'bytes_to_move': sum(f['size'] for r in moving for f in r['files']), 'retained_hash_groups': len(decisions)-len(moving), 'reasons': dict(summary)}
    write('cleanup_plan.json', result)
    print(json.dumps(result['summary'], ensure_ascii=False))

def execute():
    data = load('cleanup_plan.json')
    files = [(r, f) for r in data['decisions'] if r['decision'] == 'move_to_trash' for f in r['files']]
    if (BASE / 'cleanup_result.json').exists():
        raise RuntimeError('Cleanup already recorded; refusing duplicate run')
    # Complete preflight before the first move.
    for r, f in files:
        path = Path(f['path'])
        if path.is_symlink() or not any(path.is_relative_to(root) for root in ROOTS):
            raise RuntimeError('Unexpected path: ' + str(path))
        if not path.is_file() or path.stat().st_size != f['size'] or sha(path) != r['sha256']:
            raise RuntimeError('Source changed: ' + str(path))
    trash = Path.home() / '.Trash' / ('Загруженные_сертификаты_2026-10-06_' + datetime.datetime.now().strftime('%H%M%S'))
    trash.mkdir(parents=True, exist_ok=False)
    moved = []
    journal = BASE / 'cleanup_journal.jsonl'
    with journal.open('x') as stream:
        for r, f in files:
            source = Path(f['path'])
            root = next(root for root in ROOTS if source.is_relative_to(root))
            label = 'Checksheets' if root == ROOTS[0] else 'FERON'
            dest = trash / label / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Recheck immediately before each reversible move.
            if sha(source) != r['sha256']:
                raise RuntimeError('Source changed during cleanup: ' + str(source))
            os.rename(source, dest)
            if source.exists() or sha(dest) != r['sha256']:
                raise RuntimeError('Move verification failed: ' + str(source))
            entry = {'source': str(source), 'trash_path': str(dest), 'sha256': r['sha256'], 'size': f['size'], 'numbers': r['numbers'], 'ozon_certificate_ids': r['ozon_certificate_ids'], 'ozon_pairs': r['ozon_pairs'], 'wb_cards': r['wb_cards']}
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            stream.flush()
            moved.append(entry)
    # All retained mapped source files must still exist with the same bytes.
    retained = 0
    for r in data['decisions']:
        if r['decision'] != 'keep':
            continue
        for f in r['files']:
            if sha(Path(f['path'])) != r['sha256']:
                raise RuntimeError('Retained file changed: ' + f['path'])
            retained += 1
    result = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'trash_directory': str(trash), 'summary': data['summary'], 'verified_moved_files': len(moved), 'verified_retained_mapped_files': retained, 'moved': moved}
    write('cleanup_result.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'moved'}, ensure_ascii=False))

if __name__ == '__main__':
    execute() if '--execute' in sys.argv else plan()
