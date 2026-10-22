from __future__ import annotations
import collections, datetime as dt, hashlib, json, pathlib, sys, time
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012'; sys.path.insert(0,str(API))
from api_client import Client, now, digest
from reconcile_approved_ozon_docs_to_wb import norm_number, doc_key, wb_datetime, copy_documents, comparable_card, UPDATE_CARD_FIELDS
import run_all_found_certificates_20261014 as runner
PREFLIGHT=HERE/'arlight_02669_crossplatform_preflight_live_20261021.json'
OZON_STATE=HERE/'arlight_02669_ozon_execution_20261021.json'
STATE=HERE/'arlight_02669_wb_execution_20261021.json'
BEFORE=HERE/'arlight_02669_wb_before_20261021.json'
READBACK=HERE/'arlight_02669_wb_readback_20261021.json'
JOURNAL=HERE/'arlight_02669_wb_mutation_journal_20261021.jsonl'
NUMBER='ЕАЭС RU С-HK.АБ53.В.02669/21'; ISSUE='2021-12-08'; EXPIRY='2026-12-07'; EXPECTED=578; CERT_ID='5928221'

def save(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)); tmp.replace(path)
def append(obj):
 with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps(obj,ensure_ascii=False)+'\n'); f.flush()
def tnved(card):
 values=[]
 for c in card.get('characteristics') or []:
  name=''.join(str(c.get('name') or '').casefold().split()).replace('ё','е')
  if 'тнвэд' not in name and 'тнвед' not in name: continue
  raw=c.get('value'); raw=raw if isinstance(raw,list) else [raw]
  values.extend(str(v or '').split(' - ',1)[0].strip() for v in raw if v)
 return sorted(set(values))
def signature(doc):
 return (doc_key(doc),str(doc.get('startDate',''))[:10],str(doc.get('endDate',''))[:10],bool(doc.get('isEndless')))
