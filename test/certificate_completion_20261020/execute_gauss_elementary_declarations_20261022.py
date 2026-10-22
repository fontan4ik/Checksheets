#!/usr/bin/env python3
"""Upload two active Gauss Elementary declarations to exact Ozon/WB offers."""
from __future__ import annotations
import base64, collections, datetime, hashlib, json, pathlib, sys, time
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]; PILOT=ROOT/'test/certificate_api_pilot_20261012'
PREFLIGHT=HERE/'gauss_elementary_declarations_live_preflight_v2_20261022.json'
STATE=HERE/'gauss_elementary_declarations_execution_20261022.json'
BEFORE=HERE/'gauss_elementary_declarations_wb_before_20261022.json'
READBACK=HERE/'gauss_elementary_declarations_final_crossplatform_readback_20261022.json'
JOURNAL=HERE/'gauss_elementary_declarations_mutation_journal_20261022.jsonl'
ADDENDUM=HERE/'postwrite_coverage_addendum_20261022.json'
DOCS=[
 {'number':'ЕАЭС N RU Д-CN.РА05.В.08477/23','registry_id':'17832680','issue':'2023-06-30','expiry':'2028-06-29','sha256':'15289d16092b1dc56edcdc1fc5bec5affe6bde1bde771fb844d5c6ca6c542eec','pdf':'output_to_user/certificates/group_1/documents/gauss/33aab613ec7c4812c82c1f91.pdf','regulation':'ТР ТС 004/2011 и 020/2011'},
 {'number':'ЕАЭС N RU Д-CN.РА05.В.08558/23','registry_id':'17832766','issue':'2023-06-30','expiry':'2028-06-29','sha256':'26f46d687945f4874b13045d40474c8966cd9c5a781a0267db179100e7a7973f','pdf':'output_to_user/certificates/group_1/documents/gauss/a9ec13b68073ed632c9e564b.pdf','regulation':'ТР ЕАЭС 037/2016'}]
TARGETS=[{'offer_id':'613100150P-2','article':'613100150P','wattage':150,'product_id':'3084920081','sku':'3124680447','nmID':'669266414'},
         {'offer_id':'613100200P-2','article':'613100200P','wattage':200,'product_id':'3084920133','sku':'3124680736','nmID':'669266415'}]
FSA_SCOPE='FSA product pages list Gauss Elementary Promo articles 613100150P and 613100200P, TN VED 9405420012; production from 2023-03. Live seller offer/vendor codes encode those exact articles and titles identify Gauss Elementary 150W/200W products.'
sys.path.insert(0,str(PILOT))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number, wb_datetime, comparable_card
import run_all_found_certificates_20261014 as runner

def save(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(path)
def journal(row):
 with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps({'at':now(),**row},ensure_ascii=False)+'\n'); f.flush()
def list_certs(client):
 out=[]
 for page in range(1,101):
  result=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; batch=result.get('certificates')
  if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_invalid')
  out.extend(batch)
  if not batch or page>=int(result.get('page_count') or 0): return out
 raise RuntimeError('ozon_certificate_page_limit')
def find_record(client,number):
 matches=[x for x in list_certs(client) if norm_number(x.get('certificate_number'))==norm_number(number)]
 if len(matches)>1: raise RuntimeError('duplicate_ozon_record:'+number)
 return matches[0] if matches else None
def exact_wb(items,doc):
 return [x for x in items if norm_number(x.get('number'))==norm_number(doc['number']) and int(x.get('type') or 0)==2 and str(x.get('startDate') or '')[:10]==doc['issue'] and str(x.get('endDate') or '')[:10]==doc['expiry'] and x.get('isEndless') is False]
def wb_valid(verdict):
 return isinstance(verdict,dict) and verdict.get('verified') is True and verdict.get('status')==1 and verdict.get('reason')=='valid'
def get_card(client,offer):
 cards=client.wb_cards(offer)
 if len(cards)!=1: raise RuntimeError('wb_exact_card_count:'+offer+':'+str(len(cards)))
 return cards[0]
