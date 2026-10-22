from __future__ import annotations
import collections,datetime,hashlib,json,sys,time
from pathlib import Path
BASE=Path(__file__).resolve().parent; ROOT=BASE.parents[1]
sys.path.insert(0,str(BASE))
from api_client import Client,now,save
PRE=BASE/'iek_36648_extra_pack_preflight_20261013.json'
OUT='iek_36648_extra_pack_execute_20261013.json'
NUMBER='ЕАЭС N RU Д-CN.РА07.В.36648/26'; CERT_ID=5453798
ISSUE='2026-08-19'; EXPIRY='2027-10-05'; WB_TYPE=2
DOC_FIELDS=('id','type','number','productNumber','tradeName','applicant','startDate','endDate','isEndless')
CARD_FIELDS=('nmID','vendorCode','brand','title','description','dimensions','characteristics','sizes','kizMarked')
MAP=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(v): return ''.join(c for c in str(v or '').upper().translate(MAP) if c.isalnum())
def read(path): return json.loads(path.read_text())
def copy_docs(card): return [{k:x[k] for k in DOC_FIELDS if k in x} for x in ((card.get('documents') or {}).get('items') or [])]
def stable_fields(card): return {k:card.get(k) for k in CARD_FIELDS if k in card}
if (BASE/OUT).exists(): raise RuntimeError('execution marker exists; live reconcile before any further mutation')
pre=read(PRE)
targets=pre['targets']
if len(targets)!=8 or pre.get('problems') or any(x.get('wb_document_state')!='missing' or x.get('ozon_binding') for x in targets): raise RuntimeError('preflight is no longer a clean exact set of 8 missing targets')
expected={x['offer']:{'product_id':str(x['product_id']),'sku':str(x['sku']),'nmID':str(x['wb_nmID'])} for x in targets}
if len(expected)!=8 or len({x['sku'] for x in targets})!=8 or len({x['wb_nmID'] for x in targets})!=8: raise RuntimeError('duplicate offer/SKU/nmID in target set')
client=Client()
# Fresh Ozon certificate metadata, products, codes and bindings immediately before write.
info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
if str(info.get('certificate_id'))!=str(CERT_ID) or info.get('status_code')!='approved' or info.get('type_code')!='declaration' or str(info.get('accordance_type_code') or '').upper()!='EAEU': raise RuntimeError('Ozon certificate record changed or is not approved EAEU')
if str(info.get('issue_date',''))[:10]!=ISSUE or str(info.get('expire_date',''))[:10]!=EXPIRY: raise RuntimeError('Ozon certificate dates changed')
items=client.call('ozon','/v3/product/info/list',{'offer_id':sorted(expected)}).get('items')
if not isinstance(items,list) or len(items)!=8: raise RuntimeError('fresh Ozon product list incomplete')
by_offer={str(x.get('offer_id')):x for x in items}
if set(by_offer)!=set(expected): raise RuntimeError('fresh Ozon offers mismatch')
for offer,e in expected.items():
 p=by_offer[offer]
 if {'product_id':str(p.get('product_id') or p.get('id') or ''),'sku':str(p.get('sku') or '')} != {'product_id':e['product_id'],'sku':e['sku']} or p.get('is_archived') is True: raise RuntimeError('Ozon identity/active state changed '+offer)
 body=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':[offer]},'limit':1})
 aitems=body.get('result') or body.get('items')
 if not isinstance(aitems,list) or len(aitems)!=1 or str(aitems[0].get('offer_id'))!=offer: raise RuntimeError('fresh attributes incomplete '+offer)
 ids={str(a.get('id')):a for a in aitems[0].get('attributes') or []}
 brand=[str(v.get('value') or '') for v in (ids.get('85') or {}).get('values') or []]
 tnved={str(v.get('value') or '').split(' - ',1)[0].strip() for v in (ids.get('22232') or {}).get('values') or [] if str(v.get('value') or '').strip()}
 if brand!=['IEK'] or not tnved or not tnved.issubset({'8539520002','8539520009'}): raise RuntimeError('fresh Ozon brand/TNVED outside FSA scope '+offer)
# Read existing binding set and reject duplicate or conflicting pairs; add only these missing SKUs.
before=client.ozon_bindings(CERT_ID)
by_sku=collections.defaultdict(list)
for x in before: by_sku[str(x.get('sku') or '')].append(x)
missing=[]
for offer,e in expected.items():
 group=by_sku.get(e['sku'],[])
 if len(group)>1: raise RuntimeError('duplicate current Ozon SKU binding '+offer)
 if group:
  if str(group[0].get('product_id'))!=e['product_id']: raise RuntimeError('existing Ozon binding product mismatch '+offer)
  raise RuntimeError('target SKU already appears in live binding set; reconcile without rebinding '+offer)
 missing.append(e['sku'])
