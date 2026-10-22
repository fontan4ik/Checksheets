#!/usr/bin/env python3
"""Bind two already-approved Navigator documents to 97 exactly verified Ozon products.
WB cards already carry both exact documents with current valid verdicts; no WB writes.
"""
from __future__ import annotations
import csv, datetime, hashlib, json, sys
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PILOT=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(PILOT))
from api_client import Client, now

SNAP=HERE/'live_marketplaces_snapshot_reconciled_20261022.json'
EDGES=HERE/'all_confirmed_source_assignments_live_reconciled_20261022.csv'
PREFLIGHT=HERE/'navigator_93812_binding_preflight_20261022.json'
STATE=HERE/'navigator_93812_binding_execution_20261022.json'
JOURNAL=HERE/'navigator_93812_binding_mutation_journal_20261022.jsonl'
DOCS={
 'ЕАЭС N RU Д-CN.РА11.В.08110/24': {'type':'declaration','issue':'2024-12-02','expiry':'2029-12-01','certificate_id':5945402},
 'ЕАЭС RU С-CN.НВ54.В.06643/24': {'type':'certificate_of_conformity','issue':'2024-12-04','expiry':'2029-12-03','certificate_id':5945406},
}
TRANSLATE=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(value):
 s=str(value or '').strip().upper()
 for prefix in ('ЕАЭС','EAEU','EAEC','EAC'):
  if s.startswith(prefix): s=s[len(prefix):].strip(); break
 if s.startswith(('N','№')): s=s[1:].strip()
 return ''.join(c for c in s.translate(TRANSLATE) if c.isalnum())
def attrs_values(row):
 out={}
 for a in row.get('attributes') or []:
  vals=[str(v.get('value') or '').strip() for v in a.get('values') or []]
  out[str(a.get('id'))]=[v for v in vals if v]
 return out
def wb_codes(card):
 out=set()
 for c in card.get('characteristics') or []:
  label=''.join(str(c.get('name') or '').casefold().split()).replace('ё','е')
  if 'тнвэд' in label or 'тнвед' in label:
   vals=c.get('value') or []
   vals=vals if isinstance(vals,list) else [vals]
   out|={str(v).split(' - ',1)[0].strip() for v in vals if str(v).strip()}
 return out
def wb_exact_valid(card,number,typ,issue,expiry):
 expected_type=1 if typ=='certificate_of_conformity' else 2
 matches=[d for d in ((card.get('documents') or {}).get('items') or []) if norm(d.get('number'))==norm(number)]
 exact=[d for d in matches if int(d.get('type') or 0)==expected_type and str(d.get('startDate') or '')[:10]==issue and str(d.get('endDate') or '')[:10]==expiry]
 return len(exact)==1 and (exact[0].get('verdict') or {}).get('verified') is True and (exact[0].get('verdict') or {}).get('status')==1 and (exact[0].get('verdict') or {}).get('reason')=='valid'
def save(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)

client=Client()
snapshot=json.loads(SNAP.read_text())
products_expected={}
with EDGES.open(encoding='utf-8-sig',newline='') as stream:
 edge_rows=list(csv.DictReader(stream))
for number,spec in DOCS.items():
 offers={r['offer_id'] for r in edge_rows if r.get('number')==number and r.get('brand')=='Navigator' and r.get('ozon_state')=='missing_binding' and r.get('wb_state')=='valid'}
 products_expected[number]=offers
intersection=set.intersection(*(products_expected[n] for n in DOCS))
if len(intersection)!=97 or any(len(products_expected[n])!=97 for n in DOCS):
 raise RuntimeError(f'candidate_set_changed:{ {k:len(v) for k,v in products_expected.items()} }')
target_offers=sorted(intersection)
# Fresh Ozon product and attribute reads, in batches.
product_rows=[]; attr_rows=[]
for start in range(0,len(target_offers),100):
 batch=target_offers[start:start+100]
 product_rows.extend(client.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or [])
 body=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)})
 result=body.get('result') or []
 if isinstance(result,dict): result=result.get('items') or []
 attr_rows.extend(result)
