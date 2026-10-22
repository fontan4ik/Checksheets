#!/usr/bin/env python3
"""Fresh non-mutating WB readback after asynchronous card document propagation."""
from __future__ import annotations
import collections, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents,doc_key,norm_number,comparable_card  # noqa: E402

PREF=HERE/'navigator_nll_08110_06643_fresh_preflight_20261022.json'
BEFORE=HERE/'navigator_nll_08110_06643_wb_before_20261022.json'
STATE=HERE/'navigator_nll_08110_06643_execution_20261022.json'
OUT=HERE/'navigator_nll_08110_06643_readback_reconciled_20261022.json'
DOCS=[
 {'number':'ЕАЭС N RU Д-CN.РА11.В.08110/24','type':2,'issue':'2024-12-02','expiry':'2029-12-01'},
 {'number':'ЕАЭС RU С-CN.НВ54.В.06643/24','type':1,'issue':'2024-12-04','expiry':'2029-12-03'},
]

def sig(d):
 return (doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10],bool(d.get('isEndless')))

def main():
 if OUT.exists(): raise RuntimeError('reconciled_readback_exists_inspect_first')
 pre=json.loads(PREF.read_text()); before=json.loads(BEFORE.read_text())
 state=json.loads(STATE.read_text())
 targets={str(x['offer_id']):x for x in pre['targets'] if x.get('wb_eligible') is True}
 before_by_offer={str(x['offer_id']):x for x in before['cards']}
 if len(targets)!=153 or len(before_by_offer)!=153: raise RuntimeError('target_or_before_card_count_conflict')
 c=Client(); rows=[]; failures=[]; verdicts=collections.Counter()
 for index,(offer,target) in enumerate(sorted(targets.items()),start=1):
  cards=c.wb_cards(offer)
  if len(cards)!=1:
   failures.append({'offer_id':offer,'problem':'card_count','count':len(cards)}); continue
  card=cards[0]; docs=copy_documents(card); exact_docs=[]
  for want in DOCS:
   same=[d for d in docs if norm_number(d.get('number'))==norm_number(want['number'])]
   exact=[d for d in same if doc_key(d)==(want['type'],norm_number(want['number']))
          and str(d.get('startDate',''))[:10]==want['issue']
          and str(d.get('endDate',''))[:10]==want['expiry']
          and d.get('isEndless') is False]
   if len(exact)==1: exact_docs.append(exact[0])
   else: failures.append({'offer_id':offer,'problem':'exact_document_count','number':want['number'],'count':len(exact),'same_number_count':len(same)})
  prior=before_by_offer[offer]['prior_doc_signatures']; after=[sig(d) for d in docs]
  prior_ok=all(x in after for x in prior)
  fields_ok=comparable_card(card)==comparable_card(before_by_offer[offer]['card'])
  if not prior_ok or not fields_ok: failures.append({'offer_id':offer,'problem':'preservation_failed','prior_documents':prior_ok,'other_fields':fields_ok})
  doc_verdicts=[]
  for d in exact_docs:
   v=d.get('verdict') or {}
   status='valid' if v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' else 'pending_or_unverified'
   verdicts[status]+=1
   doc_verdicts.append({'number':d.get('number'),'status':status,'verdict':v})
  rows.append({'offer_id':offer,'nmID':str(card.get('nmID') or ''),'exact_documents':len(exact_docs),
               'target_documents_expected':2,'preserved_existing_documents':prior_ok,
               'preserved_other_fields':fields_ok,'document_verdicts':doc_verdicts})
  if index%20==0 or index==len(targets):
   partial={'checked_at_utc':now(),'complete':False,'checked_cards':len(rows),'target_cards':len(targets),
            'failures_so_far':len(failures),'cards':rows}
   OUT.write_text(json.dumps(partial,ensure_ascii=False,indent=2)+'\n')
   print(json.dumps({'live_wb_readbacks':index,'total':len(targets)},ensure_ascii=False),flush=True)
 result={'checked_at_utc':now(),'complete':len(rows)==len(targets),
         'target_cards':len(targets),'verified_cards_with_both_exact_documents':sum(x['exact_documents']==2 for x in rows),
         'document_verdict_counts':dict(verdicts),'failure_count':len(failures),'failures':failures,
         'cards':rows,'marketplace_verdicts_were_not_modified':True}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 state.update({'wb_reconciled_readback_path':str(OUT),'wb_reconciled_checked_at_utc':result['checked_at_utc'],
               'wb_reconciled_cards_with_both_exact_documents':result['verified_cards_with_both_exact_documents'],
               'wb_reconciled_failure_count':len(failures),
               'phase':'finished_readback_reconciled' if result['complete'] and not failures and result['verified_cards_with_both_exact_documents']==153 else 'finished_with_remaining_readback_issues'})
 s_tmp=STATE.with_suffix('.tmp');s_tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');s_tmp.replace(STATE)
 print(json.dumps({k:v for k,v in result.items() if k not in ('cards','failures')},ensure_ascii=False,indent=2))
 if failures or len(rows)!=153: raise RuntimeError('wb_reconciled_readback_incomplete')
if __name__=='__main__':main()
