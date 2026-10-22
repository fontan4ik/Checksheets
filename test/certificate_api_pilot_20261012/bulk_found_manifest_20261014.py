"""Offline manifest of confirmed upload plans; unknown evidence remains explicit skips.

No marketplace requests and no local document deletion. CSV/local hash-map entries
are an inventory, never an authorization to infer dates, legal numbers or scope.
"""
from __future__ import annotations
import collections
import csv
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from reconcile_approved_ozon_docs_to_wb import norm_number

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
ASSIGNMENTS = ROOT / 'output_to_user/certificates/document_assignments.csv'
LOCAL_MAP = ROOT / 'test/certificate_cleanup_20261006/local_map.json'
CORPUS_SKIP_PREFIXES = (
    'all_found_wb_raw_pagination_status_', 'all_found_wb_cards_snapshot_',
    'all_found_ozon_products_snapshot_', 'all_found_ozon_certificates_snapshot_',
    'all_source_certificates_pipeline_state_', 'all_source_certificates_native_state_',
    'all_source_certificates_final_state_', 'found_document_text_extraction_progress_',
)


def corpus_json_paths():
    return sorted(p for p in BASE.glob('*.json') if not p.name.startswith(CORPUS_SKIP_PREFIXES))


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def typename(value, number=''):
    value = str(value or '').lower()
    if value in ('declaration', 'декларация') or 'деклараци' in value:
        return 'declaration'
    if value in ('certificate_of_conformity', 'certificate') or 'сертификат' in value:
        return 'certificate_of_conformity'
    if re.search(r'\b[ДD]-[A-ZА-Я]{2}', number, re.I) or 'BY/112 11.01' in number:
        return 'declaration'
    if re.search(r'\b[СC]-[A-ZА-Я]{2}', number, re.I):
        return 'certificate_of_conformity'
    return None


def legal(number):
    return bool(re.search(r'\b(?:RU|KZ|KG|AM|BY)\s*[ДDСC]-', number, re.I) or
                re.search(r'BY/112\s+11\.01', number, re.I))


def first(data, *keys):
    return next((data[k] for k in keys if data.get(k) is not None), None)


def target_rows(value):
    if isinstance(value, dict):
        return [dict(v, offer_id=k) for k, v in value.items() if isinstance(v, dict)]
    return [v for v in (value or []) if isinstance(v, dict)]


def file_candidates(d):
    out=[]
    for k in ('upload_file','source_file','source_pdf','source','source_files','local_source_files','files'):
        v=d.get(k)
        if isinstance(v, dict): out.append(v)
        elif isinstance(v, list): out.extend(x for x in v if isinstance(x,dict))
        elif isinstance(v,str): out.append({'path':v,'sha256':first(d,'source_sha256','file_sha256')})
    for k,h in [('file_path','file_sha256'),('source_pdf_path','source_pdf_sha256'),('file','file_sha256')]:
        if d.get(k):out.append({'path':d[k],'sha256':d.get(h) or d.get('sha256_actual')})
    return out


def verified_file(candidates, hash_files):
    checked=[]
    for entry in candidates:
        digest=str(entry.get('sha256') or entry.get('sha256_actual') or '')
        names=[entry.get('path') or entry.get('file')]
        if digest: names.extend(hash_files.get(digest,[]))
        for name in names:
            if not name: continue
            path=Path(name)
            if not path.is_absolute():path=ROOT/path
            if not path.is_file():continue
            if path.suffix.lower()!='.pdf':continue
            if not re.fullmatch(r'[0-9a-f]{64}',digest):continue
            actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if actual==digest:return {'path':str(path.resolve()),'sha256':digest,'size':path.stat().st_size}
            checked.append(str(path))
    return None


