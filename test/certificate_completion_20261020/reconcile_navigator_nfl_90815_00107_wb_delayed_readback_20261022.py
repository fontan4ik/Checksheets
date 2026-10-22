from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import comparable_card,norm_number
OFFERS=['14147-1','14148-1','14149-1','14150-1','80671-1','80672-1','80673-1','80674-1','80675-1','80677-1','80678-1']
WANTED={'declaration':{'number':'ЕАЭС N RU Д-RU.РА11.В.90815/24','type':2,'startDate':'2024-12-27','endDate':'2029-12-25'},'certificate':{'number':'ЕАЭС RU С-RU.НВ28.В.00107/24','type':1,'startDate':'2024-12-24','endDate':'2029-12-23'}}
BEFORE=json.loads((HERE/'navigator_nfl_90815_00107_wb_before_20261022.json').read_text())
before={x['offer_id']:x['card'] for x in BEFORE['cards']}
c=Client();rows=[];counts=collections.Counter();failures=[]
for offer in OFFERS:
 cards=c.wb_cards(offer)
 if len(cards)!=1:
  failures.append({'offer_id':offer,'problem':'card_count','count':len(cards)});continue
 card=cards[0]; docs=((card.get('documents') or {}).get('items') or [])
 exact={}
 for key,w in WANTED.items():
  matches=[d for d in docs if norm_number(d.get('number'))==norm_number(w['number'])]
  matches=[d for d in matches if int(d.get('type') or 0)==w['type'] and str(d.get('startDate',''))[:10]==w['startDate'] and str(d.get('endDate',''))[:10]==w['endDate'] and d.get('isEndless') is False]
  exact[key]=matches
  if len(matches)==1:
   v=matches[0].get('verdict') or {}
   status='valid' if v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' else 'pending_or_unverified'
   counts[f'{key}:{status}']+=1
  else: status='missing_or_duplicate';counts[f'{key}:{status}']+=1;failures.append({'offer_id':offer,'problem':status,'document':key,'count':len(matches)})
 original=before.get(offer)
 preserved=(original is not None and comparable_card(original)==comparable_card(card))
 if not preserved:failures.append({'offer_id':offer,'problem':'non_document_card_fields_changed'})
 rows.append({'offer_id':offer,'nmID':str(card.get('nmID')),'vendorCode':card.get('vendorCode'),'brand':card.get('brand'),'title':card.get('title'),'exact_documents':{k:[{x:d.get(x) for x in ('type','number','startDate','endDate','isEndless','verdict')} for d in v] for k,v in exact.items()},'non_document_fields_preserved':preserved})
result={'checked_at_utc':now(),'complete':len(rows)==len(OFFERS),'target_cards':len(OFFERS),'cards_read':len(rows),'document_status_counts':dict(counts),'failures':failures,'cards':rows,'wb_review_state_left_untouched':True,'local_source_files_deleted':False}
out=HERE/'navigator_nfl_90815_00107_wb_delayed_readback_20261022.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='cards'},ensure_ascii=False,indent=2))
