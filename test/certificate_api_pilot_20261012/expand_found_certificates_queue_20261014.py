"""Offline exhaustive source admission. No API requests or document deletion.

Reuses explicit historical scope blocks, but never requires a manually named plan.
Every new edge comes from an exact official source assignment and SHA-verified PDF.
The runner must still perform fresh product/TNVED and existing-record preflight.
"""
from __future__ import annotations
import collections
import csv
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from bulk_found_manifest_20261014 import BASE, ROOT, ASSIGNMENTS, LOCAL_MAP, load, legal, typename, corpus_json_paths, build_manifest as build_base_manifest
from reconcile_approved_ozon_docs_to_wb import norm_number

CACHE = BASE / 'found_document_text_cache_20261014'
DEST = BASE / 'expanded_found_certificates_manifest_20261014.json'
START = ('issue_date','start_date','date_start','valid_from','Дата начала','fsa_registry_issue_date')
END = ('expire_date','expiry_date','end_date','valid_until','date_end','Дата окончания','fsa_registry_expiry_date')
NUM = ('number','certificate_number','document_number','record_number','Номер документа','Документ/номер')
HASH = ('sha256','sha256_actual','file_sha256','source_sha256','source_pdf_sha256','SHA256','SHA-256')
MONTHS = ('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')


def first(d, keys):
    if not isinstance(d, dict):
        return ''
    return next((d[k] for k in keys if d.get(k) not in (None,'')), '')


