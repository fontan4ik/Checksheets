from __future__ import annotations
import csv, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / 'test/certificate_completion_20261020/gauss_downlight_live_preflight_20261022.json'
MASTER = ROOT / 'output_to_user/certificates/coverage_master.csv'
OUT = ROOT / 'test/certificate_completion_20261020/gauss_downlight_reconciliation_20261022.csv'
NUMBER = 'ЕАЭС N RU Д-CN.РА03.В.12843/22'
FSA_URL = 'https://pub.fsa.gov.ru/rds/declaration/view/16679032/product'
EXPECTED_ALLOWED = {'9405110013', '9405110033', '9405110039'}

pre = json.loads(PREFLIGHT.read_text(encoding='utf-8'))
assert pre.get('read_only') is True
assert pre.get('wb_catalog', {}).get('complete') is True

docs = [d for d in pre['documents'] if d.get('number') == NUMBER]
assert len(docs) == 1, 'unique source declaration must be present'
doc = docs[0]
assert doc['type_code'] == 'declaration'
assert doc['issue_date'] == '2022-04-18' and doc['expire_date'] == '2027-04-17'
assert set(doc['allowed_tnved']) == EXPECTED_ALLOWED
assert doc['fsa_record_id'] == 16679032
assert doc['local_sha256'] == doc['sha256']

ozon_docs = [d for d in pre['ozon_documents'] if d.get('number') == NUMBER]
assert len(ozon_docs) == 1 and len(ozon_docs[0].get('matches') or []) == 1
record = ozon_docs[0]['matches'][0]
assert record.get('status_code') == 'approved'
assert str(record.get('issue_date', ''))[:10] == doc['issue_date']
assert str(record.get('expire_date', ''))[:10] == doc['expire_date']

coverage_rows = {}
with MASTER.open(encoding='utf-8-sig', newline='') as fh:
    reader = csv.DictReader(fh)
    master_fields = reader.fieldnames
    for row in reader:
        offer = row.get('Артикул продавца', '')
        if offer.startswith('9100420205'):
            if offer in coverage_rows:
                raise AssertionError(f'duplicate master offer: {offer}')
            coverage_rows[offer] = row

wb_by_offer = {}
for item in pre['wb_cards']:
    offer = item['offer_id']
    assert item.get('unique_exact_card_count') == 1
    assert len(item.get('cards') or []) == 1
    card = item['cards'][0]
    matching = [x for x in card.get('matching_docs', []) if x.get('number') == NUMBER]
    assert len(matching) == 1, f'no unique exact WB document on {offer}'
    wd = matching[0]
    verdict = wd.get('verdict') or {}
    assert wd.get('type') == 2
    assert str(wd.get('startDate', ''))[:10] == doc['issue_date']
    assert str(wd.get('endDate', ''))[:10] == doc['expire_date']
    assert verdict.get('verified') is True and verdict.get('status') == 1 and verdict.get('reason') == 'valid'
    wb_by_offer[offer] = (card, wd)

bindings = {}
for b in record.get('target_bindings') or []:
    offer = b.get('offer_id')
    if offer in bindings:
        raise AssertionError(f'duplicate Ozon target binding: {offer}')
    assert b.get('binding', {}).get('product_status_code') == 'approved'
    assert str(b.get('binding', {}).get('product_id')) == str(b.get('product_id'))
    assert str(b.get('binding', {}).get('sku')) == str(b.get('sku'))
    bindings[offer] = b

expected = set(wb_by_offer)
assert len(expected) == 6 and expected == set(bindings) == set(coverage_rows), (expected, set(bindings), set(coverage_rows))
assert pre.get('conflicts') and len(pre['conflicts']) == 6
assert pre.get('ozon_scope_conflicts') and len(pre['ozon_scope_conflicts']) == 6

report_rows = []
for offer in sorted(expected):
    master = coverage_rows[offer]
    b = bindings[offer]
    card, wd = wb_by_offer[offer]
    tnved = sorted(set(card.get('tnved_codes') or []))
    assert tnved and not set(tnved) <= EXPECTED_ALLOWED
    report_rows.append({
        'seller_offer': offer,
        'ozon_product_id': str(b['product_id']),
        'ozon_sku': str(b['sku']),
        'ozon_certificate_id': str(record['certificate_id']),
        'ozon_document_status': record['status_code'],
        'ozon_binding_status': b['binding']['product_status_code'],
        'wb_nmID': str(card['nmID']),
        'wb_document_verdict': wd['verdict']['reason'],
        'wb_document_status': str(wd['verdict']['status']),
        'marketplace_tnved': ';'.join(tnved),
        'document_number': NUMBER,
        'fsa_status': 'active; confirmed in FSA record 16679032',
        'fsa_url': FSA_URL,
        'document_validity': f"{doc['issue_date']}–{doc['expire_date']}",
        'allowed_tnved': ';'.join(sorted(EXPECTED_ALLOWED)),
        'resolution': 'attached and approved/valid on both platforms; unresolved scope mismatch because marketplace TN VED is outside the FSA declaration code list',
        'local_source_pdf_retained': doc['file'],
    })

# Update only the six rows whose exact Ozon and WB document records were checked above.
tmp = MASTER.with_suffix('.csv.tmp')
updated = 0
with MASTER.open(encoding='utf-8-sig', newline='') as src, tmp.open('w', encoding='utf-8-sig', newline='') as dst:
    reader = csv.DictReader(src)
    writer = csv.DictWriter(dst, fieldnames=reader.fieldnames, extrasaction='ignore')
    writer.writeheader()
    for row in reader:
        offer = row.get('Артикул продавца', '')
        if offer in expected:
            updated += 1
            old = row.get('Основание/примечание', '')
            old = old.replace('12843/22 не подтверждён', '12843/22 подтверждён в ФСА и на маркетплейсах')
            suffix = (f" LIVE 2026-10-22: декларация {NUMBER}, ФСА active ({FSA_URL}); "
                      f"Ozon document approved + binding approved, WB exact card verdict valid. "
                      f"Однако ТН ВЭД карточки вне кодов ФСА {','.join(sorted(EXPECTED_ALLOWED))}; "
                      "поэтому покрытие частичное, документ не засчитывается как юридически подтверждённый для карточки до разрешения классификационного расхождения.")
            row['Статус покрытия исходный'] = 'Действующая декларация видна на Ozon и WB; применимость требует проверки из-за ТН ВЭД вне области ФСА'
            row['Статус покрытия нормализованный'] = 'Частичное покрытие'
            row['Основание/примечание'] = old.rstrip() + suffix
        writer.writerow(row)
if updated != 6:
    tmp.unlink(missing_ok=True)
    raise AssertionError(f'expected 6 updated rows, got {updated}')
os.replace(tmp, MASTER)

with OUT.open('w', encoding='utf-8-sig', newline='') as fh:
    writer = csv.DictWriter(fh, fieldnames=list(report_rows[0]))
    writer.writeheader()
    writer.writerows(report_rows)
print(json.dumps({'updated_master_rows': updated, 'report_rows': len(report_rows), 'report': str(OUT), 'normalized_state': 'Частичное покрытие', 'marketplace_writes': 0, 'local_files_deleted': 0}, ensure_ascii=False))
