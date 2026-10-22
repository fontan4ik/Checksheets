from __future__ import annotations
import collections,hashlib,json,sys,time
from pathlib import Path
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
from api_client import Client,now,save
PRE=json.loads((BASE/'iek_36648_extra_pack_preflight_20261013.json').read_text())
EXEC=json.loads((BASE/'iek_36648_extra_pack_execute_20261013.json').read_text())
OUT='iek_36648_extra_pack_wb_retry_20261013.json'
NUMBER='ЕАЭС N RU Д-CN.РА07.В.36648/26'; CERT_ID=5453798
ISSUE='2026-08-19'; EXPIRY='2027-10-05'; WB_TYPE=2
DATE_ISO=ISSUE+'T00:00:00Z'; EXPIRY_ISO=EXPIRY+'T00:00:00Z'
DOC_FIELDS=('id','type','number','productNumber','tradeName','applicant','startDate','endDate','isEndless')
CARD_FIELDS=('nmID','vendorCode','brand','title','description','dimensions','characteristics','sizes','kizMarked','gtin')
MAP=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(v):return ''.join(c for c in str(v or '').upper().translate(MAP) if c.isalnum())
def clean_doc(d):
 unknown=set(d)-set(DOC_FIELDS)-{'verdict','createdAt','updatedAt'}
 if unknown: raise RuntimeError('unknown existing WB document fields: '+str(sorted(unknown)))
 return {k:d[k] for k in DOC_FIELDS if k in d}
def clone_docs(card):return [clean_doc(x) for x in ((card.get('documents') or {}).get('items') or [])]
def savej(value): save(OUT,value)
if (BASE/OUT).exists(): raise RuntimeError('WB retry journal exists; read it and reconcile before another write')
expected={x['offer']:{'product_id':str(x['product_id']),'sku':str(x['sku']),'nmID':str(x['wb_nmID'])} for x in PRE['targets']}
if len(expected)!=8:raise RuntimeError('preflight target set mismatch')
client=Client()
# Confirm the prior successful Ozon binding call resulted in all eight exact product/SKU relations.
current=client.ozon_bindings(CERT_ID); by_sku=collections.defaultdict(list)
for b in current:by_sku[str(b.get('sku') or '')].append(b)
ozon_rows=[]
for offer,e in expected.items():
 group=by_sku.get(e['sku'],[])
 if len(group)!=1 or str(group[0].get('product_id'))!=e['product_id']:raise RuntimeError('Ozon relation missing/duplicate/mismatched; no WB retry for '+offer)
 ozon_rows.append({'offer':offer,'product_id':e['product_id'],'sku':e['sku'],'status':group[0].get('product_status_code')})

payloads=[]; before={}; docs_before={}; issues=[]
for offer,e in expected.items():
 cards=client.wb_cards(offer)
 if len(cards)!=1 or str(cards[0].get('vendorCode'))!=offer or str(cards[0].get('nmID'))!=e['nmID']:
  raise RuntimeError('WB exact card changed/missing for '+offer)
 card=cards[0]
 if str(card.get('brand') or '').strip().casefold() not in ('iek','iek holding'):raise RuntimeError('WB brand changed for '+offer)
 tnv=[x for x in card.get('characteristics') or [] if int(x.get('id') or -1)==15000001]
 codes={str(v).strip().split(' ',1)[0] for v in ((tnv[0].get('value') or []) if len(tnv)==1 else []) if str(v).strip()} if tnv else set()
 if len(tnv)>1 or (codes and not codes.issubset({'8539520002','8539520009'})):raise RuntimeError('WB TNVED outside FSA scope for '+offer)
 docs=card.get('documents') or {}; existing=clone_docs(card)
 same=[d for d in existing if norm(d.get('number'))==norm(NUMBER)]
 if len(same)>1:raise RuntimeError('duplicate WB document rows for '+offer)
 if same:
  d=same[0]
  if int(d.get('type') or -1)!=WB_TYPE or (str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10])!=(ISSUE,EXPIRY):raise RuntimeError('conflicting WB document appeared for '+offer)
  issues.append({'offer':offer,'state':'already_present','document':d}); continue
 required=[k for k in CARD_FIELDS[:-1] if k not in card]
 if required:raise RuntimeError('WB full card response omitted required fields for '+offer+': '+str(required))
 new_doc={'type':WB_TYPE,'number':NUMBER,'startDate':DATE_ISO,'endDate':EXPIRY_ISO,'isEndless':False}
 payload={k:card[k] for k in CARD_FIELDS if k in card}
 payload['documents']={'items':existing+[new_doc],'excludeDocuments':False}
 for k in CARD_FIELDS:
  if k in card and payload.get(k)!=card.get(k):raise RuntimeError('non-document card field changed in prepared payload')
 payloads.append(payload);before[offer]=card;docs_before[offer]=existing
