#!/usr/bin/env python3
"""Read-only screen of confirmed Navigator source documents against current Ozon cards."""
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
OUT=HERE/'navigator_candidate_screen_ozon_20261026.json'
PDFTEXT='/Users/vladimirgrebennikov/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/poppler/bin/pdftotext'

def attr_values(row, ident):
 by={str(x.get('id')):x for x in row.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (by.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def norm_codes(v):return sorted({str(x).split(' - ',1)[0].strip() for x in v if str(x).strip()})
def extract_text(p):
 r=subprocess.run([PDFTEXT,'-layout',str(p),'-'],capture_output=True,text=True,timeout=60)
 return r.stdout or ''
def extract_expiry(t):
 pats=[r'(?:декларация|сертификат)[^\n.]{0,100}действительн\w*[^\n]{0,100}?по\s+(\d{2}\.\d{2}\.\d{4})',r'срок действия[^\n]{0,100}?(?:по|до)\s+(\d{2}\.\d{2}\.\d{4})']
 for pat in pats:
  ms=re.findall(pat,t,re.I)
  if ms:
   try:return datetime.strptime(ms[-1],'%d.%m.%Y').date().isoformat()
   except ValueError:pass
 return None

def main():
 report=json.loads(REPORT.read_text()); groups=[]
 for g in report.get('candidate_source_groups') or []:
  if (g.get('brand')=='Navigator' and g.get('document_number') and g.get('sha256_matches') is True
      and int(g.get('missing_ozon_offers') or 0)>0
      and sum(int(x or 0) for x in (g.get('applicability_counts') or {}).values())==int(g.get('missing_ozon_offers') or 0)):
   groups.append(g)
 assignments=defaultdict(list)
 with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r.get('Бренд подтвержденный')=='Navigator' and r.get('Применимость')=='Подтверждено источником':assignments[norm_number(r.get('Номер/название документа'))].append(r)
 snapshot=json.loads(SNAP.read_text()); pbyid={str(p.get('product_id')):p for p in snapshot['ozon_products']['products']}; pbyid.update({str(p.get('id')):p for p in snapshot['ozon_products']['products'] if p.get('id')})
 covered=set()
 today=date.today().isoformat()
 for c in snapshot['ozon_certificates']['certificates']:
  if c.get('status_code')!='approved' or str(c.get('issue_date') or '')[:10]>today or str(c.get('expire_date') or '')[:10]<today:continue
  for b in c.get('live_bindings') or []:
   p=next((x for x in snapshot['ozon_products']['products'] if str(x.get('sku'))==str(b.get('sku'))),None)
   if b.get('product_status_code')=='approved' and p and str(p.get('product_id'))==str(b.get('product_id')):covered.add(str(b.get('product_id')))
 # The two Navigator documents created in this live session must also be treated as already assigned while Ozon checks them.
 covered.update({'704778221','704778236','704778315','704778210','704778151','704778331','704778259','704778285','6025009792','6025341909','6025719632'})
 offer_details={}; docs=[]
 for g in groups:
  rows=assignments.get(norm_number(g['document_number']),[])
  rows=[r for r in rows if r.get('Локальный файл') and Path(r['Локальный файл']).name in Path(g.get('source_file','')).name or r.get('Локальный файл')==g.get('source_file')]
  # Direct number+confirmed-source assignment rows are the primary edge; require exact group count.
  if len(rows)!=int(g['missing_ozon_offers']):
   rows=assignments.get(norm_number(g['document_number']),[])
  if len(rows)!=int(g['missing_ozon_offers']):
   docs.append({'number':g['document_number'],'source_file':g.get('source_file'),'assignment_count':len(rows),'expected_assignment_count':g['missing_ozon_offers'],'screen_result':'assignment_count_mismatch'});continue
  source=ROOT/g['source_file']; sha=hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else ''
  txt=extract_text(source) if source.is_file() else ''
  tn=norm_codes(re.findall(r'(?<!\d)\d{10}(?!\d)',txt))
  cutoff=any(s in txt.casefold() for s in ['с даты изготовления отобранных образцов','даты изготовления образцов','дата изготовления образцов','даты изготовления отобранных образцов'])
  expiry=extract_expiry(txt)
  exact_models=all(str(r.get('Артикул продавца') or '') in str(r.get('Основание сопоставления') or '') or 'exact per-product' in str(r.get('Основание сопоставления') or '').casefold() for r in rows)
  for r in rows:offer_details[str(r.get('Артикул продавца') or '')]=None
  docs.append({'number':g['document_number'],'document_type':g.get('document_type'),'source_file':g.get('source_file'),'source_sha256':sha,'source_hash_matches_group':sha==g.get('actual_sha256'),'offers':[str(r.get('Артикул продавца') or '') for r in rows],'tnved_codes_in_pdf':tn,'expiry_from_pdf':expiry,'sample_date_cutoff':cutoff,'exact_model_assignment_evidence':exact_models,'text_extracted':bool(txt),'screen_result':'pending_live_check'})
 client=Client(); offers=sorted(offer_details)
 products=defaultdict(list); attrs=defaultdict(list)
 for i in range(0,len(offers),100):
  b=offers[i:i+100]
  for p in client.call('ozon','/v3/product/info/list',{'offer_id':b}).get('items') or []:products[str(p.get('offer_id') or '')].append(p)
  for a in client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':b},'limit':len(b)}).get('result') or []:attrs[str(a.get('offer_id') or '')].append(a)
 certs=[]
 for page in range(1,101):
  rr=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {};batch=rr.get('certificates')
  if not isinstance(batch,list):raise RuntimeError('incomplete_certificate_list')
  certs.extend(batch)
  if not batch or page>=int(rr.get('page_count') or 0):break
 cert_by={norm_number(c.get('certificate_number')):c for c in certs}
 for d in docs:
  if d.get('screen_result')!='pending_live_check':continue
  live=[]
  for offer in d['offers']:
   ps,ats=products.get(offer,[]),attrs.get(offer,[])
   if len(ps)!=1 or len(ats)!=1:
    live.append({'offer_id':offer,'problems':['product_or_attributes_not_unique']});continue
   p,a=ps[0],ats[0]; pid=str(p.get('product_id') or p.get('id') or ''); brand=attr_values(a,85); tn=norm_codes(attr_values(a,22232)); problems=[]
   if p.get('is_archived') is not False:problems.append('archived_or_unknown')
   if [x.casefold() for x in brand]!=['navigator']:problems.append('brand_mismatch')
   if len(tn)!=1 or tn[0] not in d['tnved_codes_in_pdf']:problems.append('tnved_mismatch')
   if pid in covered:problems.append('already_covered_by_active_approved_document')
   live.append({'offer_id':offer,'product_id':pid,'sku':str(p.get('sku') or ''),'name':p.get('name'),'brand_values':brand,'tnved_codes':tn,'covered_by_active_approved_document':pid in covered,'problems':problems})
  c=cert_by.get(norm_number(d['number']))
  if c:live.append({'record_conflict':{k:c.get(k) for k in ['certificate_id','certificate_number','status_code','issue_date','expire_date']}})
  d['live_targets']=live;d['current_ozon_record_exists']=bool(c)
  d['screen_result']='candidate_exact' if (d['source_hash_matches_group'] and d['exact_model_assignment_evidence'] and d['text_extracted'] and d['expiry_from_pdf'] and d['expiry_from_pdf']>=today and not d['sample_date_cutoff'] and not c and all(not x.get('problems') for x in live if 'offer_id' in x) and len([x for x in live if 'offer_id' in x])==len(d['offers'])) else 'skip_or_manual_review'
 out={'checked_at_utc':now(),'read_only':True,'candidate_group_count':len(groups),'offers_checked':len(offers),'today':today,'snapshot_checked_at':snapshot['ozon_products'].get('checked_at'),'live_certificate_count':len(certs),'candidate_exact_count':sum(d.get('screen_result')=='candidate_exact' for d in docs),'documents':docs,'no_marketplace_writes':True,'no_files_deleted':True}
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'candidate_group_count':len(groups),'offers_checked':len(offers),'live_certificate_count':len(certs),'candidates':[{'number':d['number'],'expiry':d.get('expiry_from_pdf'),'offers':d.get('offers'),'tnved':d.get('tnved_codes_in_pdf')} for d in docs if d.get('screen_result')=='candidate_exact'],'skip_counts':dict(Counter(d.get('screen_result') for d in docs))},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
