from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012';sys.path.insert(0,str(API))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number,doc_key,copy_documents,comparable_card
SOURCE_PRE=HERE/'arlight_03451_remaining_8_live_preflight_20261021.json'
BEFORE=HERE/'arlight_03451_remaining_8_wb_before_20261021.json'
STATE=HERE/'arlight_03451_remaining_8_wb_execution_20261021.json'
OUT=HERE/'arlight_03451_remaining_8_wb_delayed_readback_20261021.json'
NUMBER='ЕАЭС RU С-HK.НА46.В.03451/22';ISSUE='2022-04-16';EXPIRY='2027-04-15';EXPECTED=8

def sig(d):return (doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10],bool(d.get('isEndless')))
def save(p,x):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def main():
 if OUT.exists():raise RuntimeError('delayed_readback_exists')
 pre=json.loads(SOURCE_PRE.read_text());before=json.loads(BEFORE.read_text());state=json.loads(STATE.read_text())
 if state.get('writes_sent')!=1 or state.get('phase')!='readback_incomplete':raise RuntimeError('no_single_accepted_write_to_recheck')
 b={x['offer_id']:x for x in before.get('cards') or []}
 if len(b)!=EXPECTED:raise RuntimeError('before_snapshot_incomplete')
 client=Client();rows=[];status=collections.Counter()
 for t in pre['targets']:
  offer=t['offer_id'];prior=b[offer];cards=client.wb_cards(offer)
  if len(cards)!=1:rows.append({'offer_id':offer,'nmID':prior['nmID'],'verified':False,'reason':'card_missing_or_ambiguous'});continue
  card=cards[0];docs=copy_documents(card);same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)];exact=[d for d in same if doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
  olddocs=copy_documents(prior['before']);old=collections.Counter(sig(d) for d in olddocs);actual=collections.Counter(sig(d) for d in docs);preserved=all(actual[k]>=v for k,v in old.items())
  fields=comparable_card(card)==comparable_card(prior['before']);identity=str(card.get('vendorCode') or '')==offer and str(card.get('nmID') or '')==str(prior['nmID']);brand=str(card.get('brand') or '').strip().casefold()=='arlight';okay=len(same)==1 and len(exact)==1 and preserved and fields and identity and brand
  row={'offer_id':offer,'nmID':str(card.get('nmID') or ''),'verified':okay,'metadata_exact':len(exact)==1,'exact_document_count':len(exact),'prior_documents_preserved':preserved,'unrelated_fields_preserved':fields,'identity_preserved':identity,'brand_preserved':brand,'wb_document_verdict':'pending_review_or_verdict_missing','scope_basis':prior.get('scope_basis')}
  rows.append(row)
  if okay:status['pending_review_or_verdict_missing']+=1
  print(json.dumps({'offer_id':offer,'verified':okay,'exact_docs':len(exact)}),flush=True)
 failures=[r for r in rows if not r.get('verified')]
 out={'checked_at':now(),'complete':not failures and len(rows)==EXPECTED,'number':NUMBER,'target_cards':len(rows),'verified_target_cards':len(rows)-len(failures),'status_counts':dict(status),'failures':failures,'cards':rows,'wb_review_left_pending':True,'manual_wb_review_action_taken':False,'mutation_resent':False,'note':'Delayed verification after one accepted batch; no repeat mutation.'}
 save(OUT,out);state['immediate_readback']={'verified_target_cards':state.get('verified_target_cards'),'failures':state.get('failures')};state.update(phase='verified_complete' if not failures else 'readback_incomplete',verified_target_cards=out['verified_target_cards'],status_counts=dict(status),failures=failures,delayed_readback_path=str(OUT),updated_at=now(),mutation_resent=False);save(STATE,state)
 print(json.dumps({k:out[k] for k in ('complete','verified_target_cards','status_counts','failures','mutation_resent')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
