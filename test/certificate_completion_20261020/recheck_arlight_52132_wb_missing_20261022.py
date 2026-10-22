from __future__ import annotations
import collections,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import comparable_card,norm_number
from apply_arlight_52132_wb_20261020 import code_values
NUMBER='ЕАЭС N RU Д-CN.РА09.В.52132/25'
ISSUE='2025-10-22';EXPIRY='2030-10-20';ALLOWED={'9405110013','9405110033','9405110039','9405420012','9405420032','9405420039'}
BEFORE=json.loads((HERE/'arlight_52132_wb_uncovered_before_20261022.json').read_text())['cards']
PREV=json.loads((HERE/'arlight_52132_wb_uncovered_retry_targeted_readback_20261022.json').read_text())
OFFERS=[r['offer_id'] for r in PREV['results'] if r.get('status')=='document_not_visible']
OUT=HERE/'arlight_52132_wb_delayed_recheck_20261022.json'
def main():
 c=Client();rows=[]
 for i,offer in enumerate(OFFERS,1):
  cards=[x for x in c.wb_cards(offer) if x.get('vendorCode')==offer]
  if len(cards)!=1:
   rows.append({'offer_id':offer,'status':'missing_or_duplicate_card','card_count':len(cards)})
  else:
   card=cards[0];docs=[x for x in ((card.get('documents') or {}).get('items') or []) if norm_number(x.get('number'))==norm_number(NUMBER)]
   exact=(len(docs)==1 and str(docs[0].get('type'))=='2' and str(docs[0].get('startDate',''))[:10]==ISSUE and str(docs[0].get('endDate',''))[:10]==EXPIRY)
   verdict=docs[0].get('verdict') if docs else None
   prior=BEFORE.get(offer) or {}
   identity=(str(card.get('nmID') or '')==str(prior.get('nmID') or '') and str(card.get('brand') or '').casefold()=='arlight')
   unchanged=comparable_card(prior)==comparable_card(card)
   tnved=sorted(set(code_values(card)))
   rows.append({'offer_id':offer,'nmID':str(card.get('nmID')),'brand':card.get('brand'),'tnved_codes':tnved,'status':'verified_exact' if exact and identity and unchanged else 'document_not_visible' if not docs else 'metadata_or_identity_conflict','exact_metadata':exact,'identity_exact':identity,'non_document_fields_unchanged':unchanged,'verdict':verdict,'document_rows':docs,'tnved_allowed':bool(tnved) and set(tnved)<=ALLOWED})
  if i%10==0:print(f'delayed WB readback {i}/{len(OFFERS)}',flush=True)
 counts=collections.Counter(x['status'] for x in rows)
 valid=sum(x['status']=='verified_exact' and (x.get('verdict') or {}).get('verified') is True and (x.get('verdict') or {}).get('status')==1 and (x.get('verdict') or {}).get('reason')=='valid' for x in rows)
 out={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'target_count':len(rows),'status_counts':dict(counts),'valid_verdicts':valid,'results':rows,'wb_review_left_pending':True,'local_source_deleted':False}
 tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
 print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