def build_manifest():
    today=dt.datetime.now(dt.timezone.utc).date()
    with ASSIGNMENTS.open(encoding='utf-8-sig',newline='') as fh: rows=list(csv.DictReader(fh))
    local=load(LOCAL_MAP)
    brand_counts=collections.Counter(r.get('Бренд подтвержденный') or r.get('Бренд Ozon') or 'unknown' for r in rows)
    source_groups={}
    offer_brand={r['Артикул продавца']:r.get('Бренд подтвержденный') or r.get('Бренд Ozon') or '' for r in rows}
    hash_files=collections.defaultdict(list)
    for g in local.get('groups',[]):
        hash_files[g.get('sha256','')].extend(f['path'] for f in g.get('files',[]) if f.get('path'))
    for row in rows:
        brand=row.get('Бренд подтвержденный') or row.get('Бренд Ozon') or 'unknown'
        number=row.get('Номер/название документа','')
        key=(brand,typename(row.get('Тип документа'),number) or 'unknown',norm_number(number) or number)
        item=source_groups.setdefault(key,{'brand':brand,'number':number,'type_code':key[1],'offers':set(),'applicability':set(),'hashes':set()})
        item['offers'].add(row['Артикул продавца']);item['applicability'].add(row.get('Применимость',''))
        if row.get('SHA256 фактический'):item['hashes'].add(row['SHA256 фактический'])
    corpus=[]
    for path in corpus_json_paths():
        if path.name.startswith('bulk_found_'):continue
        d=load(path)
        if isinstance(d,dict):corpus.append((path,d))
    blocked={}; edge_blocks=collections.defaultdict(set)
    def block(number,reason):
        if legal(str(number or '')):blocked[norm_number(number)]=reason
    # Confirmed production-lot restrictions and unresolved scope contradictions.
    for path,d in corpus:
        number=first(d,'number','document_number','record_number') or ''
        low=path.name.lower()
        if ('00356' in str(number) or '52132' in str(number) or
            ('navigator' in low and '08110' in str(number)) or
            ('inhome' in low and '37790' in str(number)) or
            ('feron' in low and '01452' in str(number))):
            block(number,'known_unresolved_production_lot_or_product_scope_restriction')
        if d.get('marketplace_mutation_allowed') is False and d.get('mutation_blocker'):
            block(number,str(d['mutation_blocker']))
        for g in d.get('candidate_groups',[]):
            if not isinstance(g,dict):continue
            n=g.get('number_as_platform_candidate') or g.get('number','')
            if str(g.get('decision','')).startswith(('hold','exclude')):
                # An assessed gap is not the whole document: restrict listed edges,
                # keep prior separately-confirmed exact scope plans eligible.
                for t in g.get('targets',[]):
                    if isinstance(t,dict) and t.get('offer_id'):edge_blocks[norm_number(n)].add(t['offer_id'])
    assessment=load(BASE/'all_groups_candidate_assessment_20261014.json')
    rejected_gap_keys={norm_number(g.get('number_as_platform_candidate','')) for g in assessment.get('candidate_groups',[]) if str(g.get('decision','')).startswith(('hold','exclude'))}
    for gap in load(BASE/'ozon_all_groups_binding_gap_candidates_20261014.json').get('exact_binding_candidates',[]):
        key=norm_number(gap.get('number',''))
        if key in rejected_gap_keys and gap.get('offer_id'):edge_blocks[key].add(gap['offer_id'])
    # Latest scoped 05783 inventory is authoritative; revisions (2) excluded.
    latest05783=load(BASE/'arlight_05783_fresh_live_preflight_20261014.json')
    allowed05783={t['offer_id'] for t in latest05783.get('targets',[]) if t.get('offer_id')}
    groups={}; skips=[]; candidate_count=0
    def adapt(d,path,gate=False):
        nonlocal candidate_count
        record=first(d,'record','certificate','certificate_info','live_record','ozon_certificate_record') or {}
        if not isinstance(record,dict):record={}
        number=str(first(d,'number','document_number','record_number') or record.get('certificate_number') or '')
        if not number:
            nums=(d.get('source_map_group') or {}).get('document_numbers',[])
            if len({norm_number(n) for n in nums})==1 and nums:number=nums[0]
        if not legal(number):return
        candidate_count+=1
        key=norm_number(number)
        typ=typename(first(d,'type_code','ozon_type_code','document_type','type','ozon_create_type') or record.get('type_code'),number)
        issue=first(d,'issue_date','fsa_registry_issue_date') or record.get('issue_date')
        expiry=first(d,'expire_date','expiry_date','fsa_registry_expiry_date') or record.get('expire_date')
        evidence=bool(first(d,'registry_evidence','fsa_record','registry_url','fsa_url','fsa_registry_url','fsa_official_url','official_registry_url','official_eaeu_record_url','fsa_registry_product_scope') or
                      d.get('evidence') and d.get('source_url'))
        explicit=gate or d.get('eligible_for_write') is True or d.get('marketplace_mutation_allowed') is True or any(d.get(k) is True for k in ('ready_for_ozon_create_and_binding','ready_for_wb_full_read_and_ozon_create_or_bind','safe_to_bind_missing_only','ready_to_bind_three'))
        # Canonical Feron plans contain registry status plus reviewed exact workbook.
        if path.name.startswith('feron_') and 'ozon_plan' in path.name and (d.get('registry_evidence') or d.get('fsa_record')) and d.get('product_scope'):explicit=True
        reason=None
        if key in blocked:reason=blocked[key]
        elif not evidence or not explicit:reason='no_explicit_confirmed_upload_scope_plan'
        elif typ not in ('declaration','certificate_of_conformity'):reason='unknown_document_type'
        try:
            start=dt.date.fromisoformat(str(issue)[:10]);end=dt.date.fromisoformat(str(expiry)[:10])
            if not(start<=today<=end and start<=end):reason='expired_future_or_invalid_dates'
        except ValueError:reason='missing_or_invalid_dates'
        rawtargets=first(d,'targets','ozon_targets','ozon_products','offers') or []
        targets=[]
        for t in target_rows(rawtargets):
            offer=str(t.get('offer_id') or '')
            if not offer or not t.get('product_id') or not t.get('sku'):continue
            if t.get('is_archived') or t.get('archived') or t.get('active') is False:continue
            if t.get('ozon_ready') is False or t.get('ozon_blockers'):continue
            if offer in edge_blocks[key]:continue
            if '05783' in number and (not latest05783.get('eligible_for_write') or offer not in allowed05783):continue
            brands=t.get('brand_values') or t.get('ozon_brand_values') or t.get('ozon_brand') or []
            brand=t.get('brand') or t.get('brand_from_assignment') or (brands[0] if brands else '') or offer_brand.get(offer,'') or ('Feron' if path.name.startswith('feron_') else '')
            if isinstance(brand,list):brand=brand[0] if len(brand)==1 else ''
            if brand:brand_counts.setdefault(str(brand),0)
            targets.append({'offer_id':offer,'product_id':str(t['product_id']),'sku':str(t['sku']),'brand':brand})
        if not targets:reason=reason or 'no_confirmed_exact_active_targets'
        upload=verified_file(file_candidates(d),hash_files) if not reason else None
        if not upload and not reason:reason='verified_original_pdf_missing_changed_or_not_pdf'
        if reason:
            skips.append({'source':str(path),'number':number,'type_code':typ,'reason':reason});return
        country=d.get('country') or d.get('certificate_country') or ('BY' if 'BY/112' in number else 'RU')
        scope=first(d,'allowed_tnved','fsa_tnved_codes','fsa_registry_tnved_scope','tnved_scope','tnved','official_pdf_scope_codes')
        if isinstance(scope,str):scope=[scope]
        new={'number':number,'type_code':typ,'issue_date':str(issue)[:10],'expire_date':str(expiry)[:10],
             'country':country,'accordance_type':d.get('accordance_type') or 'EAEU','upload_file':upload,
             'targets':targets,'evidence_files':[str(path)],'requires_live_preflight':True}
        if scope:new['allowed_tnved']=scope
        prior=groups.get((typ,key))
        if prior:
            if (prior['issue_date'],prior['expire_date'],prior['upload_file']['sha256'])!=(new['issue_date'],new['expire_date'],upload['sha256']):
                # Do not silently choose between different original files or dates.
                blocked[key]='conflicting_confirmed_plan_hash_or_dates';return
            merged={t['offer_id']:t for t in prior['targets']}
            for t in targets:
                old=merged.get(t['offer_id'])
                if old and (old['product_id'],old['sku'])!=(t['product_id'],t['sku']):
                    edge_blocks[key].add(t['offer_id']);continue
                merged[t['offer_id']]=t
            prior['targets']=list(merged.values());prior['evidence_files'].append(str(path))
        else:groups[(typ,key)]=new
    # Only reviewed explicit plans/preflights. Old broad CSV never authorizes new scope.
    for path,d in corpus:
        if path.name=='group4_ozon_plan.json':
            for action in d.get('actions',[]):adapt(action,path,gate=bool(action.get('evidence') and action.get('source_url')))
        elif any(x in path.name for x in ('ozon_plan','preflight','ozon_execution')):
            verified_execution=bool('ozon_execution' in path.name and d.get('certificate_id') and d.get('create_response') and first(d,'fsa_registry_url','registry_evidence'))
            adapt(d,path,gate=verified_execution)
    # Jazzway audited original + later exact TNVED mutation preflight.
    jazz_source=load(BASE/'jazzway_37909_ozon_fresh_preflight_20261014.json')
    jazz=load(BASE/'jazzway_37909_in_scope_ozon_mutation_preflight_20261014.json')
    if jazz.get('fresh_verified_in_scope_count')==len(jazz.get('targets',[])) and jazz.get('targets'):
        audited=jazz_source.get('official_document',{})
        record=jazz.get('record',{})
        hash_=jazz.get('source_document_sha256')
        source=next(({'path':f.get('path'),'sha256':hash_} for f in audited.get('local_files',[]) if f.get('actual_sha256')==hash_),None)
        if source:
            ready_jazz=dict(jazz,number=jazz.get('record_number'),type_code=record.get('type_code'),
                            issue_date=record.get('issue_date'),expire_date=record.get('expire_date'),
                            source_file=source,evidence='Audited original official PDF; exact current product/TNVED scope',
                            source_url=audited.get('source_url'))
            adapt(ready_jazz,BASE/'jazzway_37909_in_scope_ozon_mutation_preflight_20261014.json',gate=True)
    # IEK: official exact article feed plus reviewed original PDF. Download/hash alone
    # is insufficient; require confirmed PDF text number or existing accepted upload.
    iekplan=load(BASE/'iek_new_offer_document_plan.json')
    iekaudit=load(BASE/'iek_new_docs_pdf_text_audit.json')
    for doc in iekaudit.get('documents',[]):
        if doc.get('number_found_in_pdf_text') is True:
            reviewed=dict(doc,document_type=doc.get('type_code'),file_sha256=doc.get('sha256_actual'),
                          evidence='Exact official manufacturer article-to-document feed; legal number confirmed in PDF text',
                          country='RU',accordance_type='EAEU')
            adapt(reviewed,BASE/'iek_new_docs_pdf_text_audit.json',gate=True)
    # Ensure every indexed group has a recorded final eligibility decision.
    ready_keys={k for _,k in groups if k not in blocked}
    for item in source_groups.values():
        key=norm_number(item['number'])
        if key in ready_keys:continue
        app=item['applicability']
        if key in blocked:reason=blocked[key]
        elif not legal(item['number']):reason='not_full_legal_number_or_supporting_document'
        elif not app.intersection({'Подтверждено источником','Подтверждено статусом покрытия'}):reason='unconfirmed_partial_historical_or_supporting_source'
        else:reason='no_verified_dated_exact_scope_upload_plan'
        skips.append({'brand':item['brand'],'number':item['number'],'type_code':item['type_code'],
                      'offer_count':len(item['offers']),'reason':reason,'source':str(ASSIGNMENTS)})
    ready=[]
    for (_,key),group in groups.items():
        if key in blocked:
            skips.append({'number':group['number'],'reason':blocked[key],'source':group['evidence_files']});continue
        group['targets']=[t for t in group['targets'] if t['offer_id'] not in edge_blocks[key]]
        if group['targets']:ready.append(group)
    for group in local.get('groups',[]):
        nums=group.get('document_numbers',[])
        if any(norm_number(n) in ready_keys for n in nums):continue
        skips.append({'source':str(LOCAL_MAP),'sha256':group.get('sha256'),'numbers':nums,
                      'offer_count':len(group.get('bindings',[])),
                      'reason':'local_hash_map_is_not_verified_upload_plan',
                      'issues':group.get('issues',[])})
    bybrand=collections.Counter(t['brand'] for g in ready for t in g['targets'])
    return {'built_at':dt.datetime.now(dt.timezone.utc).isoformat(),'groups':ready,'skips':skips,
            'blocked_document_keys':sorted(blocked),'blocked_reasons':blocked,
            'blocked_binding_brands':{norm_number('ЕАЭС N RU Д-CN.РА07.В.01452/23'):['Feron']},
            'coverage':{'assignment_rows':len(rows),'assignment_source_groups':len(source_groups),
                        'source_brands':dict(sorted(brand_counts.items())),
                        'local_hash_groups':len(local.get('groups',[])),
                        'corpus_json_files_scanned':len(corpus),'candidate_plans_examined':candidate_count,
                        'ready_document_groups':len(ready),'ready_target_edges':sum(len(g['targets']) for g in ready),
                        'ready_brands':dict(bybrand),'skip_entries':len(skips),
                        'wb_projection':'runner may project fresh approved current exact Ozon bindings across every brand, excluding blocked keys; platform approval does not authorize new Ozon scope'},
            'local_cleanup_allowed':False}

if __name__=='__main__':
    result=build_manifest()
    dest=BASE/'bulk_found_manifest_20261014.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'manifest':str(dest),'coverage':result['coverage'],'blocked_keys':result['blocked_document_keys']},ensure_ascii=False,indent=2))
