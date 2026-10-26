#!/usr/bin/env python3
"""Read-only candidate screen: confirmed source, dates, model edge, live Ozon identity/TN VED/coverage."""
from __future__ import annotations
import csv, hashlib, json, re, subprocess, sys, unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number
REPORT=HERE/'confirmed_source_gaps_allbrand_postreconcile_final_20261023.json'
SNAP=HERE/'live_marketplaces_snapshot_export_20261026.json'
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
OUT=HERE/'all_found_candidates_ozon_screen_20261026.json'
PDFTEXT='/Users/vladimirgrebennikov/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/poppler/bin/pdftotext'

def attr_values(row, ident):
 by={str(x.get('id')):x for x in row.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (by.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def codes(values):return sorted({str(x).split(' - ',1)[0].strip() for x in values if str(x).strip()})
def extract_text(p):
 try:return subprocess.run([PDFTEXT,'-layout',str(p),'-'],capture_output=True,text=True,timeout=30).stdout or ''
 except Exception:return ''
def expiry_from_text(t):
 patterns=[r'(?:декларация|сертификат)[^\n.]{0,120}действительн\w*[^\n]{0,100}?по\s+(\d{2}\.\d{2}\.\d{4})',r'срок действия[^\n]{0,120}?(?:по|до)\s+(\d{2}\.\d{2}\.\d{4})']
 for pat in patterns:
  ms=re.findall(pat,t,re.I)
  if ms:
   for raw in reversed(ms):
    try:return datetime.strptime(raw,'%d.%m.%Y').date().isoformat()
    except ValueError:pass
 return None
def document_type(g,t):
 label=str(g.get('document_type') or '').casefold(); body=t[:3000].casefold()
 if any(w in label for w in ('добровольн','пожар','отказ','госрегистрац','санитар')):return None
 if 'деклара' in label or 'декларация о соответствии' in body:return 'declaration'
 if 'сертификат соответствия' in label or 'сертификат соответствия' in body:return 'certificate_of_conformity'
 return None

def main():
 data=json.loads(REPORT.read_text()); groups=[]
 for g in data.get('candidate_source_groups') or []:
  n=int(g.get('missing_ozon_offers') or 0); app=g.get('applicability_counts') or {}
  if g.get('document_number') and g.get('sha256_matches') is True and n>0 and sum(int(v or 0) for v in app.values())==n and all(('Подтверждено' in k) for k in app):groups.append(g)
 assignments=defaultdict(list)
 with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r.get('Применимость','').startswith('Подтверждено'):assignments[norm_number(r.get('Номер/название документа'))].append(r)
 snapshot=json.loads(SNAP.read_text()); snap_certs=snapshot['ozon_certificates']['certificates']; snap_products=snapshot['ozon_products']['products']
 id_by_sku={str(p.get('sku')):str(p.get('product_id')) for p in snap_products if p.get('sku') and p.get('product_id')}
 covered=set(); reserved={}
 today=date.today().isoformat()
 for c in snap_certs:
  status=c.get('status_code');current=(str(c.get('issue_date') or '')[:10]<=today and str(c.get('expire_date') or '')[:10]>=today)
  for b in c.get('live_bindings') or []:
   pid=str(b.get('product_id') or '');sku=str(b.get('sku') or '')
   if not pid or id_by_sku.get(sku)!=pid:continue
   if status=='approved' and current and b.get('product_status_code')=='approved':covered.add(pid)
   if b.get('product_status_code') not in ('declined','rejected','invalid'):reserved[pid]={'number':c.get('certificate_number'),'id':c.get('certificate_id'),'record_status':status,'binding_status':b.get('product_status_code')}
 # Include fresh documents created after the baseline snapshot, including the two new Navigator records.
 client=Client(); current_certs=[]
 for page in range(1,101):
  res=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {};batch=res.get('certificates')
  if not isinstance(batch,list):raise RuntimeError('live_certificate_list_incomplete')
  current_certs.extend(batch)
  if not batch or page>=int(res.get('page_count') or 0):break
 snap_ids={str(c.get('certificate_id')) for c in snap_certs}; new_records=[c for c in current_certs if str(c.get('certificate_id')) not in snap_ids]
 for c in new_records:
  cid=c.get('certificate_id')
  if not cid:continue
  for b in client.ozon_bindings(cid):
   pid=str(b.get('product_id') or '')
   if not pid:continue
   status=b.get('product_status_code')
   reserved[pid]={'number':c.get('certificate_number'),'id':cid,'record_status':c.get('status_code'),'binding_status':status}
   if c.get('status_code')=='approved' and str(c.get('issue_date') or '')[:10]<=today and str(c.get('expire_date') or '')[:10]>=today and status=='approved':covered.add(pid)
 # Build source-verified document groups and offers.
 docs=[]; offer_to_docs=defaultdict(list)
 for g in groups:
  key=norm_number(g['document_number']); expected=int(g['missing_ozon_offers']); rows=[]
  # Hash plus normalized number identifies the precise source assignment set.
  for r in assignments.get(key,[]):
   sha=str(r.get('SHA256 фактический') or '').strip().lower()
   if sha and sha==str(g.get('actual_sha256') or '').lower():rows.append(r)
  src=ROOT/g['source_file'];actual=hashlib.sha256(src.read_bytes()).hexdigest() if src.is_file() else ''
  txt=extract_text(src) if src.is_file() else '';tn=codes(re.findall(r'(?<!\d)\d{10}(?!\d)',txt))
  flat_text=re.sub(r'\s+',' ',txt.casefold()); cutoff=any(s in flat_text for s in ['с даты изготовления отобранных образцов','дата изготовления отобранных образцов','даты изготовления образцов','дата изготовления образцов','с даты изготовления образца'])
  exp=expiry_from_text(txt);typ=document_type(g,txt);c=next((x for x in current_certs if norm_number(x.get('certificate_number'))==key),None)
  d={'number':g['document_number'],'brand':g.get('brand'),'document_type_source':g.get('document_type'),'ozon_type_code':typ,'source_file':g.get('source_file'),'source_sha256':actual,'source_hash_matches_report':actual==g.get('actual_sha256'),'expected_offer_count':expected,'assignment_row_count':len(rows),'offers':[],'tnved_codes_in_pdf':tn,'expiry_from_pdf':exp,'sample_date_cutoff':cutoff,'source_record_examples':g.get('validity_examples'),'model_evidence_examples':(g.get('scope_examples') or [])[:2],'existing_ozon_record':({k:c.get(k) for k in ['certificate_id','certificate_number','type_code','accordance_type_code','status_code','issue_date','expire_date','products_count']} if c else None),'text_extracted':bool(txt)}
  for r in rows:
   offer=str(r.get('Артикул продавца') or '').strip()
   if offer:
    d['offers'].append(offer);offer_to_docs[offer].append(d)
  d['assignment_exact_count']=len(d['offers'])==expected and len(set(d['offers']))==expected
  d['prelive_candidate']=(d['source_hash_matches_report'] and d['assignment_exact_count'] and bool(tn) and exp is not None and exp>=today and not cutoff and typ is not None and c is None)
  docs.append(d)
 offers=sorted(offer_to_docs); products=defaultdict(list); attrs=defaultdict(list)
 for i in range(0,len(offers),100):
  batch=offers[i:i+100]
  for p in client.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []:products[str(p.get('offer_id') or '')].append(p)
  for a in client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or []:attrs[str(a.get('offer_id') or '')].append(a)
 exact_docs=[]
 for d in docs:
  targets=[]
  for offer in d['offers']:
   ps,ats=products.get(offer,[]),attrs.get(offer,[])
   if len(ps)!=1 or len(ats)!=1:targets.append({'offer_id':offer,'problems':['non_unique_live_product_or_attributes']});continue
   p,a=ps[0],ats[0];pid=str(p.get('product_id') or p.get('id') or '');brand=attr_values(a,85);tn= codes(attr_values(a,22232)); problems=[]
   if p.get('is_archived') is not False:problems.append('archived_or_unclear')
   if [x.casefold() for x in brand]!=[str(d['brand'] or '').casefold()]:problems.append('brand_mismatch')
   if len(tn)!=1 or tn[0] not in d['tnved_codes_in_pdf']:problems.append('tnved_out_of_scope')
   if pid in covered:problems.append('already_covered_by_active_approved_document')
   if pid in reserved:problems.append('already_linked_to_another_current_or_pending_document')
   targets.append({'offer_id':offer,'product_id':pid,'sku':str(p.get('sku') or ''),'brand_values':brand,'tnved_codes':tn,'current_approved_covered':pid in covered,'other_binding':reserved.get(pid),'problems':problems})
  d['live_targets']=targets;d['safe_target_count']=sum(not x.get('problems') for x in targets)
  d['screen_result']='ready_for_registry_verification' if d['prelive_candidate'] and d['safe_target_count']>0 and d.get('assignment_exact_count') else 'skip_or_manual_review'
  if d['screen_result']=='ready_for_registry_verification':exact_docs.append(d)
 summary={'checked_at_utc':now(),'read_only':True,'today':today,'source_candidate_count':len(groups),'candidate_documents_screened':len(docs),'live_offers_checked':len(offers),'live_certificates_checked':len(current_certs),'snapshot_time':snapshot['ozon_products'].get('checked_at'),'post_snapshot_records_checked':len(new_records),'candidate_exact_count':len(exact_docs),'screen_result_counts':dict(Counter(d['screen_result'] for d in docs)),'next_candidates':[{'number':d['number'],'brand':d['brand'],'type':d['ozon_type_code'],'offers':d['offers'],'safe_target_count':d['safe_target_count'],'expiry':d['expiry_from_pdf'],'fsa_check_required':True,'source_file':d['source_file']} for d in sorted(exact_docs,key=lambda x:x['safe_target_count'],reverse=True)],'documents':docs,'no_marketplace_writes':True,'no_files_deleted':True}
 OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:summary[k] for k in ['source_candidate_count','candidate_documents_screened','live_offers_checked','live_certificates_checked','post_snapshot_records_checked','candidate_exact_count','screen_result_counts','next_candidates']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
