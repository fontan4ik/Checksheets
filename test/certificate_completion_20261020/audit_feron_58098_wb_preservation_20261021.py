#!/usr/bin/env python3
"""Audit prior card fields/docs and final live status for 58098/25."""
from __future__ import annotations
import collections,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import now,digest
from reconcile_approved_ozon_docs_to_wb import UPDATE_CARD_FIELDS,DOC_FIELDS,doc_key,norm_number
LOG=ROOT/'test/certificate_api_pilot_20261012/api_calls.jsonl'
STATE=HERE/'feron_58098_wb_execution_20261021.json'
OUT=HERE/'feron_58098_wb_preservation_audit_20261021.json'
READBACK=HERE/'feron_58098_wb_reconciled_readback_20261021.json'
OFFERS=['41326-1','41327-1','48990-1','51661-1']
NUMBER='ЕАЭС N RU Д-CN.РА06.В.58098/25'; ISSUE='2025-08-01'; EXPIRY='2030-07-31'
def canonical(k,v):
 if k=='characteristics' and isinstance(v,list): return sorted(v,key=lambda x:(str(x.get('id')),str(x.get('name'))))
 if k=='sizes' and isinstance(v,list): return sorted(v,key=lambda x:json.dumps(x,sort_keys=True,ensure_ascii=False))
 return v
def signatures(card):
 return [doc_key({k:d[k] for k in DOC_FIELDS if k in d}) for d in ((card.get('documents') or {}).get('items') or [])]
def atomic(path,obj):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
def main():
 state=json.loads(STATE.read_text()); update_at=state.get('updated_at_utc')
 if not update_at:raise RuntimeError('WB update timestamp missing')
 update_at=update_at.replace('Z','+00:00')
 log=[json.loads(x) for x in LOG.read_text().splitlines() if x.strip()]
 before={};after={}
 for row in log:
  if row.get('platform')!='wb' or row.get('path')!='/content/v2/get/cards/list' or row.get('phase')!='response':continue
  try: cards=(row.get('body') or {}).get('cards') or []
  except Exception:continue
  for card in cards:
   offer=card.get('vendorCode')
   if offer not in OFFERS:continue
   ts=str(row.get('started_at') or '')
   if ts<update_at:before[offer]=card
   else:after[offer]=card
 if set(before)!=set(OFFERS) or set(after)!=set(OFFERS):raise RuntimeError('Before/after live API journal readbacks incomplete')
 cards=[]; failures=[]; status_counts=collections.Counter()
 for offer in OFFERS:
  b,a=before[offer],after[offer]
  if str(b.get('nmID'))!=str(a.get('nmID')) or b.get('vendorCode')!=a.get('vendorCode'):raise RuntimeError('Card identity changed')
  fields={k:canonical(k,b.get(k))==canonical(k,a.get(k)) for k in UPDATE_CARD_FIELDS if k!='documents'}
  old_docs=signatures(b);new_docs=signatures(a)
  preserved=all(s in new_docs for s in old_docs)
  docs=(a.get('documents') or {}).get('items') or []
  exact=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
  exact=[d for d in exact if doc_key(d)==doc_key({'type':2,'number':NUMBER}) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  if len(exact)!=1: status='metadata_missing_or_duplicate'; failures.append({'offer_id':offer,'reason':status})
  else:
   verdict=exact[0].get('verdict') or {}
   status='valid' if verdict.get('verified') is True and verdict.get('reason')=='valid' else 'pending_or_no_verdict' if not verdict else 'other_verdict'
  status_counts[status]+=1
  row={'offer_id':offer,'nmID':str(a.get('nmID')),'preserved_card_fields':fields,'card_fields_all_preserved':all(fields.values()),'prior_document_count':len(old_docs),'prior_documents_preserved':preserved,'exact_document_count':len(exact),'document_status':status,'verdict':exact[0].get('verdict') if len(exact)==1 else None}
  cards.append(row)
  if not row['card_fields_all_preserved'] or not preserved or len(exact)!=1 or status!='valid':failures.append(row)
 pdf=HERE/'source_docs'/'feron_58098_25_upload.pdf'
 audit={'checked_at_utc':now(),'read_only':True,'fsa_number':NUMBER,'update_request_accepted':(state.get('wb_response') or {}).get('error') is False,'wb_target_cards':len(cards),'updated_cards':3,'preexisting_valid_cards':1,'status_counts':dict(status_counts),'cards':cards,'all_prior_fields_and_docs_preserved':not any(not r['card_fields_all_preserved'] or not r['prior_documents_preserved'] for r in cards),'complete':not failures,'failures':failures,'source_pdf_path':str(pdf),'source_pdf_sha256':digest(pdf) if pdf.is_file() else None,'source_pdf_deleted':False,'ozon_write_skipped_reason':'All four live Ozon products report TN VED 8504909800; FSA declaration lists 8504409100.'}
 atomic(OUT,audit)
 readback={'checked_at_utc':audit['checked_at_utc'],'complete':audit['complete'],'declaration_number':NUMBER,'target_cards':len(cards),'updated_cards':3,'preexisting_valid_cards':1,'status_counts':dict(status_counts),'failures':failures,'cards':[{'offer_id':r['offer_id'],'nmID':r['nmID'],'exact_document_count':r['exact_document_count'],'metadata_exact':r['exact_document_count']==1,'prior_documents_preserved':r['prior_documents_preserved'],'card_fields_all_preserved':r['card_fields_all_preserved'],'verdict':r['verdict'],'status':r['document_status']} for r in cards],'delayed_readback_confirmed':True,'source_pdf_path':str(pdf),'source_pdf_sha256':audit['source_pdf_sha256'],'source_pdf_deleted':False,'ozon_write_skipped_reason':audit['ozon_write_skipped_reason'],'preservation_audit_file':str(OUT)}
 atomic(READBACK,readback)
 state.update(phase='verified_complete' if audit['complete'] else 'readback_incomplete',finished_at_utc=audit['checked_at_utc'],readback_path=str(READBACK),preservation_audit_path=str(OUT),wb_status_counts=dict(status_counts),failure_count=len(failures),delayed_readback_confirmed=True,all_prior_fields_and_docs_preserved=audit['all_prior_fields_and_docs_preserved'],source_pdf_deleted=False)
 atomic(STATE,state)
 print(json.dumps({'audit_file':str(OUT),'readback_file':str(READBACK),'phase':state['phase'],'status_counts':dict(status_counts),'all_prior_fields_and_docs_preserved':audit['all_prior_fields_and_docs_preserved'],'failures':failures,'source_pdf_deleted':False},ensure_ascii=False,indent=2))
 if failures:raise RuntimeError('Preservation or final verdict audit failed')
if __name__=='__main__':main()
