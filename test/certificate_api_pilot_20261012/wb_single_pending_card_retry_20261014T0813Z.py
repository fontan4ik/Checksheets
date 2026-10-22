import json, hashlib
from pathlib import Path
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS, UPDATE_CARD_FIELDS, comparable_card, doc_key, norm_number
BASE=Path(__file__).resolve().parent
pre=json.loads((BASE/'wb_all_groups_targeted_preflight_20261014T0800Z.json').read_text())
row=next(x for x in pre['results'] if x['offer_id']=='020128-1')
proof=row['ozon_proof'][0]
if proof.get('ozon_status')!='approved' or proof.get('binding_status')!='approved': raise SystemExit('Ozon proof not approved; no write')
run_path=BASE/'wb_single_pending_card_retry_20261014T0813Z.json'
if run_path.exists(): raise SystemExit('Retry marker exists; reconcile before any further write')
client=Client(); cards=client.wb_cards('020128-1')
if len(cards)!=1: raise SystemExit(f'exact offer read returned {len(cards)} cards')
card=cards[0]
if card.get('nmID')!=row['nmID'] or card.get('vendorCode')!='020128-1': raise SystemExit('Card identity changed')
if comparable_card(card)!=comparable_card(row['before']): raise SystemExit('Unrelated card fields changed; re-plan manually')
items=[{k:d[k] for k in DOC_FIELDS if k in d} for d in ((card.get('documents') or {}).get('items') or [])]
addition=row['additions'][0]
key=doc_key(addition); nk=norm_number(addition['number'])
same=[d for d in items if norm_number(d.get('number',''))==nk]
if same: raise SystemExit('Document now exists on WB; no retry')
payload={k:card[k] for k in UPDATE_CARD_FIELDS if k in card}
payload['nmID']=card['nmID']; payload['vendorCode']=card['vendorCode']
payload['documents']={'items':items+[addition], 'excludeDocuments':False}
body=[payload]; encoded=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
run={'started_at':now(),'state':'prepared','offer_id':'020128-1','nmID':card['nmID'],
     'document':addition,'request_sha256':hashlib.sha256(encoded).hexdigest(),'request_bytes':len(encoded)}
run_path.write_text(json.dumps(run,ensure_ascii=False,indent=2))
run['state']='submitting_once';run['submitted_at']=now();run_path.write_text(json.dumps(run,ensure_ascii=False,indent=2))
try: response=client.call('wb','/content/v2/cards/update',body,mutation=True)
except Exception as e:
 run['state']='uncertain_reconcile_only';run['error_type']=type(e).__name__;run['finished_at']=now();run_path.write_text(json.dumps(run,ensure_ascii=False,indent=2));raise
run['response']=response;run['state']='accepted_readback_pending' if response.get('error') is False else 'response_error_reconcile_only'
run['finished_at']=now();run_path.write_text(json.dumps(run,ensure_ascii=False,indent=2))
print(json.dumps({'offer_id':'020128-1','nmID':card['nmID'],'state':run['state'],'response':response,'log':run_path.name},ensure_ascii=False),flush=True)
