"""Read the full WB catalog and reconcile the 591 newly attached Arlight docs."""
from __future__ import annotations
import json, sys, time
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now  # noqa:E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, doc_key, norm_number, comparable_card  # noqa:E402
from run_all_found_certificates_20261014 import deduplicate_equivalent_wb_rows  # noqa:E402

PRE=json.loads((HERE/'live_marketplaces_snapshot_final_20261020.json').read_text())
MANIFEST=json.loads((HERE/'arlight_0333370_exact_scope_manifest_20261020.json').read_text())
UPDATE=json.loads((HERE/'arlight_0333370_wb_execution_state_20261020.json').read_text())
CHECK=HERE/'arlight_0333370_wb_full_live_reconciliation_20261020.json'

def main():
 if UPDATE.get('phase')!='complete_with_wb_readback' or UPDATE.get('confirmed_count')!=591:
  raise RuntimeError('Prior target readback is not complete; do not refresh a partial result')
 c=Client();cards=[];cursor={'limit':100};seen=set();pages=0
 while True:
  body=c.call('wb','/content/v2/get/cards/list',{'settings':{'sort':{'ascending':True},'cursor':cursor,'filter':{'withPhoto':-1}}})
  data=body.get('data',body);batch=data.get('cards') or data.get('items') or []; cur=data.get('cursor') or body.get('cursor') or {}
  if body.get('error') or not isinstance(batch,list) or cur.get('total')!=len(batch): raise RuntimeError('Invalid WB page/cursor during fresh read')
  cards.extend(batch);pages+=1
  if pages%40==0: print(f'WB fresh snapshot: {pages} pages, {len(cards)} rows',flush=True)
  if len(batch)<100: break
  sig=(cur.get('updatedAt'),cur.get('nmID'))
  if None in sig or sig in seen: raise RuntimeError('WB cursor is missing or repeated')
  seen.add(sig);cursor={'limit':100,'updatedAt':sig[0],'nmID':sig[1]}
 if len(cards)<10000: raise RuntimeError(f'Unexpectedly incomplete WB catalog: {len(cards)}')
 raw_count=len(cards);unique,duplicates=deduplicate_equivalent_wb_rows(cards)
 ids=[str(x.get('nmID') or '') for x in unique]
 if any(not x for x in ids) or len(ids)!=len(set(ids)): raise RuntimeError('WB has conflicting duplicate nmID rows')
 checked=now()

 before_cards=PRE['wb_catalog']['cards']; before_by={str(x.get('vendorCode')):x for x in before_cards if x.get('vendorCode')}
 after_by={str(x.get('vendorCode')):x for x in unique if x.get('vendorCode')}
 wanted={'type':1,'number':'РОСС RU.32001.04ИБФ1.ОСП32.90090','startDate':'2025-12-01T00:00:00Z','endDate':'2028-11-30T00:00:00Z','isEndless':False}
 proof=[]
 for target in MANIFEST['targets']:
  offer=str(target['offer_id']);old=before_by.get(offer);new=after_by.get(offer)
  olddocs=copy_documents(old or {});newdocs=copy_documents(new or {})
  matches=[d for d in newdocs if norm_number(d.get('number'))==norm_number(wanted['number'])]
  visible=len(matches)==1 and doc_key(matches[0])==doc_key(wanted) and str(matches[0].get('startDate',''))[:10]=='2025-12-01' and str(matches[0].get('endDate',''))[:10]=='2028-11-30'
  oldset={(doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10],str(d.get('isEndless'))) for d in olddocs}
  newset={(doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10],str(d.get('isEndless'))) for d in newdocs}
  preserved=old is not None and new is not None and oldset<=newset
  other_fields=old is not None and new is not None and comparable_card(old)==comparable_card(new)
  raw=[d for d in ((new or {}).get('documents') or {}).get('items') or [] if norm_number(d.get('number'))==norm_number(wanted['number'])]
  verdict=[d.get('verdict') or d.get('status') for d in raw]
  proof.append({'offer_id':offer,'nmID':target['wb_nmID'],'new_document_visible':visible,'prior_documents_preserved':preserved,'other_card_fields_preserved':other_fields,'platform_verdict':verdict})
 counts=Counter(('visible' if x['new_document_visible'] else 'missing')+'|'+('prior_preserved' if x['prior_documents_preserved'] else 'prior_lost')+'|'+('fields_preserved' if x['other_card_fields_preserved'] else 'fields_changed') for x in proof)
 today=__import__('datetime').date.today().isoformat();valid=set();pending=set();rejected=set()
 for card in unique:
  docs=(card.get('documents') or {}).get('items') or []
  good=[d for d in docs if (d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('status')==1 and (d.get('verdict') or {}).get('reason')=='valid' and str(d.get('endDate') or '')[:10]>=today]
  wait=[d for d in docs if (d.get('verdict') or {}).get('status') in (None,1) and (d.get('verdict') or {}).get('reason') in (None,'','valid') and not ((d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('status')==1 and (d.get('verdict') or {}).get('reason')=='valid')]
  bad=[d for d in docs if (d.get('verdict') or {}).get('status') not in (None,1) or (d.get('verdict') or {}).get('reason') not in (None,'','valid')]
  id=str(card.get('nmID'))
  if good: valid.add(id)
  elif wait: pending.add(id)
  elif bad: rejected.add(id)
 result={'checked_at':checked,'snapshot_materialized':False,'pages':pages,'raw_rows':raw_count,'unique_cards':len(unique),'equivalent_duplicates_removed':duplicates,'target_documents':len(proof),'target_readback_counts':dict(counts),'targets':proof,'global_cards_with_current_valid_doc':len(valid),'global_pending_only_cards':len(pending),'global_rejected_only_cards':len(rejected),'global_cards_without_any_current_valid_doc':len(unique)-len(valid),'review_verdict':'document status is whatever WB returned; no moderation state was changed'}
 tmp=CHECK.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2));tmp.replace(CHECK)
 print(json.dumps({k:result[k] for k in ['checked_at','pages','unique_cards','target_readback_counts','global_cards_with_current_valid_doc','global_pending_only_cards','global_rejected_only_cards','global_cards_without_any_current_valid_doc']},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
