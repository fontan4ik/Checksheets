#!/usr/bin/env python3
"""Add FSA declaration 58098/25 to exact Feron EK WB cards, preserving other data.

Ozon is deliberately excluded: its live TN VED differs from the FSA scope.
This runner never deletes the source PDF.
"""
from __future__ import annotations
import argparse, collections, copy, json, pathlib, sys

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS, UPDATE_CARD_FIELDS, comparable_card, doc_key, norm_number

PREFLIGHT=HERE/'feron_58098_crossplatform_preflight_live_20261021.json'
STATE=HERE/'feron_58098_wb_execution_20261021.json'
READBACK=HERE/'feron_58098_wb_readback_20261021.json'
NUMBER='ЕАЭС N RU Д-CN.РА06.В.58098/25'
WB_NUMBER='ЕАЭС N RU Д-CN.PA06.B.58098/25'
ISSUE='2025-08-01'; EXPIRY='2030-07-31'
ALLOWED={
 '41326-1':('EK50',),
 '41327-1':('EK40',),
 '48990-1':('EK100',),
 '51661-1':('EK51',),
}

def atomic(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp')
 tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 tmp.replace(path)

def docs(card): return list((card.get('documents') or {}).get('items') or [])
def projected(card): return [{k:d[k] for k in DOC_FIELDS if k in d} for d in docs(card)]
def existing_signature(card): return [doc_key(d) for d in projected(card)]
def wanted_doc(): return {'type':2,'number':WB_NUMBER,'startDate':ISSUE+'T00:00:00Z','endDate':EXPIRY+'T00:00:00Z','isEndless':False}
def merge(card,wanted):
 current=projected(card)
 same=[d for d in current if doc_key(d)==doc_key(wanted)]
 if same:
  if len(same)!=1 or (str(same[0].get('startDate',''))[:10],str(same[0].get('endDate',''))[:10],same[0].get('isEndless'))!=(ISSUE,EXPIRY,False):
   raise RuntimeError('existing_WB_document_metadata_conflict')
  return None
 payload={k:copy.deepcopy(card[k]) for k in UPDATE_CARD_FIELDS if k in card}
 payload['documents']={'items':current+[wanted],'excludeDocuments':False}
 return payload

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--execute',action='store_true'); args=ap.parse_args()
 if STATE.exists() or READBACK.exists(): raise RuntimeError('execution_artifact_exists; inspect live state before rerun')
 pre=json.loads(PREFLIGHT.read_text(encoding='utf-8'))
 if not pre.get('read_only') or pre.get('declaration',{}).get('number')!=NUMBER: raise RuntimeError('preflight_identity_mismatch')
 offers=sorted(ALLOWED)
 client=Client(); before={}; writes=[]; prior={}; rows=[]
 target_doc=wanted_doc()
 for offer in offers:
  cards=client.wb_cards(offer)
  if len(cards)!=1: raise RuntimeError(f'live_WB_card_count_{offer}_{len(cards)}')
  card=cards[0]
  if str(card.get('vendorCode') or '')!=offer or str(card.get('brand') or '').strip().casefold()!='feron': raise RuntimeError(f'live_WB_identity_mismatch_{offer}')
  title=str(card.get('title') or '').upper()
  if not any(m in title for m in ALLOWED[offer]): raise RuntimeError(f'live_WB_model_mismatch_{offer}')
  before[offer]=card
  exact=[d for d in docs(card) if norm_number(d.get('number'))==norm_number(NUMBER)]
  if len(exact)>1: raise RuntimeError(f'duplicate_exact_WB_documents_{offer}')
  payload=merge(card,target_doc)
  row={'offer_id':offer,'nmID':str(card.get('nmID') or ''),'title':card.get('title'),'prior_document_signatures':existing_signature(card),'had_exact_document':bool(exact),'payload':payload,'before':card}
  if payload is None:
   doc=exact[0]
   verdict=doc.get('verdict') or {}
   if verdict.get('verified') is not True or verdict.get('reason')!='valid': raise RuntimeError(f'existing_WB_document_not_valid_{offer}')
   prior[offer]=row
  else: writes.append(row)
  rows.append(row)
 plan={'checked_at_utc':now(),'fsa_number':NUMBER,'wb_number_form':WB_NUMBER,'issue_date':ISSUE,'expiry_date':EXPIRY,'target_cards':len(offers),'updates_planned':len(writes),'already_present_valid':len(prior),'source_pdf_deleted':False,'ozon_write_skipped_reason':'Current Ozon TN VED 8504909800 is outside FSA scope 8504409100.','cards':[{'offer_id':x['offer_id'],'nmID':x['nmID'],'title':x['title'],'had_exact_document':x['had_exact_document']} for x in rows]}
 if not args.execute:
  print(json.dumps(plan,ensure_ascii=False,indent=2)); return
 state={'started_at_utc':now(),'phase':'wb_update_prepared',**plan,'writes_sent':0}
 atomic(STATE,state)
 payloads=[x['payload'] for x in writes]
 if payloads:
  state.update(phase='wb_update_sent',writes_sent=1,updated_at_utc=now()); atomic(STATE,state)
  try: response=client.call('wb','/content/v2/cards/update',payloads,mutation=True)
  except Exception as exc:
   state.update(phase='wb_update_uncertain',error_type=type(exc).__name__,updated_at_utc=now()); atomic(STATE,state)
   raise RuntimeError('WB write outcome uncertain; read live state before retry') from None
  state['wb_response']=response
  if response.get('error') is not False:
   state.update(phase='wb_update_rejected',updated_at_utc=now()); atomic(STATE,state)
   raise RuntimeError('WB update rejected; do not retry until reconciled')
  state.update(phase='wb_update_accepted',updated_at_utc=now()); atomic(STATE,state)
 statuses=collections.Counter(); failures=[]; read_rows=[]
 for row in rows:
  offer=row['offer_id']; cards=client.wb_cards(offer)
  if len(cards)!=1:
   failures.append({'offer_id':offer,'reason':'readback_card_count_changed','count':len(cards)}); continue
  card=cards[0]; matches=[d for d in docs(card) if norm_number(d.get('number'))==norm_number(NUMBER)]
  exact=[d for d in matches if doc_key(d)==doc_key(target_doc) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  preserved=True
  if row['payload'] is not None:
   preserved=comparable_card(card)==comparable_card(row['before']) and all(sig in existing_signature(card) for sig in row['prior_document_signatures'])
  verdict=(exact[0].get('verdict') or {}) if len(exact)==1 else {}
  status='valid' if verdict.get('verified') is True and verdict.get('reason')=='valid' else 'pending_or_no_verdict' if len(exact)==1 and preserved else 'readback_incomplete'
  statuses[status]+=1
  result={'offer_id':offer,'nmID':str(card.get('nmID') or ''),'exact_document_count':len(exact),'metadata_exact':len(exact)==1,'prior_documents_and_card_fields_preserved':preserved,'verdict':verdict,'status':status}
  read_rows.append(result)
  if not result['metadata_exact'] or not preserved: failures.append(result)
 readback={'checked_at_utc':now(),'complete':len(read_rows)==len(offers) and not failures,'declaration_number':NUMBER,'target_cards':len(offers),'updated_cards':len(writes),'already_present_valid':len(prior),'verified_target_cards':len(read_rows)-len(failures),'status_counts':dict(statuses),'failures':failures,'cards':read_rows,'source_pdf_deleted':False}
 atomic(READBACK,readback)
 state.update(phase='verified_complete' if readback['complete'] else 'readback_incomplete',finished_at_utc=now(),readback_path=str(READBACK),wb_status_counts=dict(statuses),failure_count=len(failures),source_pdf_deleted=False)
 atomic(STATE,state)
 print(json.dumps({'phase':state['phase'],'target_cards':len(offers),'updated_cards':len(writes),'already_present_valid':len(prior),'readback_cards':len(read_rows),'status_counts':dict(statuses),'failures':failures,'source_pdf_deleted':False},ensure_ascii=False,indent=2))
 if failures or len(read_rows)!=len(offers): raise RuntimeError('WB readback incomplete; inspect state and do not retry blindly')

if __name__=='__main__': main()
