#!/usr/bin/env python3
"""Verify delayed WB visibility for declaration 58098/25 without resending writes."""
from __future__ import annotations
import collections, hashlib, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS,UPDATE_CARD_FIELDS,doc_key,norm_number
NUMBER='ЕАЭС N RU Д-CN.РА06.В.58098/25'; ISSUE='2025-08-01'; EXPIRY='2030-07-31'
OFFERS=['41326-1','41327-1','48990-1','51661-1']
PRE=HERE/'feron_58098_crossplatform_preflight_live_20261021.json'
EXEC=HERE/'feron_58098_wb_execution_20261021.json'
DELAY=HERE/'feron_58098_wb_delayed_readback_20261021.json'
OUT=HERE/'feron_58098_wb_reconciled_readback_20261021.json'
def atomic(p,v):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');t.replace(p)
def docs(c):return list((c.get('documents') or {}).get('items') or [])
def projection(c):return [{k:d[k] for k in DOC_FIELDS if k in d} for d in docs(c)]
def signature(d):return (doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10],d.get('isEndless'))
def main():
 pre=json.loads(PRE.read_text()); state=json.loads(EXEC.read_text()); delayed=json.loads(DELAY.read_text())
 if state.get('writes_sent')!=1 or not (state.get('wb_response') or {}).get('error') is False:raise RuntimeError('WB write acceptance not proven')
 client=Client(); rows=[]; failures=[]; counts=collections.Counter()
 for offer in OFFERS:
  old=[x for x in pre['wb']['rows'] if x['offer_id']==offer]
  if len(old)!=1:raise RuntimeError('preflight exact card evidence missing')
  cards=client.wb_cards(offer)
  if len(cards)!=1 or cards[0].get('vendorCode')!=offer:raise RuntimeError('live WB card identity changed')
  card=cards[0]; target=[d for d in docs(card) if norm_number(d.get('number'))==norm_number(NUMBER)]
  exact=[d for d in target if doc_key(d)==doc_key({'type':2,'number':NUMBER}) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  if len(exact)!=1: failures.append({'offer_id':offer,'reason':'exact_document_missing_or_duplicate','count':len(exact)})
  verdict=(exact[0].get('verdict') or {}) if len(exact)==1 else {}
  if offer=='41327-1': status='valid' if verdict.get('verified') is True and verdict.get('reason')=='valid' else 'unexpected_preexisting_status'
  else: status='pending_review' if not verdict else ('valid' if verdict.get('verified') is True and verdict.get('reason')=='valid' else 'other_verdict')
  counts[status]+=1
  rows.append({'offer_id':offer,'nmID':str(card.get('nmID') or ''),'title':card.get('title'),'brand':card.get('brand'),'exact_document_count':len(exact),'metadata_exact':len(exact)==1,'verdict':verdict or None,'status':status,'document_count':len(docs(card))})
  if not rows[-1]['metadata_exact'] or status not in {'valid','pending_review'}: failures.append(rows[-1])
 local=pathlib.Path(json.loads(PRE.read_text())['declaration']['source_pdf_path']) if 'source_pdf_path' in json.loads(PRE.read_text())['declaration'] else HERE/'source_docs'/'feron_58098_25_upload.pdf'
 readback={'checked_at_utc':now(),'complete':not failures and len(rows)==len(OFFERS),'declaration_number':NUMBER,'target_cards':len(OFFERS),'updated_cards':3,'preexisting_valid_cards':1,'status_counts':dict(counts),'failures':failures,'cards':rows,'initial_immediate_readback':'temporarily did not show new docs; delayed live readback confirms visibility; no duplicate write was sent','wb_review_left_automatic':True,'source_pdf_path':str(local),'source_pdf_sha256':digest(local) if local.is_file() else None,'source_pdf_deleted':False,'ozon_write_skipped_reason':'Ozon TN VED 8504909800 is outside FSA scope 8504409100 on all four exact offers.'}
 atomic(OUT,readback)
 state.update(phase='verified_complete' if readback['complete'] else 'readback_incomplete_reconciled',finished_at_utc=now(),readback_path=str(OUT),wb_status_counts=dict(counts),failure_count=len(failures),delayed_readback_confirmed=readback['complete'],source_pdf_deleted=False)
 atomic(EXEC,state)
 print(json.dumps({'reconciled_readback':str(OUT),'phase':state['phase'],'target_cards':len(rows),'updated_cards':3,'status_counts':dict(counts),'failures':failures,'source_pdf_deleted':False},ensure_ascii=False,indent=2))
 if failures:raise RuntimeError('final WB readback incomplete; no retry sent')
if __name__=='__main__':main()