def same_prior_docs(old,new):
 def sig(d): return (norm_number(d.get('number')),int(d.get('type') or 0),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10],bool(d.get('isEndless')))
 oc=collections.Counter(sig(x) for x in (old.get('documents') or {}).get('items') or [])
 nc=collections.Counter(sig(x) for x in (new.get('documents') or {}).get('items') or [])
 return all(nc[k]>=v for k,v in oc.items())
def create_or_reuse(client,doc,targets):
 record=find_record(client,doc['number'])
 created=False; create_response=None
 if record is None:
  expiry=datetime.date.fromisoformat(doc['expiry']); source=ROOT/doc['pdf']; content=source.read_bytes()
  params={'name':'Декларация о соответствии № '+doc['number'],'certificate_type':'DECLARATION','certificate_country':'RU','accordance_type':'EAEU','number':doc['number'],'issue_date':wb_datetime(doc['issue']),'expired_date':{'date':{'day':expiry.day,'month':expiry.month,'year':expiry.year}},'skus':[str(targets[0]['sku'])],'product_type':'UNKNOWN','link_to_registry':f"https://pub.fsa.gov.ru/rds/declaration/view/{doc['registry_id']}/common",'files':[{'file_content':base64.b64encode(content).decode('ascii'),'name':source.name}]}
  body={'params':params}; encoded=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
  if len(encoded)>=15_000_000: raise RuntimeError('ozon_create_payload_too_large')
  journal({'platform':'ozon','endpoint':'/v2/product/certificate/create','phase':'prepared','number':doc['number'],'source_sha256':doc['sha256'],'payload_bytes':len(encoded),'payload_sha256':hashlib.sha256(encoded).hexdigest()})
  try: create_response=client.call('ozon','/v2/product/certificate/create',body,mutation=True)
  except Exception as exc: create_response=None; create_error=type(exc).__name__
  else: create_error=None
  journal({'platform':'ozon','endpoint':'/v2/product/certificate/create','phase':'response' if create_response is not None else 'uncertain','number':doc['number'],'response':create_response,'error_type':create_error})
  for _ in range(8):
   record=find_record(client,doc['number'])
   if record: break
   time.sleep(2)
  if not record: raise RuntimeError('ozon_create_uncertain_no_unique_record:'+doc['number'])
  created=True
  states=[x.get('state') for x in (create_response or {}).get('params',[]) if isinstance(x,dict)]
  metadata=(record.get('type_code')=='declaration' and str(record.get('issue_date') or '')[:10]==doc['issue'] and str(record.get('expire_date') or '')[:10]==doc['expiry'])
  if not metadata: raise RuntimeError('ozon_created_record_metadata_conflict:'+doc['number'])
  if create_response is None or create_response.get('status')!='COMPLETED' or not states or set(states)!={'VALID'}:
   raise RuntimeError('ozon_create_response_not_fully_validated:'+doc['number'])
 else:
  if not (record.get('type_code')=='declaration' and str(record.get('issue_date') or '')[:10]==doc['issue'] and str(record.get('expire_date') or '')[:10]==doc['expiry']):
   raise RuntimeError('existing_ozon_record_metadata_conflict:'+doc['number'])
 cert_id=int(record['certificate_id']); before=client.ozon_bindings(cert_id)
 by_pid=collections.defaultdict(list)
 for row in before: by_pid[str(row.get('product_id') or '')].append(row)
 allowed={str(x['product_id']):x for x in targets}
 outside=[row for row in before if str(row.get('product_id') or '') not in allowed]
 if outside: raise RuntimeError('existing_ozon_bindings_outside_target_set:'+doc['number'])
 missing=[]
 for target in targets:
  rows=by_pid[str(target['product_id'])]
  if len(rows)>1: raise RuntimeError('ozon_duplicate_binding:'+target['offer_id'])
  if rows and str(rows[0].get('sku') or '')!=str(target['sku']): raise RuntimeError('ozon_binding_sku_conflict:'+target['offer_id'])
  if rows and str(rows[0].get('product_status_code') or '').lower()=='declined': raise RuntimeError('ozon_binding_declined:'+target['offer_id'])
  if not rows: missing.append(target)
 bind_resp={'result':True,'already_bound':True}
 if missing:
  request={'certificate_id':cert_id,'skus':[str(x['sku']) for x in missing]}
  journal({'platform':'ozon','endpoint':'/v1/product/certificate/bind','phase':'prepared','number':doc['number'],'certificate_id':str(cert_id),'offers':[x['offer_id'] for x in missing],'skus':request['skus']})
  try: bind_resp=client.call('ozon','/v1/product/certificate/bind',request,mutation=True)
  except Exception as exc: journal({'platform':'ozon','endpoint':'/v1/product/certificate/bind','phase':'uncertain','number':doc['number'],'error_type':type(exc).__name__}); bind_resp=None
  else: journal({'platform':'ozon','endpoint':'/v1/product/certificate/bind','phase':'response','number':doc['number'],'response':bind_resp})
 current=client.ozon_bindings(cert_id); pairs=collections.defaultdict(list)
 for row in current: pairs[(str(row.get('product_id') or ''),str(row.get('sku') or ''))].append(row)
 rows=[]
 for target in targets:
  found=pairs[(str(target['product_id']),str(target['sku']))]
  rows.append({'offer_id':target['offer_id'],'exact_count':len(found),'status':found[0].get('product_status_code') if len(found)==1 else None})
 info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':doc['number']}).get('result') or {}
 result={'number':doc['number'],'certificate_id':str(cert_id),'record_status':info.get('status_code'),'created_this_run':created,'create_response':create_response,'create_error_type':create_error if created else None,'bind_response':bind_resp,'expected_bindings':len(targets),'exact_bindings':sum(x['exact_count']==1 for x in rows),'binding_status_counts':dict(collections.Counter(str(x['status'] or 'missing') for x in rows)),'bindings':rows}
 if result['exact_bindings']!=len(targets): raise RuntimeError('ozon_binding_readback_incomplete:'+doc['number'])
 return result