by_offer=defaultdict(list);attrs_by_offer=defaultdict(list)
for p in product_rows: by_offer[str(p.get('offer_id') or '')].append(p)
for a in attr_rows: attrs_by_offer[str(a.get('offer_id') or '')].append(a)
if set(by_offer)!=set(target_offers) or any(len(by_offer[o])!=1 for o in target_offers): raise RuntimeError('ozon_product_identity_not_unique')
if set(attrs_by_offer)!=set(target_offers) or any(len(attrs_by_offer[o])!=1 for o in target_offers): raise RuntimeError('ozon_attributes_not_unique')
products={}; expected_tnved='8539213009'
for offer in target_offers:
 p=by_offer[offer][0];a=attrs_values(attrs_by_offer[offer][0])
 brands=a.get('85',[])
 tnved={str(v).split(' - ',1)[0].strip() for v in a.get('22232',[])}
 product_id=str(p.get('id') or p.get('product_id') or '')
 sku=str(p.get('sku') or '')
 old=next((x for x in snapshot['ozon_products']['products'] if str(x.get('offer_id'))==offer),None)
 if (not product_id or not sku or p.get('is_archived') is not False or brands!=['Navigator'] or tnved!={expected_tnved}
     or not old or product_id!=str(old.get('product_id')) or sku!=str(old.get('sku'))):
  raise RuntimeError('fresh_ozon_identity_brand_or_tnved_conflict:'+offer)
 products[offer]={'offer_id':offer,'product_id':product_id,'sku':sku,'brand':brands[0],'tnved':sorted(tnved)}
# Verify target WB cards in the complete, reconciled live catalog. No card will be written.
wb_by_offer=defaultdict(list)
for card in snapshot['wb_catalog']['cards']: wb_by_offer[str(card.get('vendorCode') or '')].append(card)
for offer in target_offers:
 cards=wb_by_offer.get(offer,[])
 if len(cards)!=1 or str(cards[0].get('brand') or '').casefold()!='navigator' or wb_codes(cards[0])!={expected_tnved}:
  raise RuntimeError('wb_identity_brand_or_tnved_conflict:'+offer)
 for number,spec in DOCS.items():
  if not wb_exact_valid(cards[0],number,spec['type'],spec['issue'],spec['expiry']): raise RuntimeError('wb_document_not_currently_valid:'+offer+':'+number)
# Fresh Ozon certificate metadata and binding readback before writes.
records=[]
for page in range(1,101):
 result=(client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {})
 batch=result.get('certificates')
 if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_incomplete')
 records.extend(batch)
 if not batch or page>=int(result.get('page_count') or 0): break
else: raise RuntimeError('ozon_certificate_page_limit')
record_by_number={}
for number,spec in DOCS.items():
 matches=[c for c in records if norm(c.get('certificate_number'))==norm(number) and c.get('type_code')==spec['type']]
 if len(matches)!=1: raise RuntimeError('ozon_exact_record_not_unique:'+number)
 c=matches[0]
 if (str(c.get('certificate_id'))!=str(spec['certificate_id']) or c.get('status_code')!='approved'
     or str(c.get('issue_date') or '')[:10]!=spec['issue'] or str(c.get('expire_date') or '')[:10]!=spec['expiry']
     or c.get('accordance_type_code')!='EAEU'):
  raise RuntimeError('ozon_record_not_exact_approved_current:'+number)
 record_by_number[number]=c
bindings_by_doc={}
for number,spec in DOCS.items():
 bindings=client.ozon_bindings(spec['certificate_id'])
 bypid=defaultdict(list)
 for b in bindings: bypid[str(b.get('product_id') or '')].append(b)
 missing=[]
 for offer in target_offers:
  p=products[offer]; existing=bypid.get(p['product_id'],[])
  if len(existing)>1: raise RuntimeError('duplicate_existing_binding:'+offer+':'+number)
  if existing:
   b=existing[0]
   if str(b.get('sku') or '')!=p['sku'] or b.get('product_status_code')=='declined': raise RuntimeError('existing_binding_conflict:'+offer+':'+number)
  else: missing.append(offer)
 bindings_by_doc[number]={'bindings_before':len(bindings),'missing_offers':missing,'binding_rows':bindings}
 if len(missing)!=97: raise RuntimeError(f'fresh_missing_link_count_changed:{number}:{len(missing)}')
# Recheck coverage from the fresh snapshot to ensure these products have no other current approved document.
by_sku={str(p.get('sku') or ''):p for p in snapshot['ozon_products']['products']}
covered=set()
today=datetime.date.today().isoformat()
for c in snapshot['ozon_certificates']['certificates']:
 if c.get('status_code')!='approved' or str(c.get('issue_date') or '')[:10]>today or str(c.get('expire_date') or '')[:10]<today: continue
 for b in c.get('live_bindings') or []:
  p=by_sku.get(str(b.get('sku') or ''))
  if b.get('product_status_code')=='approved' and p and str(p.get('product_id'))==str(b.get('product_id')): covered.add(str(p.get('product_id')))