if len(missing)!=8: raise RuntimeError('unexpected missing SKU count')

# Refresh exact WB cards, build complete-preserving updates only where the document is still absent.
wb_before={}; payloads=[]; before_documents={}; before_fields={}
for offer,e in expected.items():
 cards=client.wb_cards(offer)
 if len(cards)!=1: raise RuntimeError('fresh WB exact card missing/ambiguous '+offer)
 card=cards[0]
 if str(card.get('vendorCode'))!=offer or str(card.get('nmID'))!=e['nmID']: raise RuntimeError('fresh WB identity mismatch '+offer)
 if str(card.get('brand') or '').strip().casefold() not in ('iek','iek holding'): raise RuntimeError('fresh WB brand mismatch '+offer)
 tnv=[x for x in card.get('characteristics') or [] if int(x.get('id') or -1)==15000001]
 if len(tnv)>1: raise RuntimeError('duplicate WB TNVED attributes '+offer)
 wbcodes={str(v).strip().split(' ',1)[0] for v in ((tnv[0].get('value') or []) if tnv else []) if str(v).strip()}
 if wbcodes and not wbcodes.issubset({'8539520002','8539520009'}): raise RuntimeError('fresh WB TNVED outside FSA scope '+offer)
 docs=card.get('documents') or {}; existing=copy_docs(card)
 same=[x for x in existing if norm(x.get('number'))==norm(NUMBER)]
 if same:
  raise RuntimeError('WB target document appeared after preflight; reconcile before changing '+offer)
 before_documents[offer]=existing; before_fields[offer]=stable_fields(card); wb_before[offer]=card
 addition={'type':WB_TYPE,'number':NUMBER,'startDate':ISSUE,'endDate':EXPIRY,'isEndless':False}
 payload={k:card[k] for k in CARD_FIELDS if k in card}
 payload['documents']={'items':existing+[addition],'excludeDocuments':False}
 payloads.append(payload)
bytes_count=len(json.dumps(payloads,ensure_ascii=False,separators=(',',':')).encode())
if len(payloads)!=8 or bytes_count>10_000_000: raise RuntimeError('WB update chunk outside safe request limits')

state={'started_at_utc':now(),'phase':'prepared','certificate_id':CERT_ID,'number':NUMBER,'fsa_url':pre['fsa_url'],'targets':[{'offer':k,**v} for k,v in expected.items()],'ozon_bindings_before':len(before),'ozon_bindings_before_status_counts':dict(collections.Counter(str(x.get('product_status_code')) for x in before)),'ozon_bind_skus':missing,'wb_cards_before':len(wb_before),'wb_update_bytes':bytes_count,'wb_update_cards':len(payloads),'wb_update_attempted':False,'wb_readback':None}
save(OUT,state)
# Ozon mutation: exactly one no-retry API call, then independent binding readback.
state['phase']='ozon_bind_prepared'; state['ozon_bind_attempted']=True; save(OUT,state)
try:
 response=client.call('ozon','/v1/product/certificate/bind',{'certificate_id':CERT_ID,'skus':missing},mutation=True)
 state['ozon_bind_response']=response; state['phase']='ozon_bind_response_received'
except RuntimeError as exc:
 state['ozon_bind_error']=str(exc); state['phase']='ozon_bind_uncertain_reconcile'; save(OUT,state)
 # Do not retry. A single live read determines whether the request took effect.
after_bind=client.ozon_bindings(CERT_ID)
after_by=collections.defaultdict(list)
for x in after_bind: after_by[str(x.get('sku') or '')].append(x)
bind_results=[]
for offer,e in expected.items():
 group=after_by.get(e['sku'],[])
 bind_results.append({'offer':offer,'product_id':e['product_id'],'sku':e['sku'],'binding_count':len(group),'binding':group[0] if len(group)==1 else None,'status':group[0].get('product_status_code') if len(group)==1 else 'missing_or_duplicate'})
if any(x['binding_count']!=1 or str(x['binding'].get('product_id'))!=x['product_id'] for x in bind_results):
 state['phase']='ozon_binding_readback_incomplete'; state['ozon_bindings_after']=bind_results; save(OUT,state)
 raise RuntimeError('Ozon binding readback incomplete; no WB write sent and no bind retry')
