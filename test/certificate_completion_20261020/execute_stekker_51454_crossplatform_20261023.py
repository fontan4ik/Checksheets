#!/usr/bin/env python3
"""Upload verified voluntary Stekker certificate 51454/24 to Ozon and reconcile WB."""
from __future__ import annotations
import base64,collections,datetime as dt,hashlib,json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number,wb_datetime
from run_all_found_certificates_20261014 import merge_wb
PREFLIGHT=HERE/'stekker_51454_crossplatform_preflight_20261023.json'
STATE=HERE/'stekker_51454_execution_20261023.json'
JOURNAL=HERE/'stekker_51454_mutation_journal_20261023.jsonl'
NUMBER='РОСС RU.32001.04ИБФ1.ОСП28.51454';ISSUE='2024-04-17';EXPIRY='2027-04-16'
SOURCE=ROOT/'output_to_user/certificates/additional_search/docs/stekker/feron_store/51454_Наконечники_гильзы_кабельные_Добровольный_сертификат.jpg'
SHA='c26ad19ac039b9e92b3b965b386d57aee17d197253e228019a3166b854ad61d3'

def save(x):
 t=STATE.with_suffix('.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');t.replace(STATE)
def journal(x):
 with JOURNAL.open('a',encoding='utf-8') as f:f.write(json.dumps({'at_utc':now(),**x},ensure_ascii=False)+'\n');f.flush()
def list_certs(c):
 rows=[]
 for p in range(1,101):
  d=c.call('ozon','/v1/product/certificate/list',{'page':p,'page_size':100}).get('result') or {};b=d.get('certificates')
  if not isinstance(b,list):raise RuntimeError('invalid_ozon_certificate_list')
  rows+=b
  if not b or p>=int(d.get('page_count') or 0):return rows
 raise RuntimeError('ozon_certificate_page_limit')