def walk(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():
            if isinstance(child,(dict,list)): yield from walk(child)
    elif isinstance(value,list):
        for child in value: yield from walk(child)


def date(value):
    s=str(value).strip()
    try: return dt.date.fromisoformat(s[:10]).isoformat()
    except ValueError: pass
    m=re.fullmatch(r'(\d{1,2})[./](\d{1,2})[./](\d{4})',s)
    if m:
        try:return dt.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
        except ValueError:pass
    return ''


def text_dates(text):
    out=set()
    for m in re.finditer(r'\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b',text):
        v=date(f'{m[1]}.{m[2]}.{m[3]}')
        if v:out.add(v)
    for m in re.finditer(r'\b(\d{1,2})\s*[»”"]?\s*('+ '|'.join(MONTHS)+r')\s+(20\d{2})',text.lower()):
        v=date(f'{m[1]}.{MONTHS.index(m[2])+1}.{m[3]}')
        if v:out.add(v)
    out.update(m.group(0) for m in re.finditer(r'\b20\d{2}-\d{2}-\d{2}\b',text))
    return out


def range_from_pdf(text):
    # Only an explicitly labelled validity interval, never min/max arbitrary dates.
    segment=re.search(r'(?:срок\s+действия|действител[еь]н[^\n]{0,30})\s*[:：]?\s*([^\n]{0,350}(?:\n[^\n]{0,180})?)',text,re.I)
    if not segment:return ('','')
    ds=sorted(text_dates(segment[0]))
    return tuple(ds) if len(ds)==2 else ('','')


def pdf_numbers(text):
    pattern=r'(?:ЕАЭС\s*(?:N|№)?\s*)?(?:RU|KZ|KG|AM|BY)\s*[ДDСC]\s*-\s*[A-ZА-Я]{2}\s*[.．]\s*[A-ZА-Я0-9]{2,8}\s*[.．]\s*[ВB]\s*[.．]\s*\d{4,7}\s*/\s*\d{2}'
    return {norm_number(m[0]):re.sub(r'\s+','',m[0]) for m in re.finditer(pattern,text,re.I)}


def exact_source(row):
    return (row.get('Применимость') in ('Подтверждено источником','Подтверждено статусом покрытия')
            and any(x in row.get('Класс/вид источника','').lower() for x in ('официаль','реестр','производител'))
            and row.get('URL документа','').startswith('https://')
            and row.get('Основание сопоставления')
            and not any(x in row.get('Основание сопоставления','').lower() for x in ('не подтвержден','неподтвержден','предполож')))


def build_expanded_manifest():
    original=build_base_manifest()
    today=dt.datetime.now(dt.timezone.utc).date().isoformat()
    local=load(LOCAL_MAP)
    hashpaths=collections.defaultdict(list)
    hashnums=collections.defaultdict(set)
    for group in local.get('groups',[]):
        sha=group.get('sha256','')
        hashpaths[sha].extend(f['path'] for f in group.get('files',[]) if f.get('path'))
        hashnums[sha].update(n for n in group.get('document_numbers',[]) if legal(n))
    snapshot=load(BASE/'all_found_ozon_products_snapshot_20261014.json')
    if not snapshot.get('complete'):raise RuntimeError('Complete current Ozon snapshot required')
    products={p['offer_id']:p for p in snapshot.get('products',[]) if not p.get('is_archived') and not p.get('is_autoarchived')}
    with ASSIGNMENTS.open(encoding='utf-8-sig',newline='') as fh: rows=list(csv.DictReader(fh))
    byhash=collections.defaultdict(list)
    meta=collections.defaultdict(list)
    for row in rows:
        sha=row.get('SHA256 фактический','')
        if not re.fullmatch('[0-9a-f]{64}',sha):continue
        try: raw=json.loads(row.get('Исходная запись JSON') or '{}')
        except ValueError:raw={}
        byhash[sha].append((row,raw))
        meta[sha].append((raw,str(ASSIGNMENTS)))
        if row.get('Локальный файл'):hashpaths[sha].append(row['Локальный файл'])
        for n in (row.get('Номер/название документа',''), first(raw,NUM)):
            if legal(str(n)):hashnums[sha].add(str(n))
    # Recursive adapter recognizes source metadata in every brand's audit, not names.
    for path in corpus_json_paths():
        if path==DEST or path.name.startswith(('all_found_certificates_bulk_state','expanded_found')):continue
        for obj in walk(load(path)):
            sha=str(first(obj,HASH))
            if re.fullmatch('[0-9a-f]{64}',sha):
                meta[sha].append((obj,str(path)))
                n=str(first(obj,NUM))
                if legal(n):hashnums[sha].add(n)
                for k in ('file','file_path','local_file','source_pdf_path','path'):
                    if isinstance(obj.get(k),str):hashpaths[sha].append(obj[k])
    # IEK current XML feed exact article assignments are newer than the consolidated CSV.
    iek=load(BASE/'iek_new_offer_document_plan.json')
    for obj in iek.get('document_assignments',[]):
        url=obj.get('source_url','')
        sha=next(iter(re.findall(r'([0-9a-f]{64})\.pdf',url)), '')
        if not sha:continue
        row={'Артикул продавца':obj.get('offer_id',''),'Бренд подтвержденный':obj.get('brand','IEK'),
             'Применимость':'Подтверждено источником','Класс/вид источника':'официальный XML каталог производителя',
             'URL документа':url,'Основание сопоставления':f"Точный артикул официального XML: {obj.get('official_article','')}",
             'Номер/название документа':obj.get('number',''),'Тип документа':obj.get('document_type','')}
        if obj.get('official_article'):
            byhash[sha].append((row,obj));meta[sha].append((obj,str(BASE/'iek_new_offer_document_plan.json')))
            hashnums[sha].add(obj.get('number',''))
            for f in obj.get('existing_local_files',[]):hashpaths[sha].extend(f.get('paths',[]))
    for sha in hashpaths:
        if re.fullmatch('[0-9a-f]{64}',sha):byhash.setdefault(sha,[])
    groups={(g['type_code'],norm_number(g['number'])):g for g in original['groups']}
    blocked=original.get('blocked_reasons',{}); edgeblocks=collections.defaultdict(set)
    for path in corpus_json_paths():
        for obj in walk(load(path)):
            if str(obj.get('decision','')).startswith(('hold','exclude')):
                n=norm_number(obj.get('number_as_platform_candidate') or obj.get('number',''))
                edgeblocks[n].update(t['offer_id'] for t in obj.get('targets',[]) if isinstance(t,dict) and t.get('offer_id'))
    assessment=load(BASE/'all_groups_candidate_assessment_20261014.json')
    held={norm_number(g.get('number_as_platform_candidate','')) for g in assessment.get('candidate_groups',[]) if str(g.get('decision','')).startswith(('hold','exclude'))}
    for obj in load(BASE/'ozon_all_groups_binding_gap_candidates_20261014.json').get('exact_binding_candidates',[]):
        k=norm_number(obj.get('number',''))
        if k in held:edgeblocks[k].add(obj.get('offer_id'))
    latest=load(BASE/'arlight_05783_fresh_live_preflight_20261014.json')
    allowed05783={t['offer_id'] for t in latest.get('targets',[]) if t.get('offer_id')}
    skips=[]; added=0; admitted_hashes=set()
    for sha, source_rows in byhash.items():
        def skip(reason,number=''):
            skips.append({'sha256':sha,'number':number,'reason':reason,'offer_count':len({r['Артикул продавца'] for r,_ in source_rows})})
        if not source_rows:skip('local_hash_has_no_exact_official_article_assignment');continue
        candidates=[]
        for name in dict.fromkeys(hashpaths[sha]):
            p=Path(name)
            if not p.is_absolute():p=ROOT/p
            if p.is_file() and p.suffix.lower()=='.pdf':candidates.append(p)
        pdf=next((p for p in candidates if hashlib.sha256(p.read_bytes()).hexdigest()==sha),None)
        if not pdf:skip('verified_local_original_pdf_missing');continue
        cache=CACHE/f'{sha}.txt'
        text=cache.read_text(encoding='utf-8') if cache.is_file() else ''
        cache_meta=load(CACHE/f'{sha}.json')
        if not text.strip() or not cache_meta.get('complete') or cache_meta.get('sha256')!=sha or not cache_meta.get('original_unchanged'):
            skip('pdf_text_or_ocr_cache_missing_or_incomplete');continue
        numbers=pdf_numbers(text)
        known={norm_number(n):n for n in hashnums[sha] if legal(n)}
        matches=set(known).intersection(numbers)
        # Full legal number printed in the official PDF itself is authoritative.
        if not known and len(numbers)==1:known=numbers;matches=set(numbers)
        if len(matches)!=1:skip('pdf_legal_number_missing_or_ambiguous');continue
        key=matches.pop();number=known[key]
        if key in blocked:skip(blocked[key],number);continue
        statuses=' '.join(str(obj.get(k,'')) for obj,_ in meta[sha] if isinstance(obj,dict) for k in ('record_status','document_status','Статус документа на 2026-10-01','Статус на 2026-10-01'))
        if re.search(r'прекращ|приостанов|аннулир|отмен|revoked|suspended|cancelled',statuses,re.I):
            skip('official_source_status_revoked_suspended_or_cancelled',number);continue
        scope_text=re.sub(r'\s+',' ',text)
        if re.search(r'изготовлен\w*\s+(?:с|от)\s+\d|партия\s+(?:продукции|товара)|изготовлен\w*.{0,160}отобранн\w*\s+образц|изготовлен\w*.{0,80}(?:не\s+ранее|начиная\s+с|с\s+даты)',scope_text,re.I):
            skip('production_lot_or_sample_date_scope_requires_separate_review',number);continue
        ranges=set()
        for obj,_ in meta[sha]:
            n=str(first(obj,NUM))
            if n and legal(n) and norm_number(n)!=key:continue
            start=date(first(obj,START));end=date(first(obj,END))
            if start and end:ranges.add((start,end))
        if not ranges:
            pair=range_from_pdf(text)
            if all(pair):ranges.add(pair)
        if len(ranges)!=1:skip('authoritative_date_range_missing_or_conflicting',number);continue
        start,end=next(iter(ranges))
        if not start<=today<=end:skip('expired_or_future_document',number);continue
        if not {start,end}.issubset(text_dates(text)):
            skip('authoritative_dates_not_confirmed_in_pdf_text',number);continue
        typ=typename('',number)
        if not typ:skip('unknown_document_type',number);continue
        tnved=set()
        for segment in re.finditer(r'(?:ТН\s*ВЭД|ТНВЭД)[^\n]{0,240}(?:\n[^\n]{0,180})?',text,re.I):
            tnved.update(re.findall(r'(?<!\d)\d{10}(?!\d)',segment[0]))
            for code in re.findall(r'(?<!\d)\d{4}\s+\d{2}\s+\d{3}\s+\d(?!\d)',segment[0]):
                tnved.add(re.sub(r'\s+','',code))
        if not tnved and (typ,key) not in groups:
            skip('official_pdf_tnved_scope_not_readable',number);continue
        targets={}
        for row,raw in source_rows:
            offer=row['Артикул продавца'];p=products.get(offer)
            if not exact_source(row) or not p or not p.get('sku'):continue
            if offer in edgeblocks[key]:continue
            if '05783' in number and (not latest.get('eligible_for_write') or offer not in allowed05783):continue
            brand=row.get('Бренд подтвержденный') or row.get('Бренд Ozon') or ''
            if brand in original.get('blocked_binding_brands',{}).get(key,[]):continue
            targets[offer]={'offer_id':offer,'product_id':str(p.get('id') or p.get('product_id')),'sku':str(p['sku']),'brand':brand,
                            'scope_evidence':row.get('Основание сопоставления'),'source_url':row.get('URL документа')}
        if not targets:skip('no_exact_current_source_confirmed_target',number);continue
        group={'number':number,'type_code':typ,'issue_date':start,'expire_date':end,'country':('BY' if 'BY/112' in number else next(iter(re.findall(r'\b(RU|KZ|KG|AM|BY)\s*[ДDСC]-',number,re.I)), 'RU')),
               'accordance_type':'EAEU','upload_file':{'path':str(pdf.resolve()),'sha256':sha,'size':pdf.stat().st_size},
               'targets':list(targets.values()),'evidence_files':sorted({p for _,p in meta[sha]}),
               'requires_live_preflight':True,'source_evidence_verified':True,'source_text_cache':str(cache),'admission':'official_exact_assignment_sha_number_date_pdf_confirmed'}
        if tnved:group['allowed_tnved']=sorted(tnved)
        old=groups.get((typ,key))
        if old:
            if (old['issue_date'],old['expire_date'])!=(start,end):skip('conflict_with_existing_confirmed_plan_dates',number);continue
            # Keep previously reviewed scope restrictions. No broadening TNVED list.
            if old.get('allowed_tnved'):group['allowed_tnved']=old['allowed_tnved']
            oldtargets={t['offer_id']:t for t in old['targets']};added+=len(set(targets)-set(oldtargets))
            oldtargets.update(targets);old['targets']=list(oldtargets.values())
        else:groups[(typ,key)]=group;added+=len(targets)
        admitted_hashes.add(sha)
    for g in groups.values():g['source_evidence_verified']=True
    result=dict(original,groups=list(groups.values()),expansion_skips=skips)
    result['built_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    result['coverage']=dict(original['coverage'],ready_document_groups=len(groups),ready_target_edges=sum(len(g['targets']) for g in groups.values()),
                            ready_brands=dict(collections.Counter(t['brand'] for g in groups.values() for t in g['targets'])),
                            exhaustive_hash_groups_scanned=len(byhash),admitted_source_hashes=len(admitted_hashes),expanded_target_edges=added,
                            expansion_skip_reasons=dict(collections.Counter(s['reason'] for s in skips)))
    result['original_manual_ready_groups']=len(original['groups'])
    result['local_cleanup_allowed']=False
    return result

# Public builder name is intentionally the exhaustive implementation.
build_manifest=build_expanded_manifest

if __name__=='__main__':
    result=build_expanded_manifest()
    DEST.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'manifest':str(DEST),'coverage':result['coverage']},ensure_ascii=False,indent=2))
