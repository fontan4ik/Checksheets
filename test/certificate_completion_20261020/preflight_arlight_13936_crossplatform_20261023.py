#!/usr/bin/env python3
"""Read-only exact preflight for the remaining Arlight declaration 13936/25 edges."""
from __future__ import annotations
import csv, hashlib, json, re, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents, UPDATE_CARD_FIELDS, wb_datetime
from run_all_found_certificates_20261014 import merge_wb, wb_scope_error
NUMBER='ЕАЭС N RU Д-HK.РА02.В.13936/25'
KEY=norm_number(NUMBER)
ISSUE='2025-02-20'; EXPIRY='2030-02-19'; CODE='8539519009'
SOURCE=ROOT/'output_to_user/certificates/additional_search/brand_research/arlight/docs/43E37E0571137C4AAAC15B9DD9C12AD5.pdf'
EXPECTED_SHA='cea94551b999c5316c668ce488490f92bae305bff0f444d5f6b80e6bdddeac51'
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
EDGES=HERE/'all_confirmed_source_assignments_live_resume_20261023.csv'
OUT=HERE/'arlight_13936_crossplatform_live_preflight_20261023.json'
CONFIRMED={'Подтверждено статусом покрытия','Подтверждено источником'}
def tnved(values): return {str(x or '').split(' - ',1)[0].strip() for x in values if str(x or '').split(' - ',1)[0].strip()}
def wb_codes(card):
    out=[]
    for char in card.get('characteristics') or []:
        label=''.join(str(char.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' in label or 'тнвед' in label:
            raw=char.get('value'); out.extend(raw if isinstance(raw,list) else [raw])
    return tnved(out)
def main():
    sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if sha!=EXPECTED_SHA: raise RuntimeError('source_hash_mismatch')
    assignments=[]
    with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if norm_number(row.get('Номер/название документа'))==KEY and row.get('Применимость') in CONFIRMED:
                assignments.append(row)
    by_offer=defaultdict(list)
    for row in assignments: by_offer[str(row.get('Артикул продавца') or '').strip()].append(row)
    with EDGES.open(encoding='utf-8-sig',newline='') as f:
        targets=[r for r in csv.DictReader(f) if r['normalized_number']==KEY and r['ozon_state']=='missing_binding' and r['wb_state']=='missing_document']
    offers=sorted({r['offer_id'] for r in targets})
    if len(targets)!=192 or len(offers)!=192: raise RuntimeError(f'unexpected_candidate_count rows={len(targets)} offers={len(offers)}')
    for offer in offers:
        if len(by_offer.get(offer,[]))!=1: raise RuntimeError(f'source_assignment_missing_or_ambiguous:{offer}')
        row=by_offer[offer][0]
        if row.get('Бренд подтвержденный')!='Arlight' or not row.get('Локальный файл'): raise RuntimeError(f'source_assignment_identity_or_file:{offer}')
        assigned_source=(ROOT/row['Локальный файл']).resolve()
        if not assigned_source.is_file() or hashlib.sha256(assigned_source.read_bytes()).hexdigest()!=EXPECTED_SHA: raise RuntimeError(f'source_file_hash_mismatch:{offer}')
    client=Client()
    records=[]; page=1; seen=set()
    while True:
        result=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100})['result']
        batch=result['certificates']
        for cert in batch:
            cid=str(cert.get('certificate_id'))
            if cid in seen: raise RuntimeError('duplicate_certificate_page')
            seen.add(cid); records.append(cert)
        if not batch or page>=result['page_count']: break
        page+=1
    docs=[c for c in records if norm_number(c.get('certificate_number'))==KEY]
    exact=[c for c in docs if c.get('type_code')=='declaration' and c.get('accordance_type_code')=='EAEU' and str(c.get('issue_date',''))[:10]==ISSUE and str(c.get('expire_date',''))[:10]==EXPIRY]
    if len(exact)!=1: raise RuntimeError(f'ozon_exact_record_count:{len(exact)}')
    cert=exact[0]
    if cert.get('status_code')!='approved' or not (ISSUE<=date.today().isoformat()<=EXPIRY): raise RuntimeError('ozon_record_not_current_approved')
    bindings=client.ozon_bindings(cert['certificate_id'])
    binding_by_pid={str(b.get('product_id')):b for b in bindings}
    pinfo=[]; attrs=[]
    for start in range(0,len(offers),100):
        batch=offers[start:start+100]
        pinfo.extend(client.call('ozon','/v3/product/info/list',{'offer_id':batch})['items'])
        attrs.extend(client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':100}).get('result') or [])
    products_by_offer=defaultdict(list)
    for p in pinfo: products_by_offer[str(p.get('offer_id') or '')].append(p)
    attrs_by_offer=defaultdict(list)
    for row in attrs: attrs_by_offer[str(row.get('offer_id') or '')].append(row)
    wb_cards={}
    target_data=[]
    mutation_candidates=[]
    for offer in offers:
        rows=products_by_offer.get(offer,[])
        ar=attrs_by_offer.get(offer,[])
        if len(rows)!=1 or len(ar)!=1: raise RuntimeError(f'ozon_product_identity_missing_or_duplicate:{offer}')
        p=rows[0]; aa={str(x.get('id')):x for x in ar[0].get('attributes') or []}
        brand_values=[str(v.get('value') or '').strip() for v in (aa.get('85') or {}).get('values') or []]
        codes=tnved([v.get('value') for v in (aa.get('22232') or {}).get('values') or []])
        if p.get('is_archived') is not False or not str(p.get('sku') or ''): raise RuntimeError(f'ozon_not_active_or_missing_sku:{offer}')
        if len(brand_values)!=1 or brand_values[0].casefold()!='arlight': raise RuntimeError(f'ozon_brand_mismatch:{offer}:{brand_values}')
        if codes!={CODE}: raise RuntimeError(f'ozon_tnved_mismatch:{offer}:{sorted(codes)}')
        b=binding_by_pid.get(str(p.get('product_id') or p.get('id')))
        if b and str(b.get('sku'))!=str(p.get('sku')): raise RuntimeError(f'ozon_binding_identity_conflict:{offer}')
        if b and b.get('product_status_code')!='approved': raise RuntimeError(f'ozon_binding_already_present_not_approved:{offer}:{b.get("product_status_code")}')
        card_rows=client.wb_cards(offer)
        if len(card_rows)!=1: raise RuntimeError(f'wb_card_missing_or_duplicate:{offer}:{len(card_rows)}')
        card=card_rows[0]; wb_cards[offer]=card
        if str(card.get('vendorCode') or '')!=offer: raise RuntimeError(f'wb_vendor_code_mismatch:{offer}')
        if wb_scope_error(card,{'allowed_tnved':[CODE]},{'brand':'Arlight'}): raise RuntimeError(f'wb_brand_or_tnved_mismatch:{offer}')
        existing=[d for d in copy_documents(card) if norm_number(d.get('number'))==KEY]
        if existing: raise RuntimeError(f'wb_document_already_present_needs_reconcile:{offer}')
        if not b: mutation_candidates.append({'offer_id':offer,'product_id':str(p.get('product_id') or p.get('id')),'sku':str(p['sku'])})
        target_data.append({'offer_id':offer,'product_id':str(p.get('product_id') or p.get('id')),'sku':str(p['sku']),
            'name':p.get('name'),'brand':brand_values,'tnved':sorted(codes),'wb_nmID':str(card.get('nmID')),
            'wb_brand':card.get('brand'),'wb_tnved':sorted(wb_codes(card)),'ozon_existing_binding':b})
        if len(target_data)%25==0:
            print(json.dumps({'preflight_wb_cards_checked':len(target_data),'targets':len(offers)},ensure_ascii=False),flush=True)
    desired={'type':2,'number':NUMBER,'startDate':ISSUE+'T00:00:00Z','endDate':EXPIRY+'T00:00:00Z','isEndless':False}
    payloads=[]
    for offer in offers:
        card=wb_cards[offer]
        merged=merge_wb(card,[desired])
        if merged is None: raise RuntimeError(f'wb_merge_unexpected_no_payload:{offer}')
        payloads.append(merged)
    out={'checked_at_utc':now(),'read_only':True,'fsa_registry_url':'https://pub.fsa.gov.ru/rds/declaration/view/19916418/product',
         'fsa_status':'Действует','fsa_issue_date':ISSUE,'fsa_expire_date':EXPIRY,'fsa_tnved':[CODE],
         'document_number':NUMBER,'ozon_certificate_id':cert['certificate_id'],'ozon_status':cert.get('status_code'),
         'ozon_issue_date':str(cert.get('issue_date'))[:10],'ozon_expire_date':str(cert.get('expire_date'))[:10],
         'ozon_live_binding_count':len(bindings),'assignment_rows':len(assignments),'target_count':len(offers),
         'source_pdf':str(SOURCE),'source_pdf_sha256':sha,'source_hash_matches':True,'targets':target_data,
         'ozon_missing_bindings':len(mutation_candidates),'ozon_bind_candidates':mutation_candidates,
         'wb_document_missing_cards':len(payloads),'wb_payloads':payloads}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(OUT),'target_count':len(offers),'ozon_cert_id':cert['certificate_id'],'ozon_status':cert.get('status_code'),
      'ozon_missing_bindings':len(mutation_candidates),'wb_missing_cards':len(payloads),'fsa_status':out['fsa_status'],
      'all_ozon_code_8539519009':True,'all_wb_cards_exact_and_in_scope':True},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
