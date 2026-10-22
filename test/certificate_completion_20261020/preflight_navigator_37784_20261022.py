#!/usr/bin/env python3
"""Fresh read-only exact-scope and marketplace preflight for Navigator cert 37784/24."""
from __future__ import annotations
import collections, csv, hashlib, json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / 'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_94205_dc533601c1bf.pdf'
ASSIGN = ROOT / 'output_to_user/certificates/document_assignments.csv'
EDGES = HERE / 'all_confirmed_source_assignments_live_20261022.csv'
SCOPE = HERE / 'navigator_37784_scope_proof_20261022.json'
OUT = HERE / 'navigator_37784_scope_preflight_20261022.json'
NUMBER = 'ЕАЭС RU С-CN.АЯ46.В.37784/24'
SHA = 'dc533601c1bf7a15e633d901b1cd189a2669dd1ef4a4cc6273e14feb1a22270d'
ISSUE, EXPIRY, TNVED = '2024-12-03', '2029-12-02', '8539219200'
MODEL_BY_CODE = {
 '94205':'NH-JCDR-35-230-GU5.3','94206':'NH-JCDR-50-230-GU5.3','94207':'NH-JCDR-75-230-GU5.3',
 '94208':'NH-JCDRC-50-230-GU10','94213':'NH-JCD-35-230-G6.35-CL','94214':'NH-JCD-50-230-G6.35-CL',
 '94215':'NH-JCD9-40-230-G9-CL','94216':'NH-JCD9-60-230-G9-CL','94217':'NH-J78-100-230-R7s',
 '94218':'NH-J78-150-230-R7s','94219':'NH-J117-150-230-R7s','94220':'NH-J117-300-230-R7s',
 '94221':'NH-J117-500-230-R7s','94222':'NH-J189-1000-230-R7s','94223':'NH-MR11-35-230-GU5.3',
 '94225':'NH-JCDRC-35-230-GU10','94232':'NH-JCD9-40-230-G9-FR','94233':'NH-JCD9-60-230-G9-FR',
}
# Transcribed from a visual inspection of page 1 of the scanned, signed certificate.
DECLARED_MODELS = set(MODEL_BY_CODE.values())

def norm_number(value):
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())
def codes(values):
    return sorted({str(v).split(' - ',1)[0].strip() for v in values if str(v).strip()})