if any(products[o]['product_id'] in covered for o in target_offers): raise RuntimeError('target_already_has_other_current_approved_document')
preflight={'checked_at_utc':now(),'read_only_preflight_passed':True,'document_count':len(DOCS),'target_offer_count':len(target_offers),'target_product_count':len(products),'target_tnved':expected_tnved,'wb_exact_valid_both_documents':len(target_offers),'ozon_exact_records':{n:{'certificate_id':str(record_by_number[n]['certificate_id']),'status':record_by_number[n]['status_code'],'bindings_before':bindings_by_doc[n]['bindings_before'],'missing_target_links':len(bindings_by_doc[n]['missing_offers'])} for n in DOCS},'local_write_or_delete':False}
save(PREFLIGHT,preflight)
print(json.dumps({'phase':'preflight_passed','target_products':len(target_offers),'documents':{n:{'id':str(record_by_number[n]['certificate_id']),'missing':len(bindings_by_doc[n]['missing_offers'])} for n in DOCS},'wb_valid_both_docs':len(target_offers)},ensure_ascii=False),flush=True)
state={'started_at_utc':now(),'phase':'mutating','target_offers':target_offers,'target_product_count':len(products),'mutations':[],'wb_writes':0,'local_files_deleted':False}
save(STATE,state)
for number,spec in DOCS.items():
 cid=int(spec['certificate_id']); target=[products[o] for o in target_offers]
 payload={'certificate_id':cid,'skus':[p['sku'] for p in target]}
 payload_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 prepared={'at_utc':now(),'platform':'ozon','endpoint':'/v1/product/certificate/bind','number':number,'certificate_id':cid,'sku_count':len(payload['skus']),'request_sha256':payload_hash,'phase':'prepared'}
 with JOURNAL.open('a',encoding='utf-8') as stream:stream.write(json.dumps(prepared,ensure_ascii=False)+'\n');stream.flush()
 state['mutations'].append(prepared);save(STATE,state)
 try:
  response=client.call('ozon','/v1/product/certificate/bind',payload,mutation=True)
  if response.get('result') is not True: raise RuntimeError('bind_response_not_true')
  done={**prepared,'phase':'response','response':response,'finished_at_utc':now()}
  with JOURNAL.open('a',encoding='utf-8') as stream:stream.write(json.dumps(done,ensure_ascii=False)+'\n');stream.flush()
  state['mutations'][-1]=done;save(STATE,state)
 except Exception as exc:
  failed={**prepared,'phase':'uncertain_or_failed','error_type':type(exc).__name__,'finished_at_utc':now()}
  with JOURNAL.open('a',encoding='utf-8') as stream:stream.write(json.dumps(failed,ensure_ascii=False)+'\n');stream.flush()
  state['mutations'][-1]=failed;state['phase']='stop_and_reconcile';save(STATE,state)
  print(json.dumps({'phase':'stopped_for_reconciliation','number':number,'error_type':type(exc).__name__},ensure_ascii=False),flush=True)
  raise
 # Read back the exact record before advancing to the next document.
 current=client.ozon_bindings(cid);byid=defaultdict(list)
 for b in current:byid[str(b.get('product_id') or '')].append(b)
 outcomes=[]
 for offer in target_offers:
  rows=byid.get(products[offer]['product_id'],[])
  if len(rows)!=1 or str(rows[0].get('sku') or '')!=products[offer]['sku']:
   raise RuntimeError('postwrite_binding_missing_or_ambiguous:'+offer+':'+number)
  outcomes.append(str(rows[0].get('product_status_code') or 'unknown'))
 counts={status:outcomes.count(status) for status in sorted(set(outcomes))}
 state['mutations'][-1]['readback_status_counts']=counts
 state['mutations'][-1]['readback_bindings']=len(outcomes)
 save(STATE,state)
 if any(status not in ('approved','awaiting_verification','pending','background_check') for status in outcomes):
  state['phase']='binding_status_requires_review';save(STATE,state)
  raise RuntimeError('postwrite_binding_status_requires_review:'+number+':'+str(counts))
 print(json.dumps({'phase':'readback','number':number,'certificate_id':cid,'bindings':len(outcomes),'status_counts':counts},ensure_ascii=False),flush=True)

state['finished_at_utc']=now()
all_statuses=[status for mutation in state['mutations'] for status,count in mutation.get('readback_status_counts',{}).items() for _ in range(count)]
state['phase']='complete_approved' if len(all_statuses)==len(DOCS)*len(target_offers) and set(all_statuses)=={'approved'} else 'bound_waiting_for_ozon_review'
state['readback_status_counts']={status:all_statuses.count(status) for status in sorted(set(all_statuses))}
state['wb_review_left_as_existing_valid']=True
save(STATE,state)
print(json.dumps({'phase':state['phase'],'total_document_product_links':len(all_statuses),'status_counts':state['readback_status_counts'],'local_files_deleted':False},ensure_ascii=False),flush=True)
