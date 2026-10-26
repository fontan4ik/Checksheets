"""Read-only evidence join for marketplace cards without a current approved document."""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
AUDIT = ROOT / 'test/certificate_completion_20261020'
TODAY = '2026-10-26'
TRANS = str.maketrans(dict(zip('АВЕКМНОРСТУХД', 'ABEKMHOPCTYXD')))

def norm(value):
    value = re.sub(r'^(?:ЕАЭС|EAEU|EAEC|EAC)\s*', '', str(value or '').upper())
    value = re.sub(r'^(?:N|№)\s*', '', value)
    return ''.join(c for c in value.translate(TRANS) if c.isalnum())

def unique(values):
    return list(dict.fromkeys(str(v).strip() for v in values if v is not None and str(v).strip()))

def joined(values):
    return '\n'.join(unique(values))[:32000]

def codes(values):
    return {str(v).split(' - ', 1)[0].strip() for v in values if v}

def active(doc, start='issue_date', end='expire_date'):
    a, b = str(doc.get(start) or '')[:10], str(doc.get(end) or '')[:10]
    return bool(a and a <= TODAY and ((b and b >= TODAY) or doc.get('isEndless') is True))

def wb_valid(doc):
    v = doc.get('verdict') or {}
    return v.get('verified') is True and v.get('status') == 1 and v.get('reason') == 'valid' and active(doc, 'startDate', 'endDate')

def rejected(doc):
    v = doc.get('verdict') or {}
    return v.get('status') not in (None, 1) or v.get('reason') not in (None, '', 'valid')

BLOCK_TEXT = {
 'known_unresolved_production_lot_or_product_scope_restriction': 'Не подтверждены ограничения документа по партии или области действия',
 'production_lot_or_sample_date_scope_requires_separate_review': 'Нужно подтвердить дату изготовления партии относительно даты образцов',
 'verified_local_original_pdf_missing': 'В проверенном комплекте нет исходного PDF',
 'pdf_text_or_ocr_cache_missing_or_incomplete': 'Не завершена проверка текста PDF и его реквизитов',
 'pdf_legal_number_missing_or_ambiguous': 'Юридический номер документа не установлен однозначно',
 'missing_or_invalid_dates': 'Не подтверждены корректные даты документа',
 'verified_original_pdf_missing_changed_or_not_pdf': 'Нет проверенного исходного PDF с ожидаемым содержимым',
 'no_explicit_confirmed_upload_scope_plan': 'Не подтверждён список точных моделей для загрузки',
 'no_confirmed_exact_active_targets': 'Нет подтверждённых точных товаров в области документа',
 'authoritative_date_range_missing_or_conflicting': 'Не подтверждены однозначные даты действия найденного документа',
 'authoritative_dates_not_confirmed_in_pdf_text': 'Даты найденного документа не подтверждены текстом оригинала',
 'expired_or_future_document': 'Найденный документ истёк или ещё не вступил в силу',
 'no_exact_current_source_confirmed_target': 'Не подтверждено точное совпадение текущей модели с документом',
 'local_hash_has_no_exact_official_article_assignment': 'Для локального файла нет подтверждённого официальным источником назначения на точный артикул',
 'not_full_legal_number_or_supporting_document': 'В найденных материалах нет подтверждённого полного регистрационного номера применимого документа',
 'no_verified_dated_exact_scope_upload_plan': 'Не завершена проверка реквизитов и точного перечня моделей для загрузки',
 'unconfirmed_partial_historical_or_supporting_source': 'Найдены материалы с неподтверждённой, частичной или исторической применимостью',
 'local_hash_map_is_not_verified_upload_plan': 'Связь локального документа с точной моделью ещё не прошла проверку',
}

def translate_block(reason):
    if reason in BLOCK_TEXT:
        return BLOCK_TEXT[reason]
    if 'manufactur' in reason or 'sample' in reason:
        return 'Документ ограничен датой изготовления партии; дата текущей партии не подтверждена'
    return ''

snap = json.loads((AUDIT / 'live_marketplaces_snapshot_export_20261026.json').read_text())
for key in ('ozon_products', 'ozon_certificates', 'wb_catalog'):
    if not snap.get(key, {}).get('complete'):
        raise RuntimeError(f'Incomplete fresh snapshot: {key}')

