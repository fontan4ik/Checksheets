import collections,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS,doc_key,norm_number,comparable_card
B=Path(__file__).resolve().parent
pre=json.loads((B/'wb_all_groups_targeted_preflight_20261014T0800Z.json').read_text())
client=Client(); results={}
for i,row in enumerate(pre['results'],1):
 offer=row['offer_id']
 try: cards=client.wb_cards(offer)
 except Exception as e: results[offer]={'state':'read_error','error':type(e).__name__};continue
 if len(cards)!=1: results[offer]={'state':'missing_or_ambiguous','matches':len(cards)};continue
 card=cards[0]; items=[{k:d[k] for k in DOC_FIELDS if k in d} for d in ((card.get('documents') or {}).get('items') or [])]
 doc_results=[]
 for want in row['additions']:
  found=[d for d in items if doc_key(d)==doc_key(want) and str(d.get('startDate') or '')[:10]==want['startDate'][:10] and str(d.get('endDate') or '')[:10]==want['endDate'][:10]]
  doc_results.append({'number':want['number'],'matches':len(found),'verdict':(found[0].get('verdict') if len(found)==1 else None)})
 before_docs=[{k:d[k] for k in DOC_FIELDS if k in d} for d in ((row['before'].get('documents') or {}).get('items') or [])]
 def sig(d):return (doc_key(d),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10])
 old_after=collections.Counter(sig(x) for x in items)
 old_before=collections.Counter(sig(x) for x in before_docs)
 old_preserved=not bool(old_before-old_after)
 visible=all(x['matches']==1 for x in doc_results)
 verdicts=[x['verdict'] for x in doc_results]
 valid=visible and all(isinstance(v,dict) and v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' for v in verdicts)
 card_preserved=comparable_card(row['before'])==comparable_card(card)
 results[offer]={'state':'valid' if valid else ('visible_pending' if visible else 'missing'),
  'nmID_before':row['nmID'],'nmID_after':card.get('nmID'),'documents':doc_results,
  'documents_visible':visible,'documents_valid':valid,'unrelated_fields_preserved':card_preserved,
  'preexisting_documents_preserved':old_preserved,'overallVerdict':(card.get('documents') or {}).get('overallVerdict')}
 if i%10==0: print(f'read {i}/{len(pre["results"])}',flush=True)
counts=dict(collections.Counter(x['state'] for x in results.values()))
out={'checked_at':now(),'target_count':len(pre['results']),'counts':counts,
 'all_documents_visible':all(x.get('documents_visible') for x in results.values()),
 'all_documents_valid':all(x.get('documents_valid') for x in results.values()),
 'all_unrelated_fields_preserved':all(x.get('unrelated_fields_preserved') for x in results.values()),
 'all_preexisting_documents_preserved':all(x.get('preexisting_documents_preserved') for x in results.values()),
 'results':results}
path=B/'wb_all_groups_final_check_20261014T0837Z.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False),flush=True)
