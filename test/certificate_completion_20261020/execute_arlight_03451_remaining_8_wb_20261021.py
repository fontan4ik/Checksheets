from __future__ import annotations
import collections,hashlib,json,pathlib,sys,time
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012';sys.path.insert(0,str(API))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number,doc_key,wb_datetime,copy_documents,comparable_card
import run_all_found_certificates_20261014 as runner
PREFLIGHT=HERE/'arlight_03451_remaining_8_live_preflight_20261021.json'
OZON_STATE=HERE/'arlight_03451_ozon_execution_20261021.json'
STATE=HERE/'arlight_03451_remaining_8_wb_execution_20261021.json'
BEFORE=HERE/'arlight_03451_remaining_8_wb_before_20261021.json'
READBACK=HERE/'arlight_03451_remaining_8_wb_readback_20261021.json'
JOURNAL=HERE/'arlight_03451_remaining_8_wb_mutation_journal_20261021.jsonl'
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/772DD20BAEF0AD4FA297663655BFAC3A.pdf'
NUMBER='ЕАЭС RU С-HK.НА46.В.03451/22';ISSUE='2022-04-16';EXPIRY='2027-04-15';CERT_ID='5925989';TNVED='8504408300';EXPECTED=8;SHA='22f5bd0657cf8c55754b3bd0d73d102de1b9520d6c167242555ae63349398add'

