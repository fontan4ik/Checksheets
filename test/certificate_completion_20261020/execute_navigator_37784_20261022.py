#!/usr/bin/env python3
"""Upload exact-scope Navigator certificate 37784/24, bind Ozon SKUs, and add WB metadata."""
from __future__ import annotations
import base64, collections, datetime as dt, hashlib, json, pathlib, sys, time
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number, wb_datetime
from run_all_found_certificates_20261014 import merge_wb
from apply_arlight_52132_wb_20261020 import code_values
NUMBER='ЕАЭС RU С-CN.АЯ46.В.37784/24'; SOURCE=ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_94205_dc533601c1bf.pdf'
SHA='dc533601c1bf7a15e633d901b1cd189a2669dd1ef4a4cc6273e14feb1a22270d'; ISSUE='2024-12-03'; EXPIRY='2029-12-02'
PREFLIGHT=HERE/'navigator_37784_scope_preflight_20261022.json'; STATE=HERE/'navigator_37784_execution_20261022.json'; OJ=HERE/'navigator_37784_ozon_mutations_20261022.jsonl'; WJ=HERE/'navigator_37784_wb_mutations_20261022.jsonl'; WBEFORE=HERE/'navigator_37784_wb_before_20261022.json'; WBREAD=HERE/'navigator_37784_wb_readback_20261022.json'
def save(p,x):
 t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n'); t.replace(p)
def journal(p,x):
 with p.open('a') as f: f.write(json.dumps(x,ensure_ascii=False)+'\n'); f.flush()