if not payloads:raise RuntimeError('all eight WB documents appeared; no mutation needed')
encoded=json.dumps(payloads,ensure_ascii=False,separators=(',',':')).encode()
if len(payloads)>3000 or len(encoded)>10_000_000:raise RuntimeError('WB request exceeds documented batch limits')
state={'started_at_utc':now(),'phase':'prepared','number':NUMBER,'targets':[{'offer':k,**v} for k,v in expected.items()],'ozon_binding_readback':ozon_rows,'ozon_status_counts':dict(collections.Counter(x['status'] for x in ozon_rows)),'wb_targets_to_update':len(payloads),'wb_already_present':issues,'payload_sha256':hashlib.sha256(encoded).hexdigest(),'payload_bytes':len(encoded),'date_fields_iso8601':{'startDate':DATE_ISO,'endDate':EXPIRY_ISO},'response':None,'readback':None}
savej(state)
state['phase']='mutation_started';state['mutation_attempts']=1;savej(state)
try:
 response=client.call('wb','/content/v2/cards/update',payloads,mutation=True)
except RuntimeError as exc:
 state['phase']='mutation_error_readback_required';state['error']=str(exc);savej(state)
 raise
state['response']=response
if response.get('error') is not False:
 state['phase']='response_error_readback_required';savej(state)
 raise RuntimeError('WB rejected update; reconcile before any retry')
state['phase']='accepted_waiting_for_wb_sync';savej(state)
# Immediate exact-card readback, polling the same submitted batch without resending.
wb_after={}
for attempt in range(4):
 wb_after={}
 for offer,e in expected.items():
  c=client.wb_cards(offer)
  if len(c)==1 and str(c[0].get('vendorCode'))==offer and str(c[0].get('nmID'))==e['nmID']:wb_after[offer]=c[0]
 visible=True
 for offer,card in wb_after.items():
  matches=[d for d in (card.get('documents') or {}).get('items') or [] if norm(d.get('number'))==norm(NUMBER) and int(d.get('type') or -1)==WB_TYPE and str(d.get('startDate') or '')[:10]==ISSUE and str(d.get('endDate') or '')[:10]==EXPIRY]
  if len(matches)!=1:visible=False
 if visible and len(wb_after)==8:break
 if attempt<3:time.sleep(8)
rows=[]
for offer,e in expected.items():
 card=wb_after.get(offer)
 if not card:rows.append({'offer':offer,'state':'exact_card_not_readable'});continue
 matches=[d for d in (card.get('documents') or {}).get('items') or [] if norm(d.get('number'))==norm(NUMBER)]
 if len(matches)!=1:rows.append({'offer':offer,'state':'document_missing_or_duplicate','count':len(matches)});continue
 doc=matches[0]; v=doc.get('verdict') or {}
 state_name='approved' if v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' else 'pending_or_unverified'
 same_fields=all(card.get(k)==before[offer].get(k) for k in CARD_FIELDS if k in before[offer]) if offer in before else True
 old_docs=clone_docs(card); old_keys={(int(x.get('type') or 0),norm(x.get('number')),str(x.get('startDate') or '')[:10],str(x.get('endDate') or '')[:10]) for x in old_docs}
 old_keys.discard((WB_TYPE,norm(NUMBER),ISSUE,EXPIRY))
 now_keys={(int(x.get('type') or 0),norm(x.get('number')),str(x.get('startDate') or '')[:10],str(x.get('endDate') or '')[:10]) for x in old_docs}
 # For cards previously present after preflight, only compare old rows for cards we submitted.
 old_preserved=True
 if offer in docs_before:old_preserved=old_keys.issubset(now_keys)
 rows.append({'offer':offer,'nmID':e['nmID'],'state':state_name,'document':doc,'overallVerdict':(card.get('documents') or {}).get('overallVerdict'),'excludeDocuments':(card.get('documents') or {}).get('excludeDocuments'),'card_fields_preserved':same_fields,'preexisting_docs_preserved':old_preserved})
state['readback']={'checked_at_utc':now(),'card_count':len(wb_after),'rows':rows,'state_counts':dict(collections.Counter(x['state'] for x in rows)),'all_rows_visible':len(rows)==8 and all(x['state'] in ('approved','pending_or_unverified') for x in rows),'all_card_fields_preserved':all(x.get('card_fields_preserved') for x in rows),'all_preexisting_docs_preserved':all(x.get('preexisting_docs_preserved') for x in rows)}
state['phase']='readback_complete' if state['readback']['all_rows_visible'] else 'accepted_readback_pending';state['finished_at_utc']=now();savej(state)
print(json.dumps({'phase':state['phase'],'response':state['response'],'ozon_status_counts':state['ozon_status_counts'],'readback':state['readback']},ensure_ascii=False,indent=2))
