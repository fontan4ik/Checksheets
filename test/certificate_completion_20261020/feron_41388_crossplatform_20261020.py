#!/usr/bin/env python3
"""Reconcile Feron declaration 41388/22 on Ozon and WB.

The FSA record was checked live on 2026-10-20: active through 2027-08-07,
Feron series TL/FN, TN VED 9405420022. Writes are journaled and idempotent;
the source scan is retained unless all required platform associations exist.
"""
from __future__ import annotations
import argparse, base64, collections, datetime as dt, json, re, sys
from pathlib import Path

BASE=Path(__file__).resolve().parent
API=BASE.parent/'certificate_api_pilot_20261012'
FERON=Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
BOOK=FERON/'Сопоставление_артикулов_и_файлов_документов.xlsx'
IMAGE=FERON/'00_Оригиналы_файлов'/'Декларация__41388_22_Светильники_светодиодные_для_подсветки,_серии_TL,_FN,_тм_Feron._Декларация_по_037._1__926750e81a.jpg'
PDF=BASE/'source_docs'/'feron_41388_22_upload.pdf'
NUMBER='ЕАЭС N RU Д-CN.РА05.В.41388/22'
FSA='https://pub.fsa.gov.ru/rds/declaration/view/16921349/product'
ISSUE='2022-08-08'; EXPIRY='2027-08-07'; CODE='declaration'
PLAN=BASE/'feron_41388_crossplatform_plan_20261020.json'
EXEC=BASE/'feron_41388_crossplatform_execution_20261020.json'
READBACK=BASE/'feron_41388_crossplatform_readback_20261020.json'
sys.path.insert(0,'/opt/homebrew/lib/python3.14/site-packages'); sys.path.insert(0,str(API))
from api_client import Client,digest,now
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS,UPDATE_CARD_FIELDS,comparable_card,doc_key,wb_datetime

def atomic(path,value):
 tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)); tmp.replace(path)
def suffix(v):
 m=re.search(r'(?<!\d)(\d{4,6})\s*/\s*(\d{2,4})(?!\d)',str(v or '')); return m.group(1)+'/'+m.group(2) if m else ''
def raw_docs(card): return list((card.get('documents') or {}).get('items') or [])
def projection(card): return [{k:x[k] for k in DOC_FIELDS if k in x} for x in raw_docs(card)]
def merge(card,wanted):
 docs=projection(card); same=[x for x in docs if doc_key(x)==doc_key(wanted)]
 if same:
  if any((str(x.get('startDate',''))[:10],str(x.get('endDate',''))[:10])!=(ISSUE,EXPIRY) for x in same): raise ValueError('WB date conflict')
  return None
 payload={k:card[k] for k in UPDATE_CARD_FIELDS if k in card}; payload['documents']={'items':docs+[wanted],'excludeDocuments':False}; return payload
def read_ozon_docs(c):
 out=[]
 for page in range(1,101):
  batch=(c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}).get('certificates')
  if not isinstance(batch,list): raise RuntimeError('Ozon list incomplete')
  out+=batch
  if len(batch)<100:return out
 raise RuntimeError('Ozon list exceeded pagination limit')
def read_bindings(c,cid):
 out=[]; cursor=0; expected=None
 while True:
  r=c.call('ozon','/v1/product/certificate/products/list',{'certificate_id':cid,'last_id':cursor,'limit':500}).get('result') or {}; batch=r.get('items'); count=r.get('count')
  if not isinstance(batch,list) or not isinstance(count,int):raise RuntimeError('Invalid binding readback')
  if expected is None:expected=count
  elif count!=expected:raise RuntimeError('Binding count changed')
  out+=batch
  if len(out)==expected:return out
  if not batch or len(out)>expected:raise RuntimeError('Binding pagination incomplete')
  nxt=int(batch[-1].get('product_id') or 0)
  if nxt<=cursor:raise RuntimeError('Binding cursor did not advance')
  cursor=nxt