def exact_record(rows):
 m=[x for x in rows if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 if len(m)>1:raise RuntimeError('duplicate_ozon_records_before_bind')
 if not m:return None
 r=m[0]
 if r.get('type_code')!='certificate_of_conformity' or str(r.get('issue_date') or '')[:10]!=ISSUE or str(r.get('expire_date') or '')[:10]!=EXPIRY or r.get('accordance_type_code') not in ('gost','GOST'):
  raise RuntimeError('existing_ozon_metadata_conflict')
 if str(r.get('status_code') or '').casefold() in {'declined','rejected','invalid','cancelled'}:raise RuntimeError('existing_ozon_record_rejected')
 return r
def attr_values(attrs,ident):
 by={str(x.get('id')):x for x in attrs or []}
 return [str(v.get('value') or '').strip() for v in (by.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def main():
 if STATE.exists() or JOURNAL.exists():raise RuntimeError('execution_artifact_exists_reconcile_before_retry')
 if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SHA:raise RuntimeError('source_hash_mismatch')
 pre=json.loads(PREFLIGHT.read_text());checked=dt.datetime.fromisoformat(pre['checked_at_utc'].replace('Z','+00:00'))
 if pre.get('read_only') is not True or (dt.datetime.now(dt.timezone.utc)-checked).total_seconds()>1800:raise RuntimeError('preflight_stale')
 if pre.get('number')!=NUMBER or pre.get('issue_date')!=ISSUE or pre.get('expiry_date')!=EXPIRY or pre.get('source_sha256')!=SHA or pre.get('assignment_count')!=55 or pre.get('ozon_target_count')!=55 or pre.get('wb_target_count')!=55 or pre.get('ozon_record_matches')!=[]:raise RuntimeError('preflight_identity_counts_or_duplicate_changed')
 targets=pre['targets'];offers=sorted(x['offer_id'] for x in targets)
 if len(targets)!=55 or len(set(offers))!=55 or any(x['ozon_blockers'] or x['wb_blockers'] or not x.get('wb_exact_preexisting') for x in targets):raise RuntimeError('target_preflight_not_complete')
 c=Client();fresh_products={};fresh_attrs={}
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]
  for x in c.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []:fresh_products.setdefault(str(x.get('offer_id') or ''),[]).append(x)
  for x in c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or []:fresh_attrs.setdefault(str(x.get('offer_id') or ''),[]).append(x)
 refreshed=[]
 for t in targets:
  pp=fresh_products.get(t['offer_id'],[]);aa=fresh_attrs.get(t['offer_id'],[])
  if len(pp)!=1 or len(aa)!=1:raise RuntimeError('fresh_ozon_identity_missing_or_ambiguous:'+t['offer_id'])
  p,a=pp[0],aa[0];brands=[x.casefold() for x in attr_values(a.get('attributes'),85)]
  pid=str(p.get('product_id') or p.get('id') or '');sku=str(p.get('sku') or '')
  if p.get('is_archived') is not False or pid!=t['product_id'] or sku!=t['sku'] or brands!=['stekker'] or p.get('name')!=t['ozon_name']:
   raise RuntimeError('fresh_ozon_identity_changed:'+t['offer_id'])
  refreshed.append({'offer_id':t['offer_id'],'product_id':pid,'sku':sku,'brand':brands,'name':p.get('name')})
 record=exact_record(list_certs(c));created=False;create_response=None
 state={'started_at_utc':now(),'phase':'fresh_preflight_passed','number':NUMBER,'source_sha256':SHA,'issue_date':ISSUE,'expiry_date':EXPIRY,'ozon_expected':55,'wb_expected_existing_exact':55,'ozon_create_attempted':False,'ozon_bind_attempted':False,'wb_update_attempted':False,'wb_review_left_to_marketplace':True,'local_source_deleted':False,'fresh_ozon_targets':refreshed}
 save(state)
 if record is None:
  expiry=dt.date.fromisoformat(EXPIRY);seed=targets[0]
  params={'name':'Добровольный сертификат соответствия № '+NUMBER,'certificate_type':'CERTIFICATE_OF_CONFORMITY','certificate_country':'RU','accordance_type':'gost','number':NUMBER,'issue_date':wb_datetime(ISSUE),'expired_date':{'date':{'day':expiry.day,'month':expiry.month,'year':expiry.year}},'skus':[seed['sku']],'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(SOURCE.read_bytes()).decode('ascii'),'name':SOURCE.name}]}
  payload={'params':params};payload_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
  state.update({'phase':'ozon_create_prepared','ozon_create_attempted':True,'ozon_create_payload_sha256':payload_hash,'ozon_seed_offer':seed['offer_id'],'ozon_seed_sku':seed['sku'],'ozon_file_format':'jpg','ozon_file_bytes':SOURCE.stat().st_size});save(state)
  journal({'platform':'ozon','phase':'create_prepared','endpoint':'/v2/product/certificate/create','payload_sha256':payload_hash,'source_sha256':SHA,'seed_offer':seed['offer_id'],'seed_sku':seed['sku']})
  try:
   create_response=c.call('ozon','/v2/product/certificate/create',payload,mutation=True)
   journal({'platform':'ozon','phase':'create_response','response':create_response})
  except Exception as e:
   journal({'platform':'ozon','phase':'create_outcome_uncertain','error_type':type(e).__name__})
   state.update({'phase':'ozon_create_outcome_uncertain','create_error_type':type(e).__name__});save(state)
   raise RuntimeError('create_outcome_uncertain; reconcile by list before any retry') from None
  created=True
  for i in range(7):
   record=exact_record(list_certs(c))
   if record or i==6:break
   time.sleep(2)
  if not record:state.update({'phase':'ozon_create_not_visible','create_response':create_response});save(state);raise RuntimeError('created_record_not_visible; no retry')
  states=[x.get('state') for x in (create_response or {}).get('params',[]) if isinstance(x,dict)]
  valid=create_response.get('status')=='COMPLETED' and bool(states) and set(states)=={'VALID'}
  state.update({'phase':'ozon_record_created','ozon_record_id':str(record['certificate_id']),'ozon_record_status':record.get('status_code'),'ozon_create_response':create_response,'create_response_fully_validated':valid});save(state)
  if not valid:raise RuntimeError('ozon_create_response_unvalidated; skip additional bindings')
 state.update({'ozon_record_id':str(record['certificate_id']),'ozon_record_status':record.get('status_code'),'ozon_record_created':created});save(state)
 bindings=c.ozon_bindings(int(record['certificate_id']));by_pid={str(x.get('product_id') or ''):x for x in bindings}
 expected_by_pid={str(x['product_id']):x for x in targets}
 outside=[x for x in bindings if str(x.get('product_id') or '') not in expected_by_pid]
 conflicts=[x for x in bindings if str(x.get('product_id') or '') in expected_by_pid and str(x.get('sku') or '')!=expected_by_pid[str(x.get('product_id'))]['sku']]
 if outside or conflicts:raise RuntimeError('ozon_existing_binding_scope_or_identity_conflict')
 for x in targets:
  current=by_pid.get(str(x['product_id']))
  if current and current.get('product_status_code') in {'declined','rejected','invalid'}:raise RuntimeError('ozon_existing_target_binding_declined:'+x['offer_id'])
 missing=[x for x in targets if str(x['product_id']) not in by_pid]
 if missing:
  req={'certificate_id':int(record['certificate_id']),'skus':sorted(x['sku'] for x in missing)};h=hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest()
  state.update({'phase':'ozon_bind_prepared','ozon_bind_attempted':True,'ozon_bind_payload_sha256':h,'ozon_bind_count':len(missing)});save(state)
  journal({'platform':'ozon','phase':'bind_prepared','endpoint':'/v1/product/certificate/bind','certificate_id':record['certificate_id'],'sku_count':len(missing),'payload_sha256':h})
  try:response=c.call('ozon','/v1/product/certificate/bind',req,mutation=True);journal({'platform':'ozon','phase':'bind_response','response':response})
  except Exception as e:
   journal({'platform':'ozon','phase':'bind_outcome_uncertain','error_type':type(e).__name__});state.update({'phase':'ozon_bind_outcome_uncertain','bind_error_type':type(e).__name__});save(state);raise RuntimeError('bind_outcome_uncertain; reconcile before retry') from None
  state['ozon_bind_response']=response;save(state)
 final=c.ozon_bindings(int(record['certificate_id']));by_pid={str(x.get('product_id') or ''):x for x in final};ozon_rows=[]
 for x in targets:
  row=by_pid.get(str(x['product_id']));ozon_rows.append({'offer_id':x['offer_id'],'product_id':str(x['product_id']),'sku':str(x['sku']),'exact':bool(row and str(row.get('sku') or '')==str(x['sku'])),'status':row.get('product_status_code') if row else None})
 if not all(x['exact'] for x in ozon_rows):raise RuntimeError('ozon_readback_missing_binding')
 wb_rows=[];wb_missing=[];wb_verdicts=collections.Counter();wb_docs_to_update=[]
 for t in targets:
  cards=c.wb_cards(t['offer_id'])
  if len(cards)!=1 or str(cards[0].get('nmID') or '')!=t['wb_nmID']:raise RuntimeError('fresh_wb_card_changed:'+t['offer_id'])
  card=cards[0];docs=((card.get('documents') or {}).get('items') or []);same=[x for x in docs if norm_number(x.get('number'))==norm_number(NUMBER)]
  exact=[x for x in same if str(x.get('type') or '')=='1' and str(x.get('startDate') or '')[:10]==ISSUE and str(x.get('endDate') or '')[:10]==EXPIRY and x.get('isEndless') is False]
  if len(exact)!=1:wb_missing.append(t['offer_id']);continue
  v=exact[0].get('verdict') or {};status='valid' if v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' else 'pending_or_unverified';wb_verdicts[status]+=1
  wb_rows.append({'offer_id':t['offer_id'],'nmID':t['wb_nmID'],'brand':card.get('brand'),'status':status,'verdict':v})
 result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'ozon_record_id':str(record['certificate_id']),'ozon_record_status':record.get('status_code'),'ozon_target_count':55,'ozon_exact_count':len(ozon_rows),'ozon_binding_status_counts':dict(collections.Counter(str(x['status'] or 'unknown') for x in ozon_rows)),'ozon_bindings':ozon_rows,'wb_target_count':55,'wb_exact_count':len(wb_rows),'wb_missing_count':len(wb_missing),'wb_missing_offers':wb_missing,'wb_verdict_counts':dict(wb_verdicts),'wb_cards':wb_rows,'wb_review_left_to_marketplace':True,'no_local_files_deleted':True}
 readback=HERE/'stekker_51454_execution_crossplatform_readback_20261023.json';readback.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 state.update({'phase':'crossplatform_readback_complete','ozon_exact_count':len(ozon_rows),'ozon_binding_status_counts':result['ozon_binding_status_counts'],'wb_exact_count':len(wb_rows),'wb_missing_count':len(wb_missing),'wb_verdict_counts':dict(wb_verdicts),'wb_review_left_to_marketplace':True,'readback_path':str(readback),'finished_at_utc':now()});save(state)
 print(json.dumps({k:v for k,v in result.items() if k not in ('ozon_bindings','wb_cards')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
