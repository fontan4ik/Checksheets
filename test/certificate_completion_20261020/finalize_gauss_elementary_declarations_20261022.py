#!/usr/bin/env python3
"""Read-only marketplace reconciliation after the accepted Gauss update batch."""
from __future__ import annotations
import collections, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]; PILOT=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(PILOT))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number, comparable_card
from execute_gauss_elementary_declarations_20261022 import DOCS, TARGETS, PREFLIGHT, STATE, BEFORE, READBACK, JOURNAL, ADDENDUM

def save(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
def wb_valid(verdict): return isinstance(verdict,dict) and verdict.get('verified') is True and verdict.get('status')==1 and verdict.get('reason')=='valid'
def exact(items,doc):
 return [x for x in items if norm_number(x.get('number'))==norm_number(doc['number']) and int(x.get('type') or 0)==2 and str(x.get('startDate') or '')[:10]==doc['issue'] and str(x.get('endDate') or '')[:10]==doc['expiry'] and x.get('isEndless') is False]
def sig(d): return (norm_number(d.get('number')),int(d.get('type') or 0),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10],bool(d.get('isEndless')))
def prior_preserved(old,new):
 old_docs=collections.Counter(sig(x) for x in (old.get('documents') or {}).get('items') or [])
 new_docs=collections.Counter(sig(x) for x in (new.get('documents') or {}).get('items') or [])
 return all(new_docs[k]>=n for k,n in old_docs.items()) and comparable_card(old)==comparable_card(new)