state['ozon_bindings_after']=bind_results; state['ozon_bindings_after_status_counts']=dict(collections.Counter(str(x['status']) for x in bind_results)); state['phase']='ozon_bindings_visible'; save(OUT,state)

# WB mutation: add only missing exact metadata rows, preserving the full current card fields and prior document rows.
state['phase']='wb_update_prepared'; state['wb_update_attempted']=True; save(OUT,state)
try:
 response=client.call('wb','/content/v2/cards/update',payloads,mutation=True)
 state['wb_update_response']=response
 if response.get('error') is not False:
  state['phase']='wb_update_response_error_reconcile'; save(OUT,state)
  raise RuntimeError('WB update response not accepted; live reconciliation required before retry')
 state['phase']='wb_update_accepted_readback_pending'; save(OUT,state)
except RuntimeError as exc:
 if state.get('phase')!='wb_update_response_error_reconcile':
  state['wb_update_error']=str(exc); state['phase']='wb_update_uncertain_reconcile'; save(OUT,state)
 # No retry; continue with exact live reads.

# Immediate live WB readback; if delayed, do not resend, poll the same exact cards.
wb_after={}
for attempt in range(4):
 wb_after={}
 for offer,e in expected.items():
  cards=client.wb_cards(offer)
  if len(cards)==1 and str(cards[0].get('vendorCode'))==offer and str(cards[0].get('nmID'))==e['nmID']:
   wb_after[offer]=cards[0]
 if len(wb_after)==8 and all(any(norm(x.get('number'))==norm(NUMBER) and int(x.get('type') or -1)==WB_TYPE and str(x.get('startDate') or '')[:10]==ISSUE and str(x.get('endDate') or '')[:10]==EXPIRY for x in (wb_after[o].get('documents') or {}).get('items') or []) for o in expected):
  break
 if attempt<3: time.sleep(8)

wb_results=[]
for offer,e in expected.items():
 card=wb_after.get(offer)
 if not card:
  wb_results.append({'offer':offer,'nmID':e['nmID'],'state':'card_missing_on_readback'}); continue
 items=[x for x in (card.get('documents') or {}).get('items') or [] if norm(x.get('number'))==norm(NUMBER)]
 if len(items)!=1: wb_results.append({'offer':offer,'nmID':e['nmID'],'state':'document_missing_or_duplicate','count':len(items)}); continue
 doc=items[0]
 if int(doc.get('type') or -1)!=WB_TYPE or (str(doc.get('startDate') or '')[:10],str(doc.get('endDate') or '')[:10])!=(ISSUE,EXPIRY):
  wb_results.append({'offer':offer,'nmID':e['nmID'],'state':'document_metadata_conflict','document':doc}); continue
 verdict=doc.get('verdict') or {}
 status='approved' if verdict.get('verified') is True and verdict.get('status')==1 and verdict.get('reason')=='valid' else 'pending_or_unverified'
 current_docs=copy_docs(card)
 before_docs=before_documents[offer]
 oldkeys={(int(d.get('type') or 0),norm(d.get('number')),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10]) for d in before_docs}
 newkeys={(int(d.get('type') or 0),norm(d.get('number')),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10]) for d in current_docs}
 old_preserved=oldkeys.issubset(newkeys)
 fields_preserved=stable_fields(card)==before_fields[offer]
 wb_results.append({'offer':offer,'nmID':e['nmID'],'state':status,'document':doc,'overallVerdict':(card.get('documents') or {}).get('overallVerdict'),'excludeDocuments':(card.get('documents') or {}).get('excludeDocuments'),'old_documents_preserved':old_preserved,'card_fields_preserved':fields_preserved})
state['wb_readback']={'checked_at_utc':now(),'card_count':len(wb_after),'results':wb_results,'state_counts':dict(collections.Counter(x['state'] for x in wb_results)),'all_rows_visible':len(wb_results)==8 and all(x['state'] in ('approved','pending_or_unverified') for x in wb_results),'all_prior_docs_preserved':all(x.get('old_documents_preserved') for x in wb_results if x['state'] in ('approved','pending_or_unverified')),'all_card_fields_preserved':all(x.get('card_fields_preserved') for x in wb_results if x['state'] in ('approved','pending_or_unverified'))}
state['finished_at_utc']=now(); state['phase']='readback_complete' if state['wb_readback']['all_rows_visible'] else 'readback_incomplete'; save(OUT,state)
print(json.dumps({k:state[k] for k in ('phase','ozon_bindings_after_status_counts','wb_readback')},ensure_ascii=False,indent=2))