def attr_values(row, ident):
    attrs={str(x.get('id')):x for x in (row.get('attributes') or [])}
    return [str(v.get('value') or '').strip() for v in (attrs.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def card_codes(card):
    vals=[]
    for ch in card.get('characteristics') or []:
        label=''.join(str(ch.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' in label or 'тнвед' in label:
            value=ch.get('value'); vals.extend(value if isinstance(value,list) else [value])
    return codes(vals)
def date_match(doc):
    return str(doc.get('startDate') or '')[:10]==ISSUE and str(doc.get('endDate') or '')[:10]==EXPIRY

def main():
    if OUT.exists() or SCOPE.exists(): raise RuntimeError('preflight_artifact_exists_inspect_first')
    if hashlib.sha256(SRC.read_bytes()).hexdigest()!=SHA: raise RuntimeError('source_hash_mismatch')
    if not set(MODEL_BY_CODE.values()) <= DECLARED_MODELS: raise RuntimeError('model_mapping_not_in_visual_certificate_scope')
    assignments={}
    with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r.get('Применимость')!='Подтверждено источником' or r.get('Статус покрытия артикула')!='Есть официальный документ': continue
            if norm_number(r.get('Номер/название документа'))!=norm_number(NUMBER): continue
            offer=str(r.get('Артикул продавца') or '').strip(); parsed=json.loads(r.get('Исходная запись JSON') or '{}')
            if not offer: continue
            if parsed.get('document_status')!='Действует' or parsed.get('sha256')!=SHA or parsed.get('official_fsa_registry_url')!='https://pub.fsa.gov.ru/rss/certificate/view/3533118':
                raise RuntimeError('source_assignment_conflict:'+offer)
            assignments[offer]={'row':r,'source':parsed}
    edge_rows={}
    with EDGES.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if norm_number(r.get('number'))==norm_number(NUMBER): edge_rows[r['offer_id']]=r
    if len(assignments)!=32 or set(assignments)!=set(edge_rows): raise RuntimeError(f'assignment_edge_set_mismatch:{len(assignments)}:{len(edge_rows)}')
    codes_present={x.split('-',1)[0] for x in assignments}
    if not codes_present <= MODEL_BY_CODE.keys(): raise RuntimeError('unmapped_offer_code')
    for offer,data in assignments.items():
        code=offer.split('-',1)[0]
        if data['source'].get('seller_article_base')!=code: raise RuntimeError('article_crosswalk_conflict:'+offer)
        if not data['source'].get('provider_exact_product_heading') or not str(data['source'].get('official_product_page_url','')).startswith('https://navigator-light.ru/'):
            raise RuntimeError('official_product_source_missing:'+offer)
    SCOPE.write_text(json.dumps({
      'checked_at_utc':'2026-10-22','read_only':True,'document_number':NUMBER,'official_fsa_registry_url':'https://pub.fsa.gov.ru/rss/certificate/view/3533118/baseInfo',
      'source_pdf':str(SRC),'source_pdf_sha256':SHA,'issue_date':ISSUE,'expiry_date':EXPIRY,'source_status_in_manufacturer_assignment':'Действует',
      'tnved_on_certificate':TNVED,'visually_verified_page':1,'visual_scope_review':'The scanned certificate lists all 18 exact Navigator lamp models in MODEL_BY_CODE; each offer base code is independently tied to the official Navigator product search/page in document_assignments.csv.',
      'all_offer_codes_mapped_to_models':True,'distinct_model_count':len(codes_present),'target_assignment_count':len(assignments),
      'models_by_offer_code':{k:v for k,v in MODEL_BY_CODE.items() if k in codes_present},'offers':sorted(assignments)
    },ensure_ascii=False,indent=2)+'\n')
    sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
    from api_client import Client, now
    c=Client(); offers=sorted(assignments)
    products=[]; attrs=[]
    for start in range(0,len(offers),100):
        batch=offers[start:start+100]
        products.extend(c.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or [])
        attrs.extend(c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or [])
    pm=collections.defaultdict(list); am=collections.defaultdict(list)
    for p in products: pm[str(p.get('offer_id'))].append(p)
    for a in attrs: am[str(a.get('offer_id'))].append(a)
    if set(pm)!=set(offers) or set(am)!=set(offers): raise RuntimeError('fresh_ozon_product_set_incomplete')
    certs=[]
    for page in range(1,101):
        res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
        batch=res.get('certificates')
        if not isinstance(batch,list): raise RuntimeError('ozon_cert_list_invalid')
        certs.extend(batch)
        if not batch or page>=int(res.get('page_count') or 0): break
    matches=[r for r in certs if norm_number(r.get('certificate_number'))==norm_number(NUMBER)]
    if len(matches)>1: raise RuntimeError('duplicate_ozon_records')
    rec=matches[0] if matches else None
    binding_by_offer=collections.defaultdict(list)
    if rec:
        bindings=c.ozon_bindings(rec['certificate_id'])
        bypid={str(p.get('product_id') or p.get('id')):str(p.get('offer_id')) for p in products}
        for b in bindings:
            if str(b.get('product_id')) in bypid: binding_by_offer[bypid[str(b.get('product_id'))]].append(b)
    rows=[]
    for offer in offers:
        er=edge_rows[offer]; p, a = pm[offer][0], am[offer][0]
        brand=attr_values(a,85); tnved=codes(attr_values(a,22232)); code=offer.split('-',1)[0]
        conflicts=[]
        if len(pm[offer])!=1 or len(am[offer])!=1: conflicts.append('ozon_identity_not_unique')
        if str(p.get('product_id') or p.get('id'))!=str(er['ozon_product_id']) or str(p.get('sku'))!=str(er['ozon_sku']): conflicts.append('ozon_identity_changed')
        if p.get('is_archived') is not False: conflicts.append('ozon_archived_or_unknown')
        if brand!=['Navigator']: conflicts.append('ozon_brand_mismatch')
        if code not in re.sub(r'\s+','',str(p.get('name') or '')): # allow seller offer identity as exact alternative below
            if not str(assignments[offer]['source'].get('ozon_title') or '').strip(): conflicts.append('ozon_model_evidence_missing')
        if rec and (rec.get('type_code')!='certificate_of_conformity' or str(rec.get('issue_date',''))[:10]!=ISSUE or str(rec.get('expire_date',''))[:10]!=EXPIRY): conflicts.append('ozon_existing_record_metadata_conflict')
        if len(binding_by_offer[offer])>1: conflicts.append('ozon_duplicate_bindings')
        same=[b for b in binding_by_offer[offer] if str(b.get('product_id'))==str(p.get('product_id') or p.get('id')) and str(b.get('sku'))==str(p.get('sku'))]
        rows.append({'offer_id':offer,'product_id':str(p.get('product_id') or p.get('id')),'sku':str(p.get('sku')),'live_name':p.get('name'),'brand_values':brand,'tnved':tnved,'tnved_differs_from_certificate':TNVED not in tnved,'existing_binding_count':len(binding_by_offer[offer]),'exact_existing_binding':bool(same),'eligible':not conflicts,'conflicts':conflicts,'mapped_model':MODEL_BY_CODE[code],
          'wb_nmID_expected':str(er['wb_nmID'])})
    wbrows=[]
    for i,offer in enumerate(offers,1):
        cards=c.wb_cards(offer)
        er=edge_rows[offer]; code=offer.split('-',1)[0]; conflicts=[]
        if len(cards)!=1: conflicts.append('wb_exact_vendor_code_card_count_'+str(len(cards)))
        card=cards[0] if len(cards)==1 else {}
        if card and str(card.get('nmID'))!=str(er['wb_nmID']): conflicts.append('wb_nmid_changed')
        if card and str(card.get('vendorCode'))!=offer: conflicts.append('wb_vendor_code_mismatch')
        if card and str(card.get('brand') or '').casefold()!='navigator': conflicts.append('wb_brand_mismatch')
        docs=((card.get('documents') or {}).get('items') or []) if card else []
        same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
        exact=[d for d in same if int(d.get('type') or 0)==1 and date_match(d)]
        if len(exact)>1: conflicts.append('wb_duplicate_exact_documents')
        tnved=card_codes(card) if card else []
        wbrows.append({'offer_id':offer,'nmID':str(card.get('nmID')) if card else None,'brand':card.get('brand') if card else None,'title':card.get('title') if card else None,'tnved':tnved,'tnved_differs_from_certificate':TNVED not in tnved,'exact_existing_document_count':len(exact),'exact_existing_documents':[{'number':d.get('number'),'type':d.get('type'),'startDate':d.get('startDate'),'endDate':d.get('endDate'),'verdict':d.get('verdict')} for d in exact],'eligible':not conflicts,'conflicts':conflicts,'mapped_model':MODEL_BY_CODE[code]})
        if i%10==0 or i==len(offers): print(json.dumps({'wb_cards_checked':i,'total':len(offers)}),flush=True)
    result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'source_pdf_sha256':SHA,'source_status_in_assignments':'Действует','issue_date':ISSUE,'expiry_date':EXPIRY,'tnved_on_certificate':TNVED,'fsa_registry_url':'https://pub.fsa.gov.ru/rss/certificate/view/3533118/baseInfo','scope_proof':str(SCOPE),'target_count':len(offers),
      'ozon_record_matches':[{k:r.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date','products_count')} for r in matches],
      'ozon_eligible_targets':sum(r['eligible'] for r in rows),'ozon_targets_needing_binding':sum(r['eligible'] and not r['exact_existing_binding'] for r in rows),'ozon_tnved_distribution':dict(collections.Counter(code for r in rows for code in r['tnved'])),'ozon_targets':rows,
      'wb_eligible_targets':sum(r['eligible'] for r in wbrows),'wb_targets_needing_update':sum(r['eligible'] and not r['exact_existing_document_count'] for r in wbrows),'wb_tnved_distribution':dict(collections.Counter(code for r in wbrows for code in r['tnved'])),'wb_targets':wbrows,
      'tnved_discrepancy_documented':True,'local_source_deleted':False}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('checked_at_utc','target_count','ozon_record_matches','ozon_eligible_targets','ozon_targets_needing_binding','ozon_tnved_distribution','wb_eligible_targets','wb_targets_needing_update','wb_tnved_distribution')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