def main():
 state=json.loads(STATE.read_text()); before=json.loads(BEFORE.read_text());
 if state.get('phase') not in {'ozon_records_and_bindings_visible','delayed_readback_complete','readback_incomplete'}: raise RuntimeError('unexpected_execution_phase:'+str(state.get('phase')))
 journal=[json.loads(x) for x in JOURNAL.read_text().splitlines() if x.strip()]
 wb_posts=[x for x in journal if x.get('platform')=='wb' and x.get('endpoint')=='/content/v2/cards/update' and x.get('phase')=='response']
 if not wb_posts or any((x.get('response') or {}).get('error') is not False for x in wb_posts): raise RuntimeError('wb_update_not_confirmed_by_response')
 pre_cards={str(x['offer_id']):x['card'] for x in before['cards']}; client=Client()
 ozon=[]
 for doc in DOCS:
  info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':doc['number']}).get('result') or {}
  certs=[]
  for page in range(1,101):
   result=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; batch=result.get('certificates')
   if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_invalid')
   certs.extend(batch)
   if not batch or page>=int(result.get('page_count') or 0): break
  matches=[x for x in certs if norm_number(x.get('certificate_number'))==norm_number(doc['number'])]
  if len(matches)!=1: raise RuntimeError('ozon_record_missing_or_ambiguous:'+doc['number'])
  rec=matches[0]; bindings=client.ozon_bindings(int(rec['certificate_id'])); by_pair=collections.defaultdict(list)
  for b in bindings: by_pair[(str(b.get('product_id') or ''),str(b.get('sku') or ''))].append(b)
  rows=[]
  for t in TARGETS:
   found=by_pair[(str(t['product_id']),str(t['sku']))]
   rows.append({'offer_id':t['offer_id'],'exact_count':len(found),'product_status_code':found[0].get('product_status_code') if len(found)==1 else None})
  metadata=rec.get('type_code')=='declaration' and str(rec.get('issue_date') or '')[:10]==doc['issue'] and str(rec.get('expire_date') or '')[:10]==doc['expiry']
  ozon.append({'number':doc['number'],'certificate_id':str(rec['certificate_id']),'record_status':info.get('status_code'),'metadata_exact':metadata,'expected_bindings':len(TARGETS),'exact_bindings':sum(x['exact_count']==1 for x in rows),'binding_status_counts':dict(collections.Counter(str(x['product_status_code'] or 'missing') for x in rows)),'bindings':rows})
 wb=[]
 for t in TARGETS:
  cards=client.wb_cards(t['offer_id'])
  if len(cards)!=1: raise RuntimeError('wb_card_missing_or_ambiguous:'+t['offer_id'])
  card=cards[0]; old=pre_cards[t['offer_id']]; items=copy_documents(card); docs={}
  for d in DOCS:
   rows=exact(items,d); verdict=rows[0].get('verdict') if len(rows)==1 else None
   docs[d['number']]={'exact_count':len(rows),'state':'valid' if wb_valid(verdict) else ('pending_review_or_no_verdict' if len(rows)==1 else 'missing_or_conflict'),'verdict':verdict}
  wb.append({'offer_id':t['offer_id'],'nmID':str(card.get('nmID') or ''),'documents':docs,'previous_documents_and_unrelated_fields_preserved':prior_preserved(old,card)})
 exact_complete=all(x['metadata_exact'] and x['exact_bindings']==len(TARGETS) for x in ozon) and all(all(d['exact_count']==1 for d in x['documents'].values()) and x['previous_documents_and_unrelated_fields_preserved'] for x in wb)
 out={'checked_at_utc':now(),'brand':'Gauss','scope_note':'These active Elementary Promo declarations cover the exact article numbers listed by FSA and TN VED 9405420012. The same two product cards already have active GFD certificate/declaration records for the same technical regulations from the earlier Gauss GFD run today; this upload is an additional current source set, not a newly covered product count.','documents':[{'number':d['number'],'fsa_record_id':d['registry_id'],'fsa_status':'active','issue_date':d['issue'],'expiry_date':d['expiry'],'source_sha256':d['sha256'],'local_source_pdf_deleted':False} for d in DOCS],'ozon':ozon,'wb':wb,'wb_update_response':wb_posts[-1]['response'],'wb_review_left_pending':True,'wb_review_state_changed_by_agent':False,'local_source_pdfs_deleted':False,'exact_crossplatform_metadata_verified':exact_complete,'verification_artifacts':[pathlib.Path(__file__).name,STATE.name,BEFORE.name,JOURNAL.name,READBACK.name]}
 save(READBACK,out);state.update({'phase':'delayed_readback_complete' if exact_complete else 'readback_incomplete','final_readback_path':str(READBACK),'final_checked_at_utc':out['checked_at_utc'],'exact_crossplatform_metadata_verified':exact_complete});save(STATE,state)
 if exact_complete:
  add=json.loads(ADDENDUM.read_text(encoding='utf-8')); entries=add.get('post_snapshot_writes',[])
  if any(any(x.get('document_number')==d['number'] for x in entries) for d in DOCS): raise RuntimeError('addendum_duplicate_document_entry')
  for doc,oz in zip(DOCS,ozon):
   wc=sum(x['documents'][doc['number']]['exact_count']==1 for x in wb); wvalid=sum(x['documents'][doc['number']]['state']=='valid' for x in wb)
   entries.append({'brand':'Gauss','document_number':doc['number'],'type':'declaration','fsa_record_id':doc['registry_id'],'fsa_status':'active','source_sha256':doc['sha256'],'ozon_certificate_id':oz['certificate_id'],'ozon_record_status':oz['record_status'],'ozon_expected_bindings':oz['expected_bindings'],'ozon_exact_bindings':oz['exact_bindings'],'ozon_binding_status_counts':oz['binding_status_counts'],'ozon_out_of_scope_or_identity_skipped':0,'wb_expected_cards':len(wb),'wb_exact_cards':wc,'wb_valid_cards':wvalid,'wb_pending_or_unverified_cards':wc-wvalid,'wb_skipped':[],'wb_review_state_changed_by_agent':False,'wb_left_for_marketplace_review':True,'local_source_pdf_deleted':False,'limitation':'Active FSA declarations exactly include articles 613100150P and 613100200P and TN VED 9405420012. The same cards already have active Gauss GFD documents for TR CU 004/020 and TR EAEU 037 from the earlier Gauss GFD update, so these additional declarations do not reduce the uncovered-product count.','verification_artifacts':[PREFLIGHT.name,STATE.name,BEFORE.name,READBACK.name]})
  add['post_snapshot_writes']=entries; totals=add['post_snapshot_totals']; totals['ozon_certificate_records']+=len(DOCS); totals['ozon_live_bindings']+=sum(x['exact_bindings'] for x in ozon)
  for row in ozon:
   if row['record_status']=='approved': totals['ozon_certificate_statuses']['approved']+=1
   elif row['record_status'] in {'awaiting_verification','under_review'}: totals['ozon_certificate_statuses']['awaiting_verification']+=1
   elif row['record_status']=='declined': totals['ozon_certificate_statuses']['declined']+=1
  # Both offers were already covered by the earlier GFD run; these duplicate-regulation links do not change coverage totals.
  add.setdefault('current_live_reconciliations',{})['gauss_elementary_declarations_20261022']={'documents':len(DOCS),'ozon_exact_bindings':sum(x['exact_bindings'] for x in ozon),'ozon_record_status_counts':dict(collections.Counter(str(x['record_status'] or 'unknown') for x in ozon)),'ozon_binding_status_counts':{x['number']:x['binding_status_counts'] for x in ozon},'wb_cards':len(wb),'wb_exact_document_bindings':sum(sum(v['exact_count']==1 for v in x['documents'].values()) for x in wb),'wb_valid_document_bindings':sum(sum(v['state']=='valid' for v in x['documents'].values()) for x in wb),'wb_pending_or_unverified_document_bindings':sum(sum(v['state']=='pending_review_or_no_verdict' for v in x['documents'].values()) for x in wb),'net_new_ozon_products_covered':0,'net_new_wb_cards_covered':0,'mutation_attempted':True,'local_source_files_deleted':False,'limitation':'Cards already had valid GFD documents for the same regulations before this run; no reduction to uncovered-product counts.','verification_artifact':str(READBACK)}
  add['checked_at_utc']=now();add['complete']=False;add['local_source_pdfs_deleted']=False;save(ADDENDUM,add)
 print(json.dumps({'phase':state['phase'],'exact_crossplatform_metadata_verified':exact_complete,'ozon':[{k:x[k] for k in ['number','certificate_id','record_status','exact_bindings','binding_status_counts']} for x in ozon],'wb_cards':len(wb),'wb_documents_exact':sum(sum(v['exact_count']==1 for v in x['documents'].values()) for x in wb),'wb_verdict_counts':dict(collections.Counter(v['state'] for x in wb for v in x['documents'].values())),'covered_product_net_increase':0,'local_source_pdfs_deleted':False},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