def build_plan(c):
 import openpyxl
 if not all(p.is_file() for p in (BOOK,IMAGE,PDF)):raise RuntimeError('Workbook or source file missing')
 wb=openpyxl.load_workbook(BOOK,read_only=True,data_only=True); targets=[]
 for r in wb['Артикул-файл'].iter_rows(min_row=6,values_only=True):
  if suffix(r[6])!='41388/22':continue
  title=str(r[2] or '')
  if not re.search(r'\b(?:TL\d+|FN\d+)\b',title,re.I):raise RuntimeError(f'Unconfirmed TL/FN model: {r[0]}')
  if 'Feron' not in title:raise RuntimeError(f'Workbook brand mismatch: {r[0]}')
  if '2027-08-07' not in str(r[12] or ''):raise RuntimeError(f'Workbook validity mismatch: {r[0]}')
  targets.append({'offer_id':str(r[0]),'article':str(r[1]),'title':title,'product_id':str(r[3]),'sku':str(r[4])})
 if len(targets)!=8 or len({x['offer_id'] for x in targets})!=8 or len({x['sku'] for x in targets})!=8:raise RuntimeError(f'Expected eight exact targets; got {len(targets)}')
 response=c.call('ozon','/v3/product/info/list',{'offer_id':[x['offer_id'] for x in targets]}); products=response.get('items') or response.get('result',{}).get('items') or []
 by_offer={str(x.get('offer_id')):x for x in products}; eligible=[]
 for t in targets:
  p=by_offer.get(t['offer_id'])
  if not p or str(p.get('id'))!=t['product_id'] or str(p.get('sku'))!=t['sku'] or p.get('is_archived') is not False:raise RuntimeError(f'Live Ozon product identity/archive mismatch: {t["offer_id"]}')
  eligible.append({**t,'live_name':p.get('name')})
 certs=read_ozon_docs(c); existing=[x for x in certs if x.get('type_code')==CODE and suffix(x.get('certificate_number'))=='41388/22']
 if len(existing)>1:raise RuntimeError('Duplicate Ozon 41388/22 records found')
 wanted={'type':2,'number':NUMBER,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
 updates=[]; prior=[]; missing=[]
 for t in eligible:
  cards=c.wb_cards(t['offer_id'])
  if not cards:missing.append(t['offer_id']); continue
  if len(cards)!=1 or cards[0].get('vendorCode')!=t['offer_id']:raise RuntimeError(f'WB identity ambiguous: {t["offer_id"]}')
  card=cards[0]
  if str(card.get('brand') or '').strip().casefold()!='feron':raise RuntimeError(f'WB brand mismatch: {t["offer_id"]}')
  try:payload=merge(card,wanted)
  except ValueError as exc:raise RuntimeError(f'WB document date conflict: {t["offer_id"]}') from exc
  row={'offer_id':t['offer_id'],'nmID':str(card.get('nmID')),'title':card.get('title'),'payload':payload,'before':card}
  if payload is None:
   docs=[d for d in raw_docs(card) if doc_key(d)==doc_key(wanted)]
   row['existing_docs']=docs; row['valid_verdict']=any((d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('reason')=='valid' for d in docs); prior.append(row)
  else: updates.append(row)
 return {'checked_at':now(),'number':NUMBER,'type_code':CODE,'fsa_url':FSA,'fsa_status_checked_live':'Действует до 2027-08-07','fsa_scope_checked_live':'Feron, серии TL и FN; TN VED 9405420022','issue_date':ISSUE,'expire_date':EXPIRY,'source_workbook':str(BOOK),'workbook_sha256':digest(BOOK),'original_scan':str(IMAGE),'original_scan_sha256':digest(IMAGE),'source_pdf':str(PDF),'source_pdf_sha256':digest(PDF),'source_pdf_bytes':PDF.stat().st_size,'targets':eligible,'ozon_products_verified':len(products),'ozon_certificate_list_count':len(certs),'ozon_existing_matching_records':existing,'wb_cards_to_update':updates,'wb_already_present':prior,'wb_missing_exact_cards':missing}
def execute(c,plan):
 if EXEC.exists() or READBACK.exists():raise RuntimeError('Execution/readback already exists; do not repeat writes')
 state={'started_at':now(),'phase':'preflight_complete','number':NUMBER,'ozon':{},'wb':{}};atomic(EXEC,state)
 matching=plan['ozon_existing_matching_records']
 if matching:
  x=matching[0]
  if str(x.get('issue_date',''))[:10]!=ISSUE or str(x.get('expire_date',''))[:10]!=EXPIRY or x.get('accordance_type_code')!='EAEU' or x.get('status_code') in {'declined','rejected','invalid','cancelled'}:raise RuntimeError('Existing Ozon metadata conflicts')
  cid=int(x['certificate_id'])
 else:
  seed=plan['targets'][0]; exp=dt.date.fromisoformat(EXPIRY)
  params={'name':'Декларация о соответствии № '+NUMBER,'certificate_type':'DECLARATION','certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,'issue_date':ISSUE+'T00:00:00Z','expired_date':{'date':{'day':exp.day,'month':exp.month,'year':exp.year}},'skus':[seed['sku']],'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(PDF.read_bytes()).decode('ascii'),'name':PDF.name}],'link_to_registry':FSA.replace('/product','')}
  if digest(PDF)!=plan['source_pdf_sha256']:raise RuntimeError('PDF hash changed after preflight')
  state.update(phase='ozon_create_prepared',updated_at=now(),ozon={'seed_offer':seed['offer_id'],'seed_sku':seed['sku'],'pdf_sha256':plan['source_pdf_sha256']});atomic(EXEC,state)
  try:resp=c.call('ozon','/v2/product/certificate/create',{'params':params},mutation=True)
  except Exception as exc:
   state.update(phase='ozon_create_uncertain',error_type=type(exc).__name__,updated_at=now());atomic(EXEC,state);raise RuntimeError('Ozon create outcome uncertain; reconcile list before retry') from None
  cid=int(resp.get('certificate_id') or 0); states=[p.get('state') for p in resp.get('params',[]) if isinstance(p,dict)]
  state['ozon'].update(create_response=resp,certificate_id=cid)
  if not cid or resp.get('status')!='COMPLETED' or not states or set(states)!={'VALID'}:state.update(phase='ozon_create_not_validated',updated_at=now());atomic(EXEC,state);raise RuntimeError('Ozon create was not fully validated')
  state.update(phase='ozon_created',updated_at=now());atomic(EXEC,state)
 certs=read_ozon_docs(c); rec=next((x for x in certs if str(x.get('certificate_id'))==str(cid)),None)
 if not rec or suffix(rec.get('certificate_number'))!='41388/22':raise RuntimeError('Ozon list does not confirm 41388/22')
 lookup=str(rec.get('certificate_number') or ''); info=c.call('ozon','/v1/product/certificate/info',{'certificate_number':lookup}).get('result') or {}
 if int(info.get('certificate_id') or -1)!=cid or info.get('type_code')!=CODE or str(info.get('issue_date',''))[:10]!=ISSUE or str(info.get('expire_date',''))[:10]!=EXPIRY or info.get('accordance_type_code')!='EAEU' or info.get('status_code') in {'declined','rejected','invalid','cancelled'}:raise RuntimeError('Ozon metadata conflicts with FSA')
 prior=read_bindings(c,cid); byid={str(x.get('product_id')):x for x in prior}
 for t in plan['targets']:
  b=byid.get(t['product_id'])
  if b and str(b.get('sku'))!=t['sku']:raise RuntimeError(f'Ozon binding identity conflict: {t["offer_id"]}')
  if b and b.get('product_status_code') in {'declined','rejected','invalid'}:raise RuntimeError(f'Existing binding rejected: {t["offer_id"]}')
 missing=[t['sku'] for t in plan['targets'] if t['product_id'] not in byid]
 if not matching and plan['targets'][0]['sku'] in missing:raise RuntimeError('Ozon seed binding not visible; wait before continuing')
 if missing:
  state.update(phase='ozon_bind_prepared',updated_at=now(),ozon={**state['ozon'],'certificate_id':cid,'initial_binding_count':len(prior),'missing_skus':missing});atomic(EXEC,state)
  try:response=c.call('ozon','/v1/product/certificate/bind',{'certificate_id':cid,'skus':missing},mutation=True)
  except Exception as exc:state.update(phase='ozon_bind_uncertain',error_type=type(exc).__name__,updated_at=now());atomic(EXEC,state);raise RuntimeError('Ozon bind outcome uncertain; read back before retry') from None
  state['ozon']['bind_response']=response
  if response.get('result') is not True:state.update(phase='ozon_bind_rejected',updated_at=now());atomic(EXEC,state);raise RuntimeError('Ozon rejected bindings')
  state.update(phase='ozon_bind_accepted',updated_at=now());atomic(EXEC,state)
 final_info=c.call('ozon','/v1/product/certificate/info',{'certificate_number':lookup}).get('result') or {}; binds=read_bindings(c,cid); byid={str(x.get('product_id')):x for x in binds}
 ozrows=[{'offer_id':t['offer_id'],'product_id':t['product_id'],'sku':t['sku'],'visible':bool(byid.get(t['product_id'])),'identity_matches':bool(byid.get(t['product_id']) and str(byid[t['product_id']].get('sku'))==t['sku']),'status':byid[t['product_id']].get('product_status_code') if t['product_id'] in byid else None} for t in plan['targets']]
 if any(not x['visible'] or not x['identity_matches'] for x in ozrows):state.update(phase='ozon_readback_incomplete',ozon_bindings=ozrows,updated_at=now());atomic(EXEC,state);raise RuntimeError('Ozon readback incomplete')
 state.update(phase='ozon_readback_complete',updated_at=now(),ozon={**state['ozon'],'certificate_id':cid,'certificate_status':final_info.get('status_code'),'binding_count':len(binds),'target_binding_readback':ozrows});atomic(EXEC,state)
 wanted={'type':2,'number':NUMBER,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
 for row in plan['wb_cards_to_update']:
  cards=c.wb_cards(row['offer_id'])
  if len(cards)!=1 or str(cards[0].get('nmID'))!=row['nmID'] or str(cards[0].get('brand') or '').casefold()!='feron':raise RuntimeError(f'WB card changed: {row["offer_id"]}')
  row['payload']=merge(cards[0],wanted);row['before']=cards[0]
 payloads=[x['payload'] for x in plan['wb_cards_to_update'] if x['payload'] is not None]
 if payloads:
  state.update(phase='wb_update_prepared',updated_at=now(),wb={'cards':[{'offer_id':x['offer_id'],'nmID':x['nmID']} for x in plan['wb_cards_to_update']]});atomic(EXEC,state)
  try:resp=c.call('wb','/content/v2/cards/update',payloads,mutation=True)
  except Exception as exc:state.update(phase='wb_update_uncertain',error_type=type(exc).__name__,updated_at=now());atomic(EXEC,state);raise RuntimeError('WB update uncertain; reconcile before retry') from None
  state['wb']['update_response']=resp
  if resp.get('error') is not False:state.update(phase='wb_update_rejected',updated_at=now());atomic(EXEC,state);raise RuntimeError('WB update rejected')
  state.update(phase='wb_update_accepted',updated_at=now());atomic(EXEC,state)
 wbrows=[]
 for row in [*plan['wb_cards_to_update'],*plan['wb_already_present']]:
  cards=c.wb_cards(row['offer_id']); exact=[d for d in (raw_docs(cards[0]) if len(cards)==1 else []) if doc_key(d)==doc_key(wanted)]
  dates=any(str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY for d in exact)
  preserved=bool(len(cards)==1 and ('before' not in row or comparable_card(cards[0])==comparable_card(row['before'])))
  valid=any((d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('reason')=='valid' for d in exact)
  wbrows.append({'offer_id':row['offer_id'],'nmID':row['nmID'],'document_visible':bool(exact),'dates_match':dates,'unrelated_fields_preserved':preserved,'valid_wb_verdict':valid,'status':'valid' if valid and dates and preserved else 'visible_pending_review' if exact and dates and preserved else 'readback_incomplete'})
 if any(x['status'] not in {'valid','visible_pending_review'} for x in wbrows):state.update(phase='wb_readback_incomplete',wb_readback=wbrows,updated_at=now());atomic(EXEC,state);raise RuntimeError('WB readback incomplete')
 result={'checked_at':now(),'number':NUMBER,'ozon_certificate_id':cid,'ozon_certificate_status':final_info.get('status_code'),'ozon_targets_expected':len(plan['targets']),'ozon_targets_visible':len(ozrows),'ozon_binding_status_counts':dict(collections.Counter(x['status'] for x in ozrows)),'ozon_bindings':ozrows,'wb_cards_updated':len(payloads),'wb_existing_exact_docs':len(plan['wb_already_present']),'wb_valid_verdicts':sum(x['valid_wb_verdict'] for x in wbrows),'wb_pending_review':sum(x['status']=='visible_pending_review' for x in wbrows),'wb_readback':wbrows,'wb_missing_exact_cards':plan['wb_missing_exact_cards'],'source_files_deleted':False,'source_files_retained_reason':'WB card for 32874-1 is absent; retain the source scan.'}
 atomic(READBACK,result);state.update(phase='complete',finished_at=now(),readback_path=str(READBACK));atomic(EXEC,state);return result
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();c=Client();plan=build_plan(c);atomic(PLAN,plan)
 print(json.dumps({'mode':'execute' if a.execute else 'dry_run','number':NUMBER,'targets':len(plan['targets']),'ozon_matching_records':len(plan['ozon_existing_matching_records']),'wb_to_update':len(plan['wb_cards_to_update']),'wb_already_present':len(plan['wb_already_present']),'wb_missing_cards':plan['wb_missing_exact_cards'],'pdf_sha256':plan['source_pdf_sha256']},ensure_ascii=False,indent=2))
 if a.execute:print(json.dumps(execute(c,plan),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