def main():
 for p in (STATE,BEFORE,READBACK,JOURNAL):
  if p.exists(): raise RuntimeError('execution_artifact_exists_inspect_first:'+p.name)
 pre=json.loads(PREFLIGHT.read_text());
 if pre.get('safe_to_write') is not True: raise RuntimeError('preflight_not_safe')
 for doc in DOCS:
  source=ROOT/doc['pdf']
  if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=doc['sha256']: raise RuntimeError('source_pdf_missing_or_hash_mismatch:'+doc['number'])
 ozon_targets={x['offer_id']:x for x in pre['ozon']['targets'] if x.get('eligible') is True}
 wb_targets={x['offer_id']:x for x in pre['wb']['targets'] if x.get('eligible') is True}
 if set(ozon_targets)!=set(x['offer_id'] for x in TARGETS) or set(wb_targets)!=set(ozon_targets): raise RuntimeError('preflight_target_set_incomplete')
 targets=[]
 for t in TARGETS:
  o=ozon_targets[t['offer_id']];w=wb_targets[t['offer_id']]
  if any(str(o[k])!=str(t[v]) for k,v in [('product_id','product_id'),('sku','sku')]) or str(w.get('nmID'))!=t['nmID'] or str(w.get('vendorCode'))!=t['offer_id']:
   raise RuntimeError('preflight_market_identity_changed:'+t['offer_id'])
  targets.append({**t,'live_name':o.get('name'),'tnved_codes':o.get('tnved_codes')})
 client=Client();state={'started_at_utc':now(),'phase':'prewrite_revalidated','brand':'Gauss','declarations':[x['number'] for x in DOCS],'targets':targets,'fsa_scope_basis':FSA_SCOPE,'source_pdfs_retained':True,'wb_left_for_review':True}
 # Last read-only identity and duplicate/conflict check before any write.
 cards=[]
 for t in targets:
  card=get_card(client,t['offer_id'])
  if str(card.get('nmID') or '')!=t['nmID'] or str(card.get('vendorCode') or '')!=t['offer_id'] or str(card.get('brand') or '').casefold()!='gauss': raise RuntimeError('wb_identity_changed:'+t['offer_id'])
  cards.append(card)
 for doc in DOCS:
  record=find_record(client,doc['number'])
  if record and not (record.get('type_code')=='declaration' and str(record.get('issue_date') or '')[:10]==doc['issue'] and str(record.get('expire_date') or '')[:10]==doc['expiry']): raise RuntimeError('ozon_record_conflict_prewrite:'+doc['number'])
 for card in cards:
  items=copy_documents(card)
  for doc in DOCS:
   same=[x for x in items if norm_number(x.get('number'))==norm_number(doc['number'])]
   exact=exact_wb(items,doc)
   if same and (len(same)!=1 or len(exact)!=1): raise RuntimeError('wb_existing_document_conflict:'+doc['number']+':'+str(card.get('vendorCode')))
 # Save exact WB before-state before Ozon or WB mutations.
 save(BEFORE,{'checked_at_utc':now(),'complete':True,'cards':[{'offer_id':str(c['vendorCode']),'nmID':str(c['nmID']),'card':c,'prior_documents':copy_documents(c)} for c in cards]})
 save(STATE,state)
 ozon_results=[]
 for doc in DOCS:
  # PDF hash is checked again immediately before upload.
  if hashlib.sha256((ROOT/doc['pdf']).read_bytes()).hexdigest()!=doc['sha256']: raise RuntimeError('source_hash_changed:'+doc['number'])
  ozon_results.append(create_or_reuse(client,doc,targets))
 state['ozon_results']=ozon_results;state['phase']='ozon_records_and_bindings_visible';save(STATE,state)
 desired=[{'type':2,'number':doc['number'],'startDate':wb_datetime(doc['issue']),'endDate':wb_datetime(doc['expiry']),'isEndless':False} for doc in DOCS]
 wb_payloads=[]; wb_before_by_offer={}
 for card in cards:
  offer=str(card['vendorCode']); wb_before_by_offer[offer]=card
  payload=runner.merge_wb(card,desired)
  if payload is not None: wb_payloads.append({'offer_id':offer,'nmID':str(card['nmID']),'payload':payload})
 wb_response=None; wb_error=None
 if wb_payloads:
  payload=[x['payload'] for x in wb_payloads]
  journal({'platform':'wb','endpoint':'/content/v2/cards/update','phase':'prepared','offers':[x['offer_id'] for x in wb_payloads],'nmIDs':[x['nmID'] for x in wb_payloads],'documents':[x['number'] for x in DOCS],'payload_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()})
  try: wb_response=client.call('wb','/content/v2/cards/update',payload,mutation=True)
  except Exception as exc: wb_error=type(exc).__name__; journal({'platform':'wb','endpoint':'/content/v2/cards/update','phase':'uncertain','error_type':wb_error})
  else: journal({'platform':'wb','endpoint':'/content/v2/cards/update','phase':'response','response':wb_response})
 # Reconcile live state before deciding whether a retry would be safe.
 wb_rows=[]
 for t in targets:
  card=get_card(client,t['offer_id']); old=wb_before_by_offer[t['offer_id']]; items=copy_documents(card)
  exact_by_doc={d['number']:len(exact_wb(items,d)) for d in DOCS}
  status_by_doc={}
  for d in DOCS:
   exact=exact_wb(items,d); verdict=exact[0].get('verdict') if len(exact)==1 else None
   status_by_doc[d['number']]='valid' if wb_valid(verdict) else ('pending_review_or_no_verdict' if len(exact)==1 else 'missing_or_conflict')
  preserved=same_prior_docs(old,card) and comparable_card(old)==comparable_card(card)
  wb_rows.append({'offer_id':t['offer_id'],'nmID':str(card.get('nmID') or ''),'exact_document_counts':exact_by_doc,'statuses':status_by_doc,'previous_documents_and_card_fields_preserved':preserved})
 state['wb_response']=wb_response;state['wb_error_type']=wb_error;state['wb_initial_readback']=wb_rows;state['phase']='marketplace_write_readback';save(STATE,state)
 # A delayed readback catches Ozon moderation and WB persistence. Leave WB review untouched.
 time.sleep(60)
 delayed_ozon=[]
 for doc in DOCS:
  rec=find_record(client,doc['number'])
  if not rec: raise RuntimeError('ozon_record_disappeared:'+doc['number'])
  bindings=client.ozon_bindings(int(rec['certificate_id'])); by_pair=collections.defaultdict(list)
  for b in bindings: by_pair[(str(b.get('product_id') or ''),str(b.get('sku') or ''))].append(b)
  rows=[]
  for t in targets:
   found=by_pair[(t['product_id'],t['sku'])]; rows.append({'offer_id':t['offer_id'],'exact_count':len(found),'status':found[0].get('product_status_code') if len(found)==1 else None})
  info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':doc['number']}).get('result') or {}
  delayed_ozon.append({'number':doc['number'],'certificate_id':str(rec['certificate_id']),'record_status':info.get('status_code'),'expected_bindings':len(targets),'exact_bindings':sum(x['exact_count']==1 for x in rows),'binding_status_counts':dict(collections.Counter(str(x['status'] or 'missing') for x in rows)),'bindings':rows})
 delayed_wb=[]
 for t in targets:
  card=get_card(client,t['offer_id']); items=copy_documents(card); old=wb_before_by_offer[t['offer_id']]
  doc_status={}
  for d in DOCS:
   found=exact_wb(items,d); verdict=found[0].get('verdict') if len(found)==1 else None
   doc_status[d['number']]={'exact_count':len(found),'verdict':verdict,'state':'valid' if wb_valid(verdict) else ('pending_review_or_no_verdict' if len(found)==1 else 'missing_or_conflict')}
  delayed_wb.append({'offer_id':t['offer_id'],'nmID':str(card.get('nmID') or ''),'documents':doc_status,'previous_documents_and_card_fields_preserved':same_prior_docs(old,card) and comparable_card(old)==comparable_card(card)})
 write_ok=all(x['exact_bindings']==len(targets) for x in delayed_ozon) and all(all(d['exact_count']==1 for d in row['documents'].values()) and row['previous_documents_and_card_fields_preserved'] for row in delayed_wb)
 result={'checked_at_utc':now(),'brand':'Gauss','fsa_scope_basis':FSA_SCOPE,'declarations':[{'number':d['number'],'fsa_record_id':d['registry_id'],'fsa_status':'active','issue_date':d['issue'],'expiry_date':d['expiry'],'regulation':d['regulation'],'source_sha256':d['sha256'],'local_source_pdf_deleted':False} for d in DOCS],'ozon':delayed_ozon,'wb':delayed_wb,'wb_review_left_pending':True,'wb_review_state_changed_by_agent':False,'local_source_pdfs_deleted':False,'exact_crossplatform_metadata_verified':write_ok,'verification_artifacts':[PREFLIGHT.name,STATE.name,BEFORE.name,READBACK.name]}
 save(READBACK,result);state['phase']='delayed_readback_complete' if write_ok else 'readback_incomplete';state['delayed_readback_path']=str(READBACK);state['finished_at_utc']=now();save(STATE,state)
 if write_ok:
  add=json.loads(ADDENDUM.read_text(encoding='utf-8')); entries=add.get('post_snapshot_writes',[])
  for doc,oz in zip(DOCS,delayed_ozon):
   if any(x.get('document_number')==doc['number'] for x in entries): raise RuntimeError('addendum_duplicate:'+doc['number'])
   wb_valid=sum(row['documents'][doc['number']]['state']=='valid' for row in delayed_wb)
   wb_exact=sum(row['documents'][doc['number']]['exact_count']==1 for row in delayed_wb)
   entries.append({'brand':'Gauss','document_number':doc['number'],'type':'declaration','fsa_record_id':doc['registry_id'],'fsa_status':'active','source_sha256':doc['sha256'],'ozon_certificate_id':oz['certificate_id'],'ozon_record_status':oz['record_status'],'ozon_expected_bindings':oz['expected_bindings'],'ozon_exact_bindings':oz['exact_bindings'],'ozon_binding_status_counts':oz['binding_status_counts'],'ozon_out_of_scope_or_identity_skipped':0,'wb_expected_cards':len(targets),'wb_exact_cards':wb_exact,'wb_valid_cards':wb_valid,'wb_pending_or_unverified_cards':wb_exact-wb_valid,'wb_skipped':[],'wb_review_state_changed_by_agent':False,'wb_left_for_marketplace_review':True,'local_source_pdf_deleted':False,'limitation':'Marketplace code and active FSA product scope match the exact seller offer/article and wattage; WB review remains with marketplace.','verification_artifacts':[PREFLIGHT.name,STATE.name,READBACK.name]})
  add['post_snapshot_writes']=entries; totals=add['post_snapshot_totals']; totals['ozon_certificate_records']+=len(DOCS); totals['ozon_live_bindings']+=sum(x['exact_bindings'] for x in delayed_ozon)
  for oz in delayed_ozon:
   status=oz['record_status']; key={'approved':'approved','awaiting_verification':'awaiting_verification','under_review':'awaiting_verification','declined':'declined'}.get(status)
   if key: totals['ozon_certificate_statuses'][key]+=1
  newly_covered=sum(all(next(d for d in delayed_ozon if d['number']==doc['number'])['binding_status_counts'].get('approved',0)==len(targets) for doc in DOCS) for t in targets)
  totals['ozon_products_with_at_least_one_current_approved_document']+=newly_covered; totals['ozon_products_without_any_current_approved_document']-=newly_covered
  totals['wb_cards_with_at_least_one_valid_document']+=sum(any(x['documents'][d['number']]['state']=='valid' for d in DOCS) for x in delayed_wb)
  totals['newly_verified_wb_cards']+=sum(any(x['documents'][d['number']]['state']=='valid' for d in DOCS) for x in delayed_wb)
  add.setdefault('current_live_reconciliations',{})['gauss_elementary_declarations_20261022']={'documents':len(DOCS),'ozon_exact_bindings':sum(x['exact_bindings'] for x in delayed_ozon),'ozon_record_status_counts':dict(collections.Counter(str(x['record_status'] or 'unknown') for x in delayed_ozon)),'ozon_binding_status_counts':{x['number']:x['binding_status_counts'] for x in delayed_ozon},'wb_cards':len(delayed_wb),'wb_exact_document_bindings':sum(sum(v['exact_count']==1 for v in x['documents'].values()) for x in delayed_wb),'wb_valid_document_bindings':sum(sum(v['state']=='valid' for v in x['documents'].values()) for x in delayed_wb),'wb_pending_or_unverified_document_bindings':sum(sum(v['state']=='pending_review_or_no_verdict' for v in x['documents'].values()) for x in delayed_wb),'mutation_attempted':bool(wb_payloads or any(x['created_this_run'] for x in ozon_results)),'local_source_files_deleted':False,'verification_artifact':str(READBACK)}
  add['checked_at_utc']=now();add['complete']=False;add['local_source_pdfs_deleted']=False;save(ADDENDUM,add)
 print(json.dumps({'phase':state['phase'],'exact_crossplatform_metadata_verified':write_ok,'ozon':[{'number':x['number'],'record_status':x['record_status'],'exact_bindings':x['exact_bindings'],'binding_status_counts':x['binding_status_counts']} for x in delayed_ozon],'wb_cards':len(delayed_wb),'wb_exact_document_bindings':sum(sum(v['exact_count']==1 for v in x['documents'].values()) for x in delayed_wb),'wb_review_left_pending':True,'local_source_pdfs_deleted':False},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__': main()