def save(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def append(x):
 with JOURNAL.open('a',encoding='utf-8') as f:f.write(json.dumps(x,ensure_ascii=False)+'\n');f.flush()
def tnved(card):
 out=[]
 for c in card.get('characteristics') or []:
  name=''.join(str(c.get('name') or '').casefold().split()).replace('ё','е')
  if 'тнвэд' not in name and 'тнвед' not in name:continue
  raw=c.get('value');raw=raw if isinstance(raw,list) else [raw]
  out.extend(str(v or '').split(' - ',1)[0].strip() for v in raw if v)
 return sorted(set(out))
def signature(d):return (doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10],bool(d.get('isEndless')))
def main():
 prior_state=json.loads(STATE.read_text()) if STATE.exists() else None
 safe_retry=bool(prior_state and prior_state.get('phase')=='aborted_prewrite_recheck_changed' and prior_state.get('mutation_sent') is False and prior_state.get('writes_sent',0)==0 and not BEFORE.exists() and not READBACK.exists() and not JOURNAL.exists())
 if any(p.exists() for p in (BEFORE,READBACK,JOURNAL)) or (STATE.exists() and not safe_retry):raise RuntimeError('remaining_8_execution_artifact_exists_reconcile_before_retry')
 pre=json.loads(PREFLIGHT.read_text());oz=json.loads(OZON_STATE.read_text())
 if pre.get('target_count')!=EXPECTED or pre.get('eligible_count')!=7 or not pre.get('read_only'):raise RuntimeError('fresh_preflight_counts_changed')
 if digest(SOURCE)!=SHA or digest(SOURCE)!=pre.get('source_pdf_sha256'):raise RuntimeError('source_pdf_hash_changed')
 if oz.get('phase')!='ozon_verified_complete' or str(oz.get('certificate_id'))!=CERT_ID or oz.get('verified_target_pairs')!=462:raise RuntimeError('ozon_binding_state_not_complete')
 targets=pre.get('targets') or []
 if len(targets)!=EXPECTED or len({x['offer_id'] for x in targets})!=EXPECTED:raise RuntimeError('target_offer_set_invalid')
 generic=[x for x in targets if not x.get('eligible')]
 if len(generic)!=1 or generic[0]['offer_id']!='026679(2)-1':raise RuntimeError('unexpected_unconfirmed_product')
 g=generic[0]
 if not (g.get('assigned_nmID')==g.get('wb_nmID') and g.get('wb_assigned_nmID_matches')==1 and g.get('wb_returned_card_count')==1 and g.get('wb_brand')=='Arlight' and g.get('wb_tnved')==[] and '24В' in str(g.get('wb_title')) and '240Вт' in str(g.get('wb_title')) and '24V' in str(g.get('ozon_name')) and '240W' in str(g.get('ozon_name')) and g.get('ozon_binding_approved') and g.get('ozon_tnved')==[TNVED]):raise RuntimeError('generic_card_spec_identity_not_confirmed')
 client=Client();info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
 if str(info.get('certificate_id'))!=CERT_ID or info.get('status_code')!='approved' or str(info.get('issue_date',''))[:10]!=ISSUE or str(info.get('expire_date',''))[:10]!=EXPIRY:raise RuntimeError('ozon_certificate_info_changed')
 bindings=client.ozon_bindings(int(CERT_ID))
 byid={str(x.get('product_id')):x for x in bindings}
 if len(bindings)!=462 or len(byid)!=462:raise RuntimeError('ozon_binding_count_changed')
 prepared=[];failures=[];document={'type':1,'number':NUMBER,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
 for t in targets:
  offer=t['offer_id']
  livebind=byid.get(str(t['product_id']))
  if not livebind or str(livebind.get('sku'))!=str(t['sku']) or livebind.get('product_status_code')!='approved':failures.append({'offer_id':offer,'reason':'live_ozon_binding_pair_changed'});continue
  cards=client.wb_cards(offer);exact=[c for c in cards if str(c.get('nmID'))==str(t['assigned_nmID']) and str(c.get('vendorCode'))==offer]
  if len(exact)!=1:failures.append({'offer_id':offer,'reason':'assigned_wb_nmID_missing_or_ambiguous','cards':len(cards),'assigned_matches':len(exact)});continue
  card=exact[0];brand=str(card.get('brand') or '').strip().casefold()=='arlight';codes=tnved(card);same=[d for d in copy_documents(card) if norm_number(d.get('number'))==norm_number(NUMBER)]
  if not brand or codes or same:failures.append({'offer_id':offer,'reason':'live_card_scope_or_document_conflict','brand':card.get('brand'),'tnved':codes,'same_number_docs':len(same)});continue
  if offer==g['offer_id']:
   title=str(card.get('title') or '')
   ozname=str(t['ozon_name'] or '')
   if not ('24В' in title and '240Вт' in title and '24V' in ozname and '240W' in ozname):failures.append({'offer_id':offer,'reason':'generic_card_specs_changed'});continue
  payload=runner.merge_wb(card,[document])
  if payload is None or str(payload.get('nmID'))!=str(card.get('nmID')):failures.append({'offer_id':offer,'reason':'merge_refused_or_identity_mismatch'});continue
  docs=copy_documents(card)
  prepared.append({'offer_id':offer,'nmID':str(card['nmID']),'before':card,'payload':payload,'prior_document_signatures':[signature(d) for d in docs],'scope_basis':'exact_model_code' if t.get('eligible') else 'exact_seller_offer_nmID_brand_and_matching_24V_240W_specs'})
 if failures or len(prepared)!=EXPECTED:
  state={'started_at':now(),'phase':'aborted_prewrite_recheck_changed','number':NUMBER,'prepared_cards':len(prepared),'failures':failures,'mutation_sent':False,'writes_sent':0,'local_file_deleted':False};save(STATE,state);raise RuntimeError('prewrite_scope_incomplete_no_mutation')
 save(BEFORE,{'checked_at':now(),'complete':True,'target_count':EXPECTED,'number':NUMBER,'certificate_info':info,'cards':[{'offer_id':x['offer_id'],'nmID':x['nmID'],'before':x['before'],'prior_document_signatures':x['prior_document_signatures'],'scope_basis':x['scope_basis']} for x in prepared]})
 payload=[x['payload'] for x in prepared];encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
 if len(encoded)>9_000_000:raise RuntimeError('wb_payload_too_large')
 state={'started_at':now(),'phase':'wb_prewrite_verified','number':NUMBER,'certificate_id':CERT_ID,'target_cards':EXPECTED,'writes_sent':0,'payload_bytes':len(encoded),'wb_review_left_pending':True,'manual_wb_review_action_taken':False,'local_file_deleted':False,'tnved_blank_retained':True};save(STATE,state)
 marker=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest();append({'phase':'prepared','at':now(),'cards':EXPECTED,'sha256':marker})
 state.update(phase='wb_update_sent',writes_sent=1,updated_at=now());save(STATE,state)
 try:response=client.call('wb','/content/v2/cards/update',payload,mutation=True)
 except Exception as e:
  append({'phase':'uncertain','at':now(),'sha256':marker,'error_type':type(e).__name__});state.update(phase='wb_update_uncertain',error_type=type(e).__name__,updated_at=now());save(STATE,state);raise RuntimeError('wb_update_uncertain_reconcile_before_retry') from None
 append({'phase':'response','at':now(),'response':response,'sha256':marker})
 if response.get('error') is not False or response.get('additionalErrors'):state.update(phase='wb_update_rejected',response=response,updated_at=now());save(STATE,state);raise RuntimeError('wb_update_rejected')
 rows=[];statuses=collections.Counter()
 for x in prepared:
  cards=client.wb_cards(x['offer_id']);
  if len(cards)!=1:rows.append({'offer_id':x['offer_id'],'nmID':x['nmID'],'verified':False,'reason':'missing_or_ambiguous_readback'});continue
  card=cards[0];docs=copy_documents(card);same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)];exact=[d for d in same if doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  preserved=all(collections.Counter(signature(d) for d in docs)[sig]>=1 for sig in x['prior_document_signatures'])
  fields=comparable_card(card)==comparable_card(x['before']);identity=str(card.get('vendorCode') or '')==x['offer_id'] and str(card.get('nmID') or '')==x['nmID'];brand=str(card.get('brand') or '').strip().casefold()=='arlight';okay=len(same)==1 and len(exact)==1 and preserved and fields and identity and brand
  rows.append({'offer_id':x['offer_id'],'nmID':str(card.get('nmID') or ''),'verified':okay,'metadata_exact':len(exact)==1,'exact_document_count':len(exact),'prior_documents_preserved':preserved,'unrelated_fields_preserved':fields,'identity_preserved':identity,'brand_preserved':brand,'wb_document_verdict':'pending_review_or_verdict_missing','scope_basis':x['scope_basis']})
  if okay:statuses['pending_review_or_verdict_missing']+=1
 failures=[r for r in rows if not r.get('verified')]
 out={'checked_at':now(),'complete':not failures and len(rows)==EXPECTED,'number':NUMBER,'certificate_id':CERT_ID,'target_cards':len(rows),'verified_target_cards':len(rows)-len(failures),'status_counts':dict(statuses),'failures':failures,'cards':rows,'wb_review_left_pending':True,'manual_wb_review_action_taken':False,'local_file_deleted':False}
 save(READBACK,out)
 state.update(phase='verified_complete' if not failures else 'readback_incomplete',verified_target_cards=len(rows)-len(failures),status_counts=dict(statuses),failures=failures,readback_path=str(READBACK),updated_at=now());save(STATE,state)
 print(json.dumps({'phase':state['phase'],'verified_target_cards':out['verified_target_cards'],'status_counts':dict(statuses),'failures':failures,'wb_review_left_pending':True,'generic_offer_scope_basis':g['offer_id']},ensure_ascii=False,indent=2))
 if failures:raise RuntimeError('wb_readback_incomplete')
if __name__=='__main__':main()