manifest = json.loads((AUDIT / 'all_source_certificates_verified_manifest_20261024.json').read_text())
assignments = defaultdict(list)
with (ROOT / 'output_to_user/certificates/document_assignments.csv').open(encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        assignments[r['Артикул продавца'].strip()].append(r)
groups_offer = defaultdict(list)
groups_hash = defaultdict(list)
for g in manifest['groups']:
    groups_hash[g.get('upload_file', {}).get('sha256', '')].append(g)
    for t in g.get('targets') or []:
        groups_offer[str(t['offer_id'])].append(g)
blocks_number = defaultdict(list)
blocks_hash = defaultdict(list)
for r in manifest.get('skips', []):
    if r.get('number'):
        blocks_number[norm(r['number'])].append(r.get('reason', ''))
for k, v in manifest.get('blocked_reasons', {}).items():
    blocks_number[norm(k)].append(v)
for r in manifest.get('expansion_skips', []):
    if r.get('sha256'):
        blocks_hash[r['sha256']].append(r.get('reason', ''))

certs = snap['ozon_certificates']['certificates']
cert_number = defaultdict(list)
links = defaultdict(list)
for c in certs:
    cert_number[norm(c.get('certificate_number'))].append(c)
    for b in c.get('live_bindings') or []:
        links[str(b.get('product_id'))].append((c, b))

def candidate_info(offer, actual_codes):
    rows = assignments.get(offer, [])
    gs = list(groups_offer.get(offer, []))
    details, nums, urls = [], [], []
    informative_letters = []
    history = []
    conformity_rows = []
    for r in rows:
        kind = r.get('Тип документа', '')
        desc = (kind + ' ' + r.get('Применимость', '')).lower()
        number = r.get('Номер/название документа', '')
        sha = r.get('SHA256 фактический') or r.get('SHA256 заявленный') or ''
        nums.append(f'{number} ({kind})' if number else kind)
        urls.append(r.get('URL документа'))
        if ('отказное письмо' in kind.lower() or 'refusal letter' in kind.lower() or kind == 'refusal') and 'отказ в регистрации' not in desc:
            informative_letters.append(r)
        if 'историч' in desc or 'истёк' in desc or 'historic' in desc:
            history.append(r)
        if r.get('Применимость') in ('Подтверждено статусом покрытия', 'Подтверждено источником') and re.search('сертификат|деклараци|conformity|declaration|certificate', kind, re.I):
            conformity_rows.append(r)
        for g in groups_hash.get(sha, []):
            if g not in gs:
                gs.append(g)
        for block in blocks_hash.get(sha, []) + blocks_number.get(norm(number), []):
            if block in ('verified_local_original_pdf_missing', 'verified_original_pdf_missing_changed_or_not_pdf'):
                local = str(r.get('Локальный файл') or '')
                if local and (ROOT / local).is_file():
                    continue
            details.append(translate_block(block))
    for g in gs:
        nums.append(g.get('number'))
        allowed = set(map(str, g.get('allowed_tnved') or []))
        if actual_codes and allowed and not actual_codes <= allowed:
            details.append(f'Кандидат {g["number"]}: ТН ВЭД товара {", ".join(sorted(actual_codes))} вне области документа ({", ".join(sorted(allowed))})')
        if g.get('expire_date', '') < TODAY:
            details.append(f'Кандидат {g["number"]}: истёк {g.get("expire_date")}')
    keys = {norm(g.get('number')) for g in gs} | {norm(r.get('Номер/название документа')) for r in rows}
    matching = [c for k in keys if k for c in cert_number.get(k, [])]
    base = 'Применимый документ не найден в накопленных материалах'
    action = 'Запросить у производителя документ для точной модели и проверить обязательность оценки соответствия'
    if rows:
        base = 'Найденные материалы не подтверждают действующий документ для этой карточки'
    if history and not conformity_rows:
        base = 'Найдены исторические документы; действующий применимый документ не подтверждён'
    if conformity_rows or gs:
        base = 'Документ-кандидат найден; его применимость и загрузка для карточки не подтверждены'
        action = 'Проверить оригинал, реестр, модель, даты, партию и ТН ВЭД; затем загрузить и привязать'
    if details:
        meaningful = unique(details)
        if meaningful:
            base = meaningful[0]
    if any('вне области' in d for d in details):
        base = 'ТН ВЭД карточки не совпадает с областью найденного документа-кандидата'
        action = 'Сверить классификацию и модель; найти документ с подходящей областью действия'
    if informative_letters:
        letter = 'Найдено отказное/информационное письмо; актуальность и применимость требуют проверки'
        if not conformity_rows and not gs:
            base = 'Есть отказное/информационное письмо; действующий сертификат или декларация не подтверждены'
            action = 'Проверить, освобождён ли конкретный товар от обязательной оценки, и актуальность письма'
    else:
        letter = 'Необходимость не установлена; проверить по модели, назначению и классификации'
    return dict(reason=base, action=action, detail=joined(details), numbers=joined(nums), urls=joined(urls), letter=letter, matching=matching)

HEAD = ['Артикул продавца', 'Причина', 'Статус', 'Бренд', 'Название товара', 'ТН ВЭД', 'ID товара / nmID', 'SKU / штрихкоды', 'Документы на площадке', 'Найденные документы', 'Подробности проверки', 'Что сделать', 'Отказное письмо', 'Источник документа', 'Архив / документы не требуются', 'Проверено, UTC']
output = {'Ozon': [], 'WB': []}
counts = {}
for p in snap['ozon_products']['products']:
    pid, sku, offer = str(p['product_id']), str(p.get('sku') or ''), p['offer_id']
    exact = [(c, b) for c, b in links[pid] if str(b.get('sku') or '') == sku]
    if any(c.get('status_code') == 'approved' and b.get('product_status_code') == 'approved' and active(c) for c, b in exact):
        continue
    ci = candidate_info(offer, codes(p.get('tnved_values') or []))
    reason, action, status = ci['reason'], ci['action'], 'Нет подтверждённой привязки'
    detail = [ci['detail']]
    if any(b.get('product_status_code') == 'declined' for c, b in exact):
        reason, status = 'Ozon отклонил привязку документа к товару', 'Привязка отклонена'
        action = 'Открыть причину отказа в Ozon Seller, исправить её и повторно проверить привязку'
        detail.append('API не раскрывает причину отказа по отдельному товару')
    elif any(active(c) for c, b in exact):
        reason, status = 'Документ или привязка ещё не одобрены Ozon', 'На проверке / не одобрено'
        action = 'Проверить статус документа и привязки в Ozon Seller'
    elif exact:
        reason, status = 'У привязанных документов нет подтверждённого действующего срока', 'Истёкший срок / даты не подтверждены'
    elif ci['matching']:
        reason = 'Документ-кандидат уже загружен в Ozon; подтверждённой привязки к товару нет'
        action = 'Проверить применимость загруженного документа и привязать точный товар'
        if 'вне области' in ci['detail']:
            reason, action = ci['reason'], ci['action']
    listed = []
    for c, b in exact:
        listed.append(f'{c.get("certificate_number")}: документ {c.get("status_code")}; привязка {b.get("product_status_code")}; до {str(c.get("expire_date") or "")[:10]}')
        detail.extend([c.get('verification_comment'), c.get('rejection_reason_code')])
    if not exact:
        listed = [f'{c.get("certificate_number")}: {c.get("status_code")}; привязка отсутствует' for c in ci['matching']]
    if links[pid] and not exact:
        detail.append('В API есть привязка с несовпадающим SKU; идентичность не подтверждена')
    output['Ozon'].append([offer, reason, status, joined(p.get('brand_values') or []), p.get('name') or '', joined(p.get('tnved_values') or []), pid, sku, joined(listed) or 'Связанный документ в API не найден', ci['numbers'], joined(detail), action, ci['letter'], ci['urls'], 'Архив' if p.get('is_archived') else 'Не в архиве', snap['ozon_certificates']['checked_at']])

for c in snap['wb_catalog']['cards']:
    ds = c.get('documents') or {}
    docs = ds.get('items') or []
    if any(wb_valid(d) for d in docs):
        continue
    actual = []
    for ch in c.get('characteristics') or []:
        if re.search('тнвэд|тнвед', ch.get('name', ''), re.I):
            v = ch.get('value')
            actual.extend(v if isinstance(v, list) else [v])
    offer = c.get('vendorCode') or ''
    ci = candidate_info(offer, codes(actual))
    reason, action, status = ci['reason'], ci['action'], 'Документ в карточке отсутствует'
    if docs and any(not rejected(d) and active(d, 'startDate', 'endDate') for d in docs):
        reason, status = 'Документ добавлен, положительный вердикт WB пока не получен', 'На проверке / вердикта нет'
        action = 'Дождаться проверки WB; повторно проверить вердикт'
    elif docs and any(rejected(d) for d in docs):
        reason, status = 'WB отклонил документы; действующего одобренного документа нет', 'Документы отклонены'
        translations = {'document_not_found': 'WB не нашёл документ в реестре', 'document_dates_mismatch': 'Даты документа в карточке не совпадают с реестром WB', 'document_inactive': 'WB считает документ недействующим'}
        verdict_reasons = unique(translations.get((d.get('verdict') or {}).get('reason'), '') for d in docs if rejected(d))
        if verdict_reasons:
            reason = '; '.join(verdict_reasons)
        action = 'Исправить причину вердикта WB, реквизиты или подобрать применимый документ'
    elif docs:
        reason, status = 'У добавленных документов нет подтверждённого действующего срока', 'Истёкший срок / даты не подтверждены'
    if ds.get('excludeDocuments') is True:
        reason, status = 'В WB установлен признак «Документы не требуются»; сертификат не добавлен', 'Указано освобождение от документов'
        action = 'Проверить обоснованность освобождения для конкретной модели; при подтверждении загрузка сертификата не требуется'
    doc_text = []
    for d in docs:
        v = d.get('verdict') or {}
        doc_text.append(f'{d.get("number")}: статус={v.get("status")}; verified={v.get("verified")}; причина={v.get("reason")}; до {str(d.get("endDate") or "")[:10]}')
    detail = [ci['detail']]
    ov = ds.get('overallVerdict') or {}
    if ov:
        detail.append(f'Общий вердикт WB: status={ov.get("status")}; reason={ov.get("reason")}')
    detail.extend(f'Вердикт по {d.get("number")}: {(d.get("verdict") or {}).get("reason")}' for d in docs if rejected(d))
    letter = ci['letter'] + '. WB: отказное письмо не загружается; при подтверждённом освобождении используется признак «Документы не требуются»'
    skus = [s for z in c.get('sizes') or [] for s in z.get('skus') or []]
    output['WB'].append([offer, reason, status, c.get('brand') or '', c.get('title') or '', joined(actual), str(c['nmID']), joined(skus), joined(doc_text) or 'В карточке нет документов', ci['numbers'], joined(detail), action, letter, ci['urls'], 'Документы не требуются: да' if ds.get('excludeDocuments') is True else 'Документы не требуются: нет', snap['wb_catalog']['checked_at']])

for platform, rows in output.items():
    rows.sort(key=lambda r: (r[14] == 'Архив', r[3].casefold(), r[2], r[0]))
    assert len({r[6] for r in rows}) == len(rows), f'Duplicate IDs: {platform}'
    assert all(r[0] and r[1] for r in rows)
    counts[platform] = {'rows': len(rows), 'unique_articles': len({r[0] for r in rows}), 'statuses': dict(Counter(r[2] for r in rows)), 'reasons': dict(Counter(r[1] for r in rows)), 'archived': sum(r[14] == 'Архив' for r in rows)}

result = {'date': TODAY, 'headers': HEAD, 'sheets': output, 'counts': counts, 'checked': {k: snap[k].get('checked_at') for k in ('ozon_products', 'ozon_certificates', 'wb_catalog')}, 'source': str(AUDIT / 'live_marketplaces_snapshot_export_20261026.json'), 'platform_docs': {'WB': 'https://seller.wildberries.ru/instructions/ru/ru/material/certificates-and-conformity-declarations', 'Ozon': 'https://seller.ozon.ru/media/dictionary/otkaznoe-pismo/'}}
(HERE / 'export_data.json').write_text(json.dumps(result, ensure_ascii=False))
(HERE / 'export_summary.json').write_text(json.dumps({k: result[k] for k in ('date', 'counts', 'checked', 'source', 'platform_docs')}, ensure_ascii=False, indent=2))
print(json.dumps(counts, ensure_ascii=False, indent=2))