def main():
 if any(p.exists() for p in (STATE,BEFORE,READBACK,JOURNAL)): raise RuntimeError('wb_execution_artifact_exists_reconcile_before_retry')
 pre=json.loads(PREFLIGHT.read_text()); oz=json.loads(OZON_STATE.read_text())
 if not pre.get('eligible_for_upload') or pre.get('eligible_wb_cards_for_add')!=EXPECTED or not pre.get('ozon_exact_record_absence_confirmed'):
  raise RuntimeError('wb_preflight_not_eligible')
 if oz.get('phase')!='ozon_verified_complete' or str(oz.get('certificate_id'))!=CERT_ID or oz.get('verified_target_pairs')!=EXPECTED:
  raise RuntimeError('ozon_bindings_not_verified')
 targets={x['offer_id']:x for x in pre.get('wb_cards') or []}
 if len(targets)!=EXPECTED or any(not x.get('eligible_for_add') for x in targets.values()): raise RuntimeError('wb_candidate_map_incomplete')
 oz_targets={x['offer_id']:x for x in pre['ozon_targets']}
 bindings={x['offer_id'] for x in oz.get('bindings') or [] if x.get('bound')}
 if bindings!=set(targets): raise RuntimeError('ozon_binding_offer_set_mismatch')
 state={'started_at':now(),'phase':'fresh_prewrite_recheck','number':NUMBER,'certificate_id':CERT_ID,'target_cards':EXPECTED,'writes_sent':0,'wb_review_left_pending':True,'local_file_deleted':False,'tnved_mismatch_recorded':True}
 save(STATE,state); client=Client()
 info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
 if (str(info.get('certificate_id'))!=CERT_ID or norm_number(info.get('certificate_number'))!=norm_number(NUMBER) or info.get('type_code')!='certificate_of_conformity' or str(info.get('issue_date',''))[:10]!=ISSUE or str(info.get('expire_date',''))[:10]!=EXPIRY or str(info.get('accordance_type_code','')).upper()!='EAEU' or info.get('status_code') in {'declined','rejected','invalid','cancelled'}):
  state.update(phase='aborted_ozon_metadata_changed',certificate_info=info,updated_at=now());save(STATE,state);raise RuntimeError('ozon_document_metadata_conflict_before_wb')
 live_bindings=client.ozon_bindings(int(CERT_ID)); live_by_id={str(x.get('product_id')):x for x in live_bindings}
 if len(live_bindings)!=EXPECTED or len(live_by_id)!=EXPECTED: raise RuntimeError('ozon_live_binding_count_mismatch_before_wb')
 for offer,t in oz_targets.items():
  b=live_by_id.get(t['product_id'])
  if not b or str(b.get('sku'))!=t['sku']: raise RuntimeError('ozon_live_binding_pair_missing_before_wb:'+offer)
 document={'type':1,'number':NUMBER,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
 prepared=[]; failures=[]
 for index,(offer,first) in enumerate(sorted(targets.items()),1):
  cards=client.wb_cards(offer)
  if len(cards)!=1:
   failures.append({'offer_id':offer,'reason':'wb_card_missing_or_ambiguous','card_count':len(cards)});continue
  card=cards[0]
  identity=str(card.get('vendorCode') or '')==offer and str(card.get('nmID') or '')==str(first.get('nmID') or first.get('assigned_nmID') or '')
  brand=str(card.get('brand') or '').strip().casefold()=='arlight'
  current_tnved=tnved(card)
  prior_tnved=first.get('tnved_codes') or []
  same_tnved=current_tnved==prior_tnved
  docs=copy_documents(card); same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
  exact=[d for d in same if doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  if len(same)==1 and len(exact)==1:
   prepared.append({'offer_id':offer,'nmID':str(card['nmID']),'before':card,'already_exact':True,'prior_document_signatures':[signature(d) for d in docs]})
  elif not identity or not brand or not same_tnved or same:
   failures.append({'offer_id':offer,'reason':'live_card_identity_scope_or_document_conflict','identity_matches':identity,'brand_matches':brand,'tnved_before':prior_tnved,'tnved_live':current_tnved,'same_number_docs':len(same),'exact_number_docs':len(exact)})
  else:
   payload=runner.merge_wb(card,[document])
   if payload is None or str(payload.get('nmID'))!=str(card.get('nmID')): failures.append({'offer_id':offer,'reason':'merge_refused_or_nmID_mismatch'})
   else: prepared.append({'offer_id':offer,'nmID':str(card['nmID']),'before':card,'payload':payload,'already_exact':False,'prior_document_signatures':[signature(d) for d in docs]})
  if index%50==0:
   state.update(phase='fresh_prewrite_recheck',checked=index,prepared_cards=len(prepared),failures=len(failures),updated_at=now());save(STATE,state)
   print(json.dumps({'phase':'fresh_prewrite_recheck','checked':index,'prepared':len(prepared),'failures':len(failures)}),flush=True)
 if len(prepared)!=EXPECTED or failures:
  state.update(phase='aborted_prewrite_recheck_changed',prepared_cards=len(prepared),failures=failures,mutation_sent=False,updated_at=now());save(STATE,state);raise RuntimeError('wb_prewrite_recheck_incomplete_no_mutation')
 payload_rows=[x for x in prepared if not x['already_exact']]
 save(BEFORE,{'checked_at':now(),'complete':True,'target_count':len(prepared),'write_count':len(payload_rows),'number':NUMBER,'scope_basis':pre.get('applicability_assessment',{}).get('scope_basis'),'cards':[{'offer_id':x['offer_id'],'nmID':x['nmID'],'before':x['before'],'prior_document_signatures':x['prior_document_signatures'],'already_exact':x['already_exact']} for x in prepared]})
 batches=[payload_rows[i:i+100] for i in range(0,len(payload_rows),100)]
 encoded=json.dumps([x['payload'] for x in payload_rows],ensure_ascii=False,separators=(',',':')).encode()
 if len(encoded)>9_000_000: raise RuntimeError('wb_payload_exceeds_safe_batch_size')
 state.update(phase='wb_prewrite_verified',prepared_cards=len(prepared),write_cards=len(payload_rows),batch_count=len(batches),payload_bytes=len(encoded),certificate_info=info,ozon_binding_count=len(live_bindings),updated_at=now());save(STATE,state)
 last_send=None
 for batch_no,batch in enumerate(batches,1):
  if last_send is not None:
   delay=7.0-(time.monotonic()-last_send)
   if delay>0: time.sleep(delay)
  payload=[x['payload'] for x in batch]
  marker=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
  append({'phase':'prepared','at':now(),'batch':batch_no,'cards':len(batch),'sha256':marker})
  state.update(phase='wb_update_sent',current_batch=batch_no,writes_sent=state['writes_sent']+1,updated_at=now());save(STATE,state)
  last_send=time.monotonic()
  try: response=client.call('wb','/content/v2/cards/update',payload,mutation=True)
  except Exception as exc:
   append({'phase':'uncertain','at':now(),'batch':batch_no,'sha256':marker,'error_type':type(exc).__name__})
   state.update(phase='wb_update_uncertain',error_type=type(exc).__name__,updated_at=now());save(STATE,state);raise RuntimeError('wb_write_uncertain_reconcile_before_retry') from None
  append({'phase':'response','at':now(),'batch':batch_no,'response':response,'sha256':marker})
  if response.get('error') is not False or response.get('additionalErrors'):
   state.update(phase='wb_update_rejected',response=response,updated_at=now());save(STATE,state);raise RuntimeError('wb_update_rejected_stop_and_reconcile')
  state.update(phase='wb_batches_progress',completed_batches=batch_no,updated_at=now());save(STATE,state)
  print(json.dumps({'phase':'wb_batch_complete','batch':batch_no,'batches':len(batches),'cards':len(batch)}),flush=True)
 # Read every card back from WB and check metadata, prior documents, and unrelated fields.
 old={x['offer_id']:x for x in prepared}; rows=[]; statuses=collections.Counter()
 for index,(offer,entry) in enumerate(sorted(old.items()),1):
  cards=client.wb_cards(offer)
  if len(cards)!=1:
   rows.append({'offer_id':offer,'nmID':entry['nmID'],'verified':False,'reason':'live_card_missing_or_ambiguous'});continue
  card=cards[0]; docs=copy_documents(card); same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
  exact=[d for d in same if doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  actual=collections.Counter(signature(d) for d in docs); old_sigs=collections.Counter(entry['prior_document_signatures'])
  preserved=all(actual[key]>=count for key,count in old_sigs.items())
  before=entry['before']; fields=comparable_card(card)==comparable_card(before)
  identity=str(card.get('vendorCode') or '')==offer and str(card.get('nmID') or '')==entry['nmID']
  brand=str(card.get('brand') or '').strip().casefold()=='arlight'
  okay=len(same)==1 and len(exact)==1 and preserved and fields and identity and brand
  rows.append({'offer_id':offer,'nmID':str(card.get('nmID') or ''),'verified':okay,'exact_document_count':len(exact),'metadata_exact':len(exact)==1,'document_status':'pending_review_or_verdict_missing' if len(exact)==1 else 'missing_or_conflicting','prior_documents_preserved':preserved,'unrelated_fields_preserved':fields,'identity_preserved':identity,'brand_preserved':brand})
  if okay: statuses['pending_review_or_verdict_missing']+=1
  if index%50==0:
   state.update(phase='wb_targeted_readback',readback_checked=index,updated_at=now());save(STATE,state)
   print(json.dumps({'phase':'wb_targeted_readback','checked':index,'target_cards':EXPECTED}),flush=True)
 failures=[r for r in rows if not r.get('verified')]
 readback={'checked_at':now(),'complete':not failures and len(rows)==EXPECTED,'number':NUMBER,'target_cards':len(rows),'verified_target_cards':len(rows)-len(failures),'status_counts':dict(statuses),'failures':failures,'cards':rows,'wb_review_left_pending':True,'manual_wb_review_action_taken':False,'local_file_deleted':False}
 save(READBACK,readback)
 state.update(phase='verified_complete' if not failures else 'readback_incomplete',readback_path=str(READBACK),verified_target_cards=len(rows)-len(failures),status_counts=dict(statuses),failures=failures,wb_review_left_pending=True,updated_at=now(),local_file_deleted=False)
 save(STATE,state)
 print(json.dumps({'phase':state['phase'],'verified_target_cards':len(rows)-len(failures),'status_counts':dict(statuses),'failures':failures,'wb_review_left_pending':True,'local_file_deleted':False},ensure_ascii=False,indent=2))
 if failures: raise RuntimeError('wb_readback_incomplete')
if __name__=='__main__':main()
