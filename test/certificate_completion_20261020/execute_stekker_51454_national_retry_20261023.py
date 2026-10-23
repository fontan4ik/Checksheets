#!/usr/bin/env python3
"""Correct the non-creating GOST parameter attempt and apply Stekker 51454/24."""
from __future__ import annotations
import base64,collections,datetime as dt,hashlib,json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number,wb_datetime
PREFLIGHT=HERE/'stekker_51454_crossplatform_preflight_20261023.json'
FAILED=HERE/'stekker_51454_execution_20261023.json'
STATE=HERE/'stekker_51454_national_retry_execution_20261023.json'
JOURNAL=HERE/'stekker_51454_national_retry_journal_20261023.jsonl'
NUMBER='РОСС RU.32001.04ИБФ1.ОСП28.51454';ISSUE='2024-04-17';EXPIRY='2027-04-16'
SOURCE=ROOT/'output_to_user/certificates/additional_search/docs/stekker/feron_store/51454_Наконечники_гильзы_кабельные_Добровольный_сертификат.jpg'
SHA='c26ad19ac039b9e92b3b965b386d57aee17d197253e228019a3166b854ad61d3'
def save(path,x):
 t=path.with_suffix(path.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');t.replace(path)
def j(x):
 with JOURNAL.open('a',encoding='utf-8') as f:f.write(json.dumps({'at_utc':now(),**x},ensure_ascii=False)+'\n');f.flush()
def list_certs(c):
 out=[]
 for page in range(1,101):
  d=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {};b=d.get('certificates')
  if not isinstance(b,list):raise RuntimeError('invalid_certificate_list')
  out+=b
  if not b or page>=int(d.get('page_count') or 0):return out
 raise RuntimeError('certificate_list_page_limit')
def matching(rows):return [x for x in rows if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
def attr_values(attrs,ident):
 by={str(x.get('id')):x for x in attrs or []}
 return [str(v.get('value') or '').strip() for v in (by.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def main():
 if STATE.exists() or JOURNAL.exists():raise RuntimeError('retry_artifact_exists')
 if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SHA:raise RuntimeError('source_hash_mismatch')
 old=json.loads(FAILED.read_text());oldresp=old.get('create_response') or {};params={x.get('name'):x for x in oldresp.get('params') or []}
 if (old.get('phase')!='ozon_create_not_visible' or oldresp.get('status')!='INCOMPLETE' or oldresp.get('certificate_id') is not None or params.get('ACCORDANCE_TYPE',{}).get('state')!='INVALID' or params.get('ACCORDANCE_TYPE',{}).get('error')!='Это обязательное поле'):
  raise RuntimeError('prior_attempt_not_proven_noncreating')
 pre=json.loads(PREFLIGHT.read_text());checked=dt.datetime.fromisoformat(pre['checked_at_utc'].replace('Z','+00:00'))
 if pre.get('read_only') is not True or (dt.datetime.now(dt.timezone.utc)-checked).total_seconds()>1800 or pre.get('source_sha256')!=SHA or pre.get('assignment_count')!=55 or pre.get('ozon_target_count')!=55 or pre.get('wb_target_count')!=55:raise RuntimeError('preflight_stale_or_counts_changed')
 targets=pre['targets']
 if len(targets)!=55 or any(x['ozon_blockers'] or x['wb_blockers'] or not x.get('wb_exact_preexisting') for x in targets):raise RuntimeError('target_scope_not_complete')
 c=Client();offers=sorted(x['offer_id'] for x in targets);fresh_p={};fresh_a={}
 for i in range(0,len(offers),100):
  batch=offers[i:i+100]
  for x in c.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []:fresh_p.setdefault(str(x.get('offer_id') or ''),[]).append(x)
  for x in c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or []:fresh_a.setdefault(str(x.get('offer_id') or ''),[]).append(x)
 for t in targets:
  p=fresh_p.get(t['offer_id'],[]);a=fresh_a.get(t['offer_id'],[])
  if len(p)!=1 or len(a)!=1:raise RuntimeError('fresh_product_missing_or_ambiguous:'+t['offer_id'])
  p=p[0];brands=[x.casefold() for x in attr_values(a[0].get('attributes'),85)]
  if p.get('is_archived') is not False or str(p.get('product_id') or p.get('id') or '')!=t['product_id'] or str(p.get('sku') or '')!=t['sku'] or p.get('name')!=t['ozon_name'] or brands!=['stekker']:raise RuntimeError('fresh_product_identity_changed:'+t['offer_id'])
 live=matching(list_certs(c))
 if live:raise RuntimeError('certificate_record_now_exists; reconcile before creating')
 state={'started_at_utc':now(),'phase':'corrected_preflight_passed','number':NUMBER,'prior_noncreating_attempt':str(FAILED),'prior_attempt_status':'INCOMPLETE','prior_attempt_certificate_id':None,'prior_attempt_parameter_error':params['ACCORDANCE_TYPE'].get('error'),'source_sha256':SHA,'ozon_target_count':55,'wb_exact_existing_count':55,'accordance_type':'NATIONAL','ozon_create_attempted':False,'ozon_bind_attempted':False,'wb_update_attempted':False,'wb_review_left_to_marketplace':True,'local_source_deleted':False}
 save(STATE,state)
 end=dt.date.fromisoformat(EXPIRY);seed=targets[0]
 payload={'params':{'name':'Добровольный сертификат соответствия № '+NUMBER,'certificate_type':'CERTIFICATE_OF_CONFORMITY','certificate_country':'RU','accordance_type':'NATIONAL','number':NUMBER,'issue_date':wb_datetime(ISSUE),'expired_date':{'date':{'day':end.day,'month':end.month,'year':end.year}},'skus':[seed['sku']],'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(SOURCE.read_bytes()).decode('ascii'),'name':SOURCE.name}]}}
 payload_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
 state.update({'phase':'ozon_create_prepared','ozon_create_attempted':True,'ozon_create_payload_sha256':payload_hash,'ozon_seed_offer':seed['offer_id'],'ozon_seed_sku':seed['sku']});save(STATE,state)
 j({'platform':'ozon','phase':'create_prepared','endpoint':'/v2/product/certificate/create','payload_sha256':payload_hash,'source_sha256':SHA,'accordance_type':'NATIONAL','seed_offer':seed['offer_id']})
 try:created=c.call('ozon','/v2/product/certificate/create',payload,mutation=True)
 except Exception as e:
  state.update({'phase':'ozon_create_uncertain','error_type':type(e).__name__});save(STATE,state);j({'platform':'ozon','phase':'create_uncertain','error_type':type(e).__name__});raise RuntimeError('create_uncertain; reconcile before retry') from None
 j({'platform':'ozon','phase':'create_response','response':created})
 states=[x.get('state') for x in created.get('params',[]) if isinstance(x,dict)]
 if not created.get('certificate_id') or created.get('status')!='COMPLETED' or not states or set(states)!={'VALID'}:
  state.update({'phase':'ozon_create_response_invalid','create_response':created});save(STATE,state);raise RuntimeError('create_not_fully_validated; no bind')
 cid=int(created['certificate_id']);record=None
 for i in range(7):
  hits=matching(list_certs(c))
  if hits or i==6:break
  time.sleep(2)
 if len(hits)!=1 or int(hits[0].get('certificate_id') or -1)!=cid:
  state.update({'phase':'ozon_record_not_uniquely_visible','certificate_id':cid,'matching_record_count':len(hits),'create_response':created});save(STATE,state);raise RuntimeError('record_not_uniquely_visible; no retry')
 record=hits[0]
 if record.get('type_code')!='certificate_of_conformity' or record.get('accordance_type_code') not in ('national','NATIONAL','gost','GOST') or str(record.get('issue_date') or '')[:10]!=ISSUE or str(record.get('expire_date') or '')[:10]!=EXPIRY:
  state.update({'phase':'ozon_record_metadata_conflict','record':record});save(STATE,state);raise RuntimeError('record_metadata_conflict')
 state.update({'phase':'ozon_record_verified','certificate_id':cid,'record_status':record.get('status_code'),'create_response':created});save(STATE,state)
 bindings=c.ozon_bindings(cid);by={str(x.get('product_id') or ''):x for x in bindings};expected={str(x['product_id']):x for x in targets}
 if any(str(x.get('product_id') or '') not in expected for x in bindings):raise RuntimeError('existing_binding_outside_target_set')
 missing=[x for x in targets if str(x['product_id']) not in by]
 if any(by.get(str(x['product_id']),{}).get('product_status_code') in {'declined','rejected','invalid'} for x in targets):raise RuntimeError('existing_target_binding_rejected')
 if missing:
  request={'certificate_id':cid,'skus':sorted(x['sku'] for x in missing)};h=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
  state.update({'phase':'ozon_bind_prepared','ozon_bind_attempted':True,'ozon_bind_payload_sha256':h,'ozon_bind_count':len(missing)});save(STATE,state);j({'platform':'ozon','phase':'bind_prepared','endpoint':'/v1/product/certificate/bind','certificate_id':cid,'sku_count':len(missing),'payload_sha256':h})
  try:resp=c.call('ozon','/v1/product/certificate/bind',request,mutation=True)
  except Exception as e:state.update({'phase':'ozon_bind_uncertain','bind_error_type':type(e).__name__});save(STATE,state);j({'platform':'ozon','phase':'bind_uncertain','error_type':type(e).__name__});raise RuntimeError('bind_uncertain; reconcile before retry') from None
  if resp.get('result') is not True:state.update({'phase':'ozon_bind_rejected','bind_response':resp});save(STATE,state);raise RuntimeError('bind_rejected')
  state['bind_response']=resp;save(STATE,state);j({'platform':'ozon','phase':'bind_response','response':resp})
 final=c.ozon_bindings(cid);by={str(x.get('product_id') or ''):x for x in final};oz=[]
 for t in targets:
  x=by.get(str(t['product_id']));oz.append({'offer_id':t['offer_id'],'product_id':t['product_id'],'sku':t['sku'],'exact':bool(x and str(x.get('sku'))==str(t['sku'])),'status':x.get('product_status_code') if x else None})
 if not all(x['exact'] for x in oz):raise RuntimeError('ozon_exact_readback_incomplete')
 wb=[];miss=[];verdicts=collections.Counter()
 for t in targets:
  cards=c.wb_cards(t['offer_id'])
  if len(cards)!=1 or str(cards[0].get('nmID') or '')!=t['wb_nmID'] or str(cards[0].get('brand') or '').strip().casefold()!='stekker':raise RuntimeError('fresh_wb_identity_changed:'+t['offer_id'])
  items=((cards[0].get('documents') or {}).get('items') or []);same=[x for x in items if norm_number(x.get('number'))==norm_number(NUMBER)]
  exact=[x for x in same if str(x.get('type') or '')=='1' and str(x.get('startDate') or '')[:10]==ISSUE and str(x.get('endDate') or '')[:10]==EXPIRY and x.get('isEndless') is False]
  if len(exact)!=1:miss.append(t['offer_id']);continue
  v=exact[0].get('verdict') or {};status='valid' if v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' else 'pending_or_unverified';verdicts[status]+=1;wb.append({'offer_id':t['offer_id'],'nmID':t['wb_nmID'],'status':status,'verdict':v})
 result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'ozon_record_id':str(cid),'ozon_record_status':record.get('status_code'),'ozon_target_count':55,'ozon_exact_count':len(oz),'ozon_binding_status_counts':dict(collections.Counter(str(x['status'] or 'unknown') for x in oz)),'ozon_bindings':oz,'wb_target_count':55,'wb_exact_count':len(wb),'wb_missing_count':len(miss),'wb_missing_offers':miss,'wb_verdict_counts':dict(verdicts),'wb_cards':wb,'wb_review_left_to_marketplace':True,'no_local_files_deleted':True}
 readback=HERE/'stekker_51454_national_retry_readback_20261023.json';save(readback,result)
 state.update({'phase':'crossplatform_readback_complete','ozon_record_id':str(cid),'ozon_record_status':record.get('status_code'),'ozon_exact_count':len(oz),'ozon_binding_status_counts':result['ozon_binding_status_counts'],'wb_exact_count':len(wb),'wb_missing_count':len(miss),'wb_verdict_counts':dict(verdicts),'readback_path':str(readback),'finished_at_utc':now()});save(STATE,state)
 print(json.dumps({k:v for k,v in result.items() if k not in ('ozon_bindings','wb_cards')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
