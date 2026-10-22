#!/usr/bin/env python3
"""Read-only delayed cross-platform readback for Navigator certificate 37784/24."""
from __future__ import annotations
import collections,csv,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number
from apply_arlight_52132_wb_20261020 import code_values
NUMBER='ЕАЭС RU С-CN.АЯ46.В.37784/24'; ISSUE='2024-12-03'; EXPIRY='2029-12-02'
PRE=HERE/'navigator_37784_scope_preflight_20261022.json'; BEFORE=HERE/'navigator_37784_wb_before_20261022.json'; STATE=HERE/'navigator_37784_execution_20261022.json'; OUT=HERE/'navigator_37784_delayed_readback_20261022.json'
def find_records(c):
 out=[]
 for page in range(1,101):
  res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; batch=res.get('certificates')
  if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_invalid')
  out.extend(x for x in batch if norm_number(x.get('certificate_number'))==norm_number(NUMBER))
  if not batch or page>=int(res.get('page_count') or 0): return out
 raise RuntimeError('certificate_page_limit')
def docs(card): return ((card.get('documents') or {}).get('items') or [])
def doc_signature(d): return (int(d.get('type') or 0),str(d.get('number') or ''),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10],bool(d.get('isEndless')))
def main():
 pre=json.loads(PRE.read_text()); before=json.loads(BEFORE.read_text()); st=json.loads(STATE.read_text())
 targets={r['offer_id']:r for r in pre['ozon_targets']}; wbtargets={r['offer_id']:r for r in pre['wb_targets']}
 c=Client(); records=find_records(c)
 if len(records)!=1: raise RuntimeError('ozon_record_missing_or_duplicate')
 rec=records[0]; cid=int(rec['certificate_id']); binds=c.ozon_bindings(cid)
 product_ids={str(x['product_id']):x['offer_id'] for x in targets.values()}
 binding_by_offer=collections.defaultdict(list)
 for b in binds:
  if str(b.get('product_id')) in product_ids: binding_by_offer[product_ids[str(b.get('product_id'))]].append(b)
 ozrows=[]
 for offer,t in sorted(targets.items()):
  matching=[b for b in binding_by_offer[offer] if str(b.get('product_id'))==t['product_id'] and str(b.get('sku'))==t['sku']]
  ozrows.append({'offer_id':offer,'product_id':t['product_id'],'sku':t['sku'],'exact_binding_count':len(matching),'binding_status':matching[0].get('product_status_code') if len(matching)==1 else None})
 wb_before=before['cards']; wbrows=[]
 for i,offer in enumerate(sorted(wbtargets),1):
  cards=[x for x in c.wb_cards(offer) if str(x.get('vendorCode') or '')==offer]
  if len(cards)!=1:
   wbrows.append({'offer_id':offer,'card_count':len(cards),'exact_document_count':0,'status':'missing_or_duplicate'}); continue
  card=cards[0]; ds=docs(card); same=[d for d in ds if norm_number(d.get('number'))==norm_number(NUMBER)]
  exact=[d for d in same if int(d.get('type') or 0)==1 and str(d.get('startDate') or '')[:10]==ISSUE and str(d.get('endDate') or '')[:10]==EXPIRY and d.get('isEndless') is False]
  prior=docs(wb_before.get(offer) or {})
  prior_signatures={doc_signature(x) for x in prior}; current_signatures={doc_signature(x) for x in ds}
  prior_docs_preserved=prior_signatures <= current_signatures
  base={k:v for k,v in (wb_before.get(offer) or {}).items() if k not in {'documents','updatedAt','characteristics'}}
  cur={k:v for k,v in card.items() if k not in {'documents','updatedAt','characteristics'}}
  unchanged_other_fields=base==cur
  # Preserve all non-document characteristics; document-only characteristics may be supplied by WB.
  base_chars=[x for x in (wb_before.get(offer) or {}).get('characteristics') or [] if x.get('id') not in {15001135,15001137,15001138}]
  cur_chars=[x for x in card.get('characteristics') or [] if x.get('id') not in {15001135,15001137,15001138}]
  unrelated_characteristics_preserved=sorted(base_chars,key=lambda x:x.get('id',0))==sorted(cur_chars,key=lambda x:x.get('id',0))
  valid=any((d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('status')==1 and (d.get('verdict') or {}).get('reason')=='valid' for d in exact)
  pending=any(not d.get('verdict') for d in exact)
  wbrows.append({'offer_id':offer,'nmID':str(card.get('nmID')),'expected_nmID':wbtargets[offer].get('nmID'),'vendorCode':card.get('vendorCode'),'brand':card.get('brand'),'title':card.get('title'),'tnved':code_values(card),'exact_document_count':len(exact),'exact_documents':[{'type':d.get('type'),'number':d.get('number'),'startDate':d.get('startDate'),'endDate':d.get('endDate'),'isEndless':d.get('isEndless'),'verdict':d.get('verdict')} for d in exact],'valid':valid,'pending':pending,'prior_documents_preserved':prior_docs_preserved,'unrelated_card_fields_preserved':unchanged_other_fields and unrelated_characteristics_preserved,'status':'verified_exact' if len(exact)==1 and prior_docs_preserved and unchanged_other_fields and unrelated_characteristics_preserved else 'readback_mismatch'})
  if i%10==0: print(json.dumps({'wb_readback_checked':i,'total':len(wbtargets),'visible_exact':sum(x['status']=='verified_exact' for x in wbrows)}),flush=True)
 ozstatus=collections.Counter(str(x['binding_status'] or 'unknown') for x in ozrows if x['exact_binding_count']==1)
 wbstatus=collections.Counter(x['status'] for x in wbrows)
 verdict=collections.Counter('valid' if x['valid'] else 'pending_review_or_unverified' if x['pending'] else 'other' for x in wbrows if x['status']=='verified_exact')
 result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'ozon_certificate_id':cid,'ozon_record_status':rec.get('status_code'),'ozon_expected_bindings':32,'ozon_exact_bindings':sum(x['exact_binding_count']==1 for x in ozrows),'ozon_binding_status_counts':dict(ozstatus),'ozon_outside_binding_count':sum(1 for b in binds if str(b.get('product_id')) not in product_ids),'wb_target_cards':32,'wb_exact_cards':sum(x['status']=='verified_exact' for x in wbrows),'wb_status_counts':dict(wbstatus),'wb_verdict_counts':dict(verdict),'wb_left_for_marketplace_review':True,'wb_review_state_changed_by_agent':False,'tnved_discrepancy_documented':True,'failures':[{'offer_id':x.get('offer_id'),'reason':x.get('status')} for x in wbrows if x.get('status')!='verified_exact']+ [{'offer_id':x['offer_id'],'reason':'ozon_binding_not_exactly_once'} for x in ozrows if x['exact_binding_count']!=1], 'ozon_rows':ozrows,'wb_rows':wbrows,'local_source_deleted':False}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 st.update({'delayed_readback_artifact':str(OUT),'delayed_readback_checked_at_utc':result['checked_at_utc'],'delayed_ozon_exact_bindings':result['ozon_exact_bindings'],'delayed_ozon_binding_status_counts':result['ozon_binding_status_counts'],'delayed_wb_exact_cards':result['wb_exact_cards'],'delayed_wb_status_counts':result['wb_status_counts'],'delayed_wb_verdict_counts':result['wb_verdict_counts'],'phase':'delayed_readback_complete' if result['ozon_exact_bindings']==32 and result['wb_exact_cards']==32 else 'delayed_readback_incomplete'})
 STATE.write_text(json.dumps(st,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:result[k] for k in ('checked_at_utc','ozon_record_status','ozon_exact_bindings','ozon_binding_status_counts','wb_exact_cards','wb_status_counts','wb_verdict_counts','failures')},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