def attr_values(row,ident):
 attrs={str(x.get('id')):x for x in row.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (attrs.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def codes(vals): return sorted({str(v).split(' - ',1)[0].strip() for v in vals if str(v).strip()})
def find_records(c):
 out=[]
 for page in range(1,101):
  res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; batch=res.get('certificates')
  if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_invalid')
  out.extend(x for x in batch if norm_number(x.get('certificate_number'))==norm_number(NUMBER))
  if not batch or page>=int(res.get('page_count') or 0): return out
 raise RuntimeError('ozon_certificate_page_limit')
def exact_wb(card): return [d for d in ((card.get('documents') or {}).get('items') or []) if norm_number(d.get('number'))==norm_number(NUMBER)]
def main():
 if any(p.exists() for p in (STATE,OJ,WJ,WBEFORE,WBREAD)): raise RuntimeError('execution_artifact_exists_inspect_before_retry')
 pre=json.loads(PREFLIGHT.read_text())
 if (pre.get('read_only') is not True or pre.get('target_count')!=32 or pre.get('ozon_eligible_targets')!=32 or pre.get('wb_eligible_targets')!=32 or pre.get('ozon_record_matches') or pre.get('ozon_tnved_distribution')!={'8539213009':32} or pre.get('wb_tnved_distribution')!={'8539520009':32}): raise RuntimeError('preflight_or_scope_changed')
 if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SHA: raise RuntimeError('source_pdf_hash_mismatch')
 oz={x['offer_id']:x for x in pre['ozon_targets'] if x.get('eligible') is True}; wb={x['offer_id']:x for x in pre['wb_targets'] if x.get('eligible') is True}
 if len(oz)!=32 or len(wb)!=32 or set(oz)!=set(wb): raise RuntimeError('target_sets_not_exact')
 c=Client(); state={'started_at_utc':now(),'number':NUMBER,'source_sha256':SHA,'issue_date':ISSUE,'expire_date':EXPIRY,'target_count':32,'ozon_tnved_mismatch':{'certificate':'8539219200','marketplace':'8539213009'},'wb_tnved_mismatch':{'certificate':'8539219200','marketplace':'8539520009'},'ozon_mutation_attempted':False,'wb_mutation_attempted':False,'wb_review_left_pending':True,'local_source_deleted':False,'phase':'fresh_prewrite_check'}
 save(STATE,state)
 offers=sorted(oz); products={}; attrs={}
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]
  pr=c.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []
  ar=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or []
  for r in pr: products.setdefault(str(r.get('offer_id')),[]).append(r)
  for r in ar: attrs.setdefault(str(r.get('offer_id')),[]).append(r)
 if set(products)!=set(offers) or set(attrs)!=set(offers): raise RuntimeError('fresh_ozon_prewrite_target_set_changed')
 for offer,e in oz.items():
  if len(products[offer])!=1 or len(attrs[offer])!=1: raise RuntimeError('fresh_ozon_ambiguous:'+offer)
  p,a=products[offer][0],attrs[offer][0]
  if (p.get('is_archived') is not False or str(p.get('product_id') or p.get('id'))!=e['product_id'] or str(p.get('sku'))!=e['sku'] or attr_values(a,85)!=['Navigator']): raise RuntimeError('fresh_ozon_identity_changed:'+offer)
  if codes(attr_values(a,22232))!=['8539213009']: raise RuntimeError('fresh_ozon_tnved_changed:'+offer)
 matches=find_records(c)
 if len(matches)>1: raise RuntimeError('duplicate_ozon_record_before_write')
 record=matches[0] if matches else None
 if record and (record.get('type_code')!='certificate_of_conformity' or str(record.get('issue_date',''))[:10]!=ISSUE or str(record.get('expire_date',''))[:10]!=EXPIRY): raise RuntimeError('ozon_existing_record_metadata_conflict')
 state.update({'phase':'ozon_record_prewrite_checked','record_reused':bool(record),'existing_record':({k:record.get(k) for k in ('certificate_id','certificate_number','status_code','issue_date','expire_date','products_count')} if record else None)})
 save(STATE,state)
 if record is None:
  exp=dt.date.fromisoformat(EXPIRY); seed=oz[offers[0]]
  payload={'params':{'name':'Сертификат соответствия № '+NUMBER,'certificate_type':'CERTIFICATE_OF_CONFORMITY','certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,'issue_date':wb_datetime(ISSUE),'expired_date':{'date':{'day':exp.day,'month':exp.month,'year':exp.year}},'skus':[seed['sku']],'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(SOURCE.read_bytes()).decode('ascii'),'name':SOURCE.name}]}}
  marker=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  journal(OJ,{'phase':'create_prepared','at':now(),'request_sha256':marker,'source_sha256':SHA,'first_sku':seed['sku']})
  state.update({'phase':'ozon_create_outcome_pending','ozon_mutation_attempted':True,'ozon_create_payload_sha256':marker}); save(STATE,state)
  try:
   response=c.call('ozon','/v2/product/certificate/create',payload,mutation=True); state['ozon_create_response']=response; journal(OJ,{'phase':'create_response','at':now(),'response':response})
  except Exception as exc:
   state.update({'phase':'ozon_create_outcome_uncertain','ozon_create_error_type':type(exc).__name__,'no_create_retry':True}); journal(OJ,{'phase':'create_outcome_uncertain','at':now(),'error_type':type(exc).__name__}); save(STATE,state); raise
  save(STATE,state)
  for attempt in range(6):
   matches=find_records(c)
   if matches:
    if len(matches)!=1: raise RuntimeError('duplicate_ozon_records_after_create')
    record=matches[0]; break
   if attempt<5: time.sleep(2)
  if not record: state.update({'phase':'ozon_record_not_visible_no_retry','no_create_retry':True}); save(STATE,state); raise RuntimeError('created_record_not_visible_do_not_retry')
 if record.get('type_code')!='certificate_of_conformity' or str(record.get('issue_date',''))[:10]!=ISSUE or str(record.get('expire_date',''))[:10]!=EXPIRY: raise RuntimeError('created_ozon_record_metadata_conflict')
 cid=int(record['certificate_id']); state['ozon_record']={k:record.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date','products_count')}; save(STATE,state)
 binds=c.ozon_bindings(cid); expected={(e['product_id'],e['sku']) for e in oz.values()}; before={(str(b.get('product_id') or ''),str(b.get('sku') or '')) for b in binds}
 outside=[b for b in binds if (str(b.get('product_id') or ''),str(b.get('sku') or '')) not in expected]
 if outside: state.update({'phase':'ozon_outside_bindings_stop','outside_binding_count':len(outside)}); save(STATE,state); raise RuntimeError('ozon_record_has_outside_bindings')
 missing=[e for e in oz.values() if (e['product_id'],e['sku']) not in before]
 if missing:
  bp={'certificate_id':cid,'skus':sorted(e['sku'] for e in missing)}; marker=hashlib.sha256(json.dumps(bp,sort_keys=True).encode()).hexdigest()
  journal(OJ,{'phase':'bind_prepared','at':now(),'request_sha256':marker,'certificate_id':cid,'sku_count':len(missing),'skus':bp['skus']})
  state.update({'phase':'ozon_bind_outcome_pending','ozon_mutation_attempted':True,'ozon_bind_requested':len(missing)}); save(STATE,state)
  try: resp=c.call('ozon','/v1/product/certificate/bind',bp,mutation=True); state['ozon_bind_response']=resp; journal(OJ,{'phase':'bind_response','at':now(),'response':resp})
  except Exception as exc: state.update({'phase':'ozon_bind_outcome_uncertain','ozon_bind_error_type':type(exc).__name__,'no_bind_retry':True}); journal(OJ,{'phase':'bind_outcome_uncertain','at':now(),'error_type':type(exc).__name__}); save(STATE,state); raise
  save(STATE,state)
 # Read exact pairs after binding; refuse to proceed if not all are visible.
 b_after=c.ozon_bindings(cid); bypid=collections.defaultdict(list)
 for b in b_after: bypid[str(b.get('product_id') or '')].append(b)
 binding_rows=[]
 for offer,e in sorted(oz.items()):
  found=[b for b in bypid.get(e['product_id'],[]) if str(b.get('sku') or '')==e['sku']]
  binding_rows.append({'offer_id':offer,'product_id':e['product_id'],'sku':e['sku'],'visible_exactly_once':len(found)==1,'status':(found[0].get('product_status_code') if len(found)==1 else None)})
 statuses=collections.Counter(str(x['status'] or 'unknown') for x in binding_rows if x['visible_exactly_once'])
 save(HERE/'navigator_37784_ozon_readback_20261022.json',{'checked_at_utc':now(),'read_only':True,'number':NUMBER,'certificate_id':cid,'record_status':record.get('status_code'),'expected_bindings':32,'exact_visible_bindings':sum(x['visible_exactly_once'] for x in binding_rows),'binding_status_counts':dict(statuses),'rows':binding_rows,'local_source_deleted':False})
 state.update({'ozon_bindings_expected':32,'ozon_bindings_visible_exact':sum(x['visible_exactly_once'] for x in binding_rows),'ozon_binding_status_counts':dict(statuses),'ozon_readback_rows':binding_rows,'phase':'ozon_bindings_read_back'}); save(STATE,state)
 # Fresh WB prewrite validation, preserve all fields and existing documents.
 desired={'type':1,'number':NUMBER,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
 updates=[]; already=[]; exclusions=[]; before_cards={}
 for i,offer in enumerate(sorted(wb),1):
  cards=[x for x in c.wb_cards(offer) if str(x.get('vendorCode') or '')==offer]
  e=wb[offer]
  if len(cards)!=1: exclusions.append({'offer_id':offer,'reason':'fresh_card_missing_or_duplicate','count':len(cards)}); continue
  card=cards[0]
  if str(card.get('nmID'))!=e['nmID'] or str(card.get('brand') or '').strip().casefold()!='navigator' or code_values(card)!=['8539520009']:
   exclusions.append({'offer_id':offer,'reason':'fresh_card_identity_or_tnved_changed'}); continue
  same=exact_wb(card)
  if same:
   exact=[d for d in same if str(d.get('type'))=='1' and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
   if len(same)==1 and len(exact)==1: already.append({'offer_id':offer,'document':exact[0]})
   else: exclusions.append({'offer_id':offer,'reason':'same_number_metadata_conflict','documents':same})
   continue
  payload=merge_wb(card,[desired])
  if payload is None: already.append({'offer_id':offer,'document':None}); continue
  updates.append({'offer_id':offer,'nmID':e['nmID'],'payload':payload}); before_cards[offer]=card
  if i%10==0: print(json.dumps({'phase':'wb_prewrite','checked':i,'updates':len(updates),'already':len(already),'excluded':len(exclusions)}),flush=True)
 save(WBEFORE,{'checked_at_utc':now(),'read_only':True,'cards':before_cards,'already_exact':already,'exclusions':exclusions})
 state.update({'wb_updates_planned':len(updates),'wb_already_exact':len(already),'wb_prewrite_exclusions':exclusions,'phase':'wb_prewrite_complete'}); save(STATE,state)
 if exclusions: raise RuntimeError('wb_prewrite_exclusions_stop_review_before_mutation')
 if updates:
  payload=[x['payload'] for x in updates]; size=len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())
  if size>9_500_000: raise RuntimeError('wb_payload_too_large')
  marker=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  journal(WJ,{'phase':'update_prepared','at':now(),'request_sha256':marker,'request_bytes':size,'card_count':len(updates),'offers':[x['offer_id'] for x in updates]})
  state.update({'phase':'wb_update_outcome_pending','wb_mutation_attempted':True,'wb_request_sha256':marker}); save(STATE,state)
  try: response=c.call('wb','/content/v2/cards/update',payload,mutation=True); state['wb_update_response']=response; journal(WJ,{'phase':'update_response','at':now(),'response':response})
  except Exception as exc: state.update({'phase':'wb_update_outcome_uncertain','wb_update_error_type':type(exc).__name__,'no_wb_retry':True}); journal(WJ,{'phase':'update_outcome_uncertain','at':now(),'error_type':type(exc).__name__}); save(STATE,state); raise
  save(STATE,state)
  if response.get('error') is not False: state.update({'phase':'wb_update_rejected_reconcile','no_wb_retry':True}); save(STATE,state); raise RuntimeError('wb_update_rejected')
 # Immediate targeted WB readback. Delayed confirmation is handled separately.
 before_map=before_cards; rows=[]
 for i,offer in enumerate(sorted(set(wb)-{x['offer_id'] for x in exclusions}),1):
  cards=[x for x in c.wb_cards(offer) if str(x.get('vendorCode') or '')==offer]
  if len(cards)!=1: rows.append({'offer_id':offer,'status':'missing_or_duplicate','card_count':len(cards)}); continue
  card=cards[0]; docs=exact_wb(card)
  exact=len(docs)==1 and str(docs[0].get('type'))=='1' and str(docs[0].get('startDate',''))[:10]==ISSUE and str(docs[0].get('endDate',''))[:10]==EXPIRY and docs[0].get('isEndless') is False
  unchanged=offer not in before_map or comparable_card(before_map[offer])==comparable_card(card)
  rows.append({'offer_id':offer,'nmID':str(card.get('nmID')),'exact_metadata':exact,'non_document_fields_unchanged':unchanged,'status':'verified_exact' if exact and unchanged else 'readback_mismatch','documents':docs,'verdict':docs[0].get('verdict') if docs else None})
  if i%10==0: print(json.dumps({'phase':'wb_readback','checked':i,'verified':sum(x['status']=='verified_exact' for x in rows)}),flush=True)
 counts=collections.Counter(r['status'] for r in rows); verdicts=collections.Counter('valid' if (r.get('verdict') or {}).get('reason')=='valid' else 'pending_review_or_unverified' if r.get('verdict') is None else 'other' for r in rows if r['status']=='verified_exact')
 wbproof={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'target_cards':len(rows),'updated_cards':len(updates),'already_exact_cards':len(already),'excluded_cards':exclusions,'status_counts':dict(counts),'verdict_counts':dict(verdicts),'wb_left_for_marketplace_review':True,'local_source_deleted':False,'results':rows}
 save(WBREAD,wbproof)
 complete=(state.get('ozon_bindings_visible_exact')==32 and counts.get('verified_exact')==32)
 state.update({'phase':'cross_marketplace_readback_complete' if complete else 'cross_marketplace_readback_incomplete','wb_exact_metadata_cards':counts.get('verified_exact',0),'wb_readback_status_counts':dict(counts),'wb_verdict_counts':dict(verdicts),'wb_review_left_pending':True,'local_source_deleted':False,'finished_at_utc':now()}); save(STATE,state)
 print(json.dumps({k:v for k,v in state.items() if k not in ('ozon_create_response','ozon_bind_response','wb_update_response','ozon_readback_rows')},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
