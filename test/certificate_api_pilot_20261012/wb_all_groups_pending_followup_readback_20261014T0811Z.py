import collections, json
from pathlib import Path
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS, doc_key, comparable_card
BASE=Path(__file__).resolve().parent
first=json.loads((BASE/'wb_all_groups_targeted_readback_20261014T0800Z.json').read_text())
pre=json.loads((BASE/'wb_all_groups_targeted_preflight_20261014T0800Z.json').read_text())
pre_by={x['offer_id']:x for x in pre['results']}
pending=[offer for offer,row in first['results'].items() if row['state']=='pending_or_missing']
client=Client(); results={}
for i,offer in enumerate(pending,1):
 try: cards=client.wb_cards(offer)
 except Exception as e:
  results[offer]={'state':'read_error','error':type(e).__name__}; continue
 if len(cards)!=1:
  results[offer]={'state':'missing_or_ambiguous','matches':len(cards)}; continue
 card=cards[0]; before=pre_by[offer]['before']
 items=[{k:d[k] for k in DOC_FIELDS if k in d} for d in ((card.get('documents') or {}).get('items') or [])]
 expected=pre_by[offer]['additions']
 found={}
 for want in expected:
  found[want['number']]=[d for d in items if doc_key(d)==doc_key(want) and str(d.get('startDate') or '')[:10]==want['startDate'][:10] and str(d.get('endDate') or '')[:10]==want['endDate'][:10]]
 results[offer]={'state':'visible' if all(len(x)==1 for x in found.values()) else 'still_missing',
   'nmID':card.get('nmID'),'documents_visible':all(len(x)==1 for x in found.values()),
   'visible_documents':{n:(xs[0] if xs else None) for n,xs in found.items()},
   'overallVerdict':(card.get('documents') or {}).get('overallVerdict'),
   'unrelated_fields_preserved':comparable_card(before)==comparable_card(card)}
 if i%10==0: print(f'read {i}/{len(pending)}',flush=True)
counts=dict(collections.Counter(x['state'] for x in results.values()))
out={'checked_at':now(),'prior_pending_count':len(pending),'counts':counts,'results':results}
path=BASE/'wb_all_groups_pending_followup_readback_20261014T0811Z.json'
path.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'checked_at':out['checked_at'],'prior_pending_count':len(pending),'counts':counts,'output':path.name},ensure_ascii=False),flush=True)
