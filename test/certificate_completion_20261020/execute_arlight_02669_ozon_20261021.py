from __future__ import annotations
import base64, collections, datetime as dt, hashlib, json, pathlib, re, sys, time
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012'; sys.path.insert(0,str(API))
from api_client import Client, now, digest
from reconcile_approved_ozon_docs_to_wb import norm_number
PREFLIGHT=HERE/'arlight_02669_crossplatform_preflight_live_20261021.json'
STATE=HERE/'arlight_02669_ozon_execution_20261021.json'
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/B40746683BE4E24A9A25CD278FD53917.pdf'
NUMBER='ЕАЭС RU С-HK.АБ53.В.02669/21'; ISSUE='2021-12-08'; EXPIRY='2026-12-07'
EXPECTED=578; EXPECTED_SHA='9b9c776c47d6e805fc9a18b4717a64407b348289c7b0dcf4f8c42de5e90b275f'
SERIES=('ART','SNAP','CLIP','MAG','FLEX','LGD')

def save(x):
 tmp=STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2)); tmp.replace(STATE)
def attr_values(row,attr_id):
 attrs={str(a.get('id')):a for a in row.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (attrs.get(str(attr_id)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def hits(value):
 text=str(value or '').upper()
 return [s for s in SERIES if re.search(r'(?<![A-Z0-9])'+s+r'(?![A-Z0-9])',text)]
def list_records(client):
 out=[]; page=1; seen=set()
 while True:
  data=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
  batch=data.get('certificates')
  if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_missing')
  for x in batch:
   cid=str(x.get('certificate_id') or '')
   if not cid or cid in seen: raise RuntimeError('duplicate_or_missing_ozon_certificate_id')
   seen.add(cid)
  out.extend(batch)
  if not batch or page>=int(data.get('page_count') or 0): return out
  page+=1
def exact_info(client):
 payload={'certificate_number':NUMBER}; raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
 entry={'started_at':now(),'platform':'ozon','path':'/v1/product/certificate/info','mutation':False,'request_sha256':hashlib.sha256(raw).hexdigest(),'request_bytes':len(raw)}
 log=API/'api_calls.jsonl'
 with log.open('a') as f: f.write(json.dumps({**entry,'phase':'prepared'},ensure_ascii=False)+'\n'); f.flush()
 response=client.http.post('https://api-seller.ozon.ru/v1/product/certificate/info',data=raw,headers=client.ozon_headers,timeout=(15,60))
 try: body=response.json()
 except ValueError: body={'non_json_response':True}
 with log.open('a') as f: f.write(json.dumps({**entry,'phase':'response','http_status':response.status_code,'body':body,'finished_at':now()},ensure_ascii=False)+'\n'); f.flush()
 absent=(response.status_code==404 and isinstance(body,dict) and body.get('code')==5 and 'not found' in str(body.get('message') or '').casefold() and NUMBER in str(body.get('message') or ''))
 return absent,response.status_code,body

def main():
 if STATE.exists(): raise RuntimeError('ozon_execution_state_exists_reconcile_before_retry')
 pre=json.loads(PREFLIGHT.read_text())
 if not pre.get('eligible_for_upload') or pre.get('eligible_ozon_targets')!=EXPECTED or pre.get('eligible_wb_cards_for_add')!=EXPECTED or pre.get('ozon_exact_record_absence_confirmed') is not True:
  raise RuntimeError('crossplatform_preflight_not_eligible')
 if digest(SOURCE)!=EXPECTED_SHA or digest(SOURCE)!=pre.get('source_pdf_sha256'): raise RuntimeError('source_pdf_hash_changed')
 targets=pre['ozon_targets']; offers={x['offer_id'] for x in targets}; pids={x['product_id'] for x in targets}; skus={x['sku'] for x in targets}
 if len(targets)!=EXPECTED or len(offers)!=EXPECTED or len(pids)!=EXPECTED or len(skus)!=EXPECTED: raise RuntimeError('ozon_target_ids_not_unique')
 if any(not x.get('model_scope_confirmed_by_fsa_series') or x.get('archived') is not False or x.get('brand_values')!=['Arlight'] or not set(x.get('series_hits') or [])<=set(SERIES) for x in targets): raise RuntimeError('ozon_model_scope_not_confirmed')
 client=Client()
 # Refresh exact product identities/brands/current classifier values immediately before creation.
 details={}
 pid_list=sorted(pids)
 for start in range(0,len(pid_list),100):
  batch=pid_list[start:start+100]
  result=client.call('ozon','/v3/product/info/list',{'product_id':[int(x) for x in batch]}).get('items')
  if not isinstance(result,list): raise RuntimeError('ozon_product_refresh_missing')
  for row in result:
   pid=str(row.get('product_id') or row.get('id') or '')
   if pid not in batch or pid in details: raise RuntimeError('ozon_product_refresh_identity_mismatch')
   details[pid]=row
 if set(details)!=pids: raise RuntimeError('ozon_product_refresh_incomplete')
 attrs={}
 for start in range(0,len(offers),100):
  batch=sorted(offers)[start:start+100]
  result=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result')
  if not isinstance(result,list): raise RuntimeError('ozon_attributes_refresh_missing')
  for row in result:
   offer=str(row.get('offer_id') or '')
   if offer not in batch or offer in attrs: raise RuntimeError('ozon_attribute_refresh_identity_mismatch')
   attrs[offer]=row
 if set(attrs)!=offers: raise RuntimeError('ozon_attribute_refresh_incomplete')
 for target in targets:
  detail=details[target['product_id']]; attr=attrs[target['offer_id']]
  brand=attr_values(attr,85); codes=sorted({v.split(' - ',1)[0].strip() for v in attr_values(attr,22232) if v.strip()})
  name=str(detail.get('name') or detail.get('name_ru') or '')
  identity=(str(detail.get('offer_id') or '')==target['offer_id'] and str(detail.get('product_id') or detail.get('id') or '')==target['product_id'] and str(detail.get('sku') or '')==target['sku'] and str(attr.get('offer_id') or '')==target['offer_id'] and detail.get('is_archived') is False)
  if not identity or brand!=['Arlight'] or not hits(name) or codes!=target['tnved_codes']:
   raise RuntimeError('ozon_target_changed_before_create:'+target['offer_id'])
 records=list_records(client)
 existing=[x for x in records if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 if existing: raise RuntimeError('normalized_ozon_record_exists_before_create:'+','.join(str(x.get('certificate_id')) for x in existing))
 absent,http_status,absence_body=exact_info(client)
 if not absent: raise RuntimeError('ozon_exact_record_absence_not_confirmed:'+str(http_status))
 state={'started_at':now(),'phase':'preflight_verified','number':NUMBER,'source_pdf_sha256':digest(SOURCE),'official_fsa_record_id':3008100,'target_count':EXPECTED,'tnved_mismatch_recorded':True,'exact_lookup_http_status':http_status,'exact_lookup_body':absence_body,'create_sent':False,'bind_batches':[],'local_file_deleted':False}
 save(state)
 expiry=dt.date.fromisoformat(EXPIRY)
 seed=targets[0]
 params={'name':'Сертификат соответствия № '+NUMBER,'certificate_type':'CERTIFICATE_OF_CONFORMITY','certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,'issue_date':ISSUE+'T00:00:00Z','expired_date':{'date':{'day':expiry.day,'month':expiry.month,'year':expiry.year}},'skus':[seed['sku']],'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(SOURCE.read_bytes()).decode('ascii'),'name':SOURCE.name}]}
 payload={'params':params}
 if len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())>9_500_000: raise RuntimeError('ozon_create_payload_too_large')
 state.update(phase='ozon_create_prepared',create_sent=True,seed_offer_id=seed['offer_id'],seed_sku=seed['sku']); save(state)
 try: created=client.call('ozon','/v2/product/certificate/create',payload,mutation=True)
 except Exception as exc:
  state.update(phase='ozon_create_uncertain',error_type=type(exc).__name__,updated_at=now()); save(state)
  raise RuntimeError('ozon_create_uncertain_reconcile_live_before_retry') from None
 states=[x.get('state') for x in created.get('params',[]) if isinstance(x,dict)]
 cert_id=int(created.get('certificate_id') or 0)
 state.update(create_response=created,certificate_id=cert_id,updated_at=now())
 if not cert_id or created.get('status')!='COMPLETED' or not states or set(states)!={'VALID'}:
  state.update(phase='ozon_create_not_validated'); save(state); raise RuntimeError('ozon_create_response_not_fully_validated')
 info={}
 for attempt in range(8):
  try:
   info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}; break
  except RuntimeError as exc:
   if 'HTTP 404' not in str(exc) or attempt==7:
    state.update(phase='ozon_info_readback_failed',error_type=type(exc).__name__,updated_at=now()); save(state); raise
   time.sleep(2)
 if (str(info.get('certificate_id'))!=str(cert_id) or norm_number(info.get('certificate_number'))!=norm_number(NUMBER) or info.get('type_code')!='certificate_of_conformity' or str(info.get('issue_date',''))[:10]!=ISSUE or str(info.get('expire_date',''))[:10]!=EXPIRY or str(info.get('accordance_type_code','')).upper()!='EAEU' or info.get('status_code') in {'declined','rejected','invalid','cancelled'}):
  state.update(phase='ozon_metadata_conflict',certificate_info=info,updated_at=now()); save(state); raise RuntimeError('ozon_live_document_metadata_conflict')
 bindings=client.ozon_bindings(cert_id); by_id={str(x.get('product_id')):x for x in bindings}; target_by_id={x['product_id']:x for x in targets}
 if len(by_id)!=len(bindings) or set(by_id)-set(target_by_id): raise RuntimeError('seed_binding_has_unknown_or_duplicate_product')
 missing=[]
 for target in targets:
  current=by_id.get(target['product_id'])
  if current and str(current.get('sku'))!=target['sku']: raise RuntimeError('ozon_binding_identity_conflict:'+target['offer_id'])
  if not current: missing.append(target['sku'])
 state.update(phase='ozon_binding',certificate_info=info,binding_count_before=len(bindings),missing_binding_count=len(missing)); save(state)
 for start in range(0,len(missing),100):
  batch=missing[start:start+100]
  response=client.call('ozon','/v1/product/certificate/bind',{'certificate_id':cert_id,'skus':batch},mutation=True)
  state['bind_batches'].append({'count':len(batch),'result':response.get('result')}); state['updated_at']=now(); save(state)
  if response.get('result') is not True: state.update(phase='ozon_bind_rejected'); save(state); raise RuntimeError('ozon_bind_not_accepted')
 final=client.ozon_bindings(cert_id); by_id={str(x.get('product_id')):x for x in final}
 rows=[]; statuses=collections.Counter()
 for target in targets:
  b=by_id.get(target['product_id']); okay=bool(b and str(b.get('sku'))==target['sku']); status=str(b.get('product_status_code')) if okay else None
  rows.append({'offer_id':target['offer_id'],'product_id':target['product_id'],'sku':target['sku'],'bound':okay,'status':status})
  if okay: statuses[status or 'unknown']+=1
 outside=sorted(set(by_id)-set(target_by_id)); missing_pairs=[x['offer_id'] for x in rows if not x['bound']]
 if missing_pairs or outside or len(by_id)!=EXPECTED:
  state.update(phase='ozon_binding_readback_incomplete',missing_offers=missing_pairs,outside_product_ids=outside,binding_row_count=len(final),updated_at=now()); save(state); raise RuntimeError('ozon_binding_readback_incomplete')
 state.update(phase='ozon_verified_complete',binding_count=len(final),verified_target_pairs=len(rows),binding_status_counts=dict(statuses),certificate_status=info.get('status_code'),updated_at=now(),local_file_deleted=False,tnved_mismatch_recorded=True)
 state['bindings']=rows; save(state)
 print(json.dumps({'phase':state['phase'],'certificate_id':cert_id,'certificate_status':info.get('status_code'),'verified_target_pairs':len(rows),'binding_status_counts':dict(statuses),'local_file_deleted':False},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
