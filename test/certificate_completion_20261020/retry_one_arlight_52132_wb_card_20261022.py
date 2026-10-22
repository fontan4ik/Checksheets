from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import comparable_card,norm_number
from run_all_found_certificates_20261014 import merge_wb
from apply_arlight_52132_wb_20261020 import code_values
NUMBER='ЕАЭС N RU Д-CN.РА09.В.52132/25';ISSUE='2025-10-22';EXPIRY='2030-10-20'
ALLOWED={'9405110013','9405110033','9405110039','9405420012','9405420032','9405420039'}
READBACK=HERE/'arlight_52132_wb_delayed_recheck_20261022.json'
PREV=HERE/'arlight_52132_wb_uncovered_before_20261022.json'
JOURNAL=HERE/'arlight_52132_wb_individual_retry_journal_20261022.jsonl'
OUT=HERE/'arlight_52132_wb_individual_retry_20261022.json'
def save(v):
 t=OUT.with_suffix('.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');t.replace(OUT)
def main():
 if JOURNAL.exists() or OUT.exists():raise RuntimeError('individual retry artifact already exists; reconcile before rerun')
 rb=json.loads(READBACK.read_text()); unresolved=[x for x in rb['results'] if x['status']=='document_not_visible']
 if len(unresolved)!=39:raise RuntimeError(f'unexpected unresolved count {len(unresolved)}')
 offer=unresolved[0]['offer_id']; expected=unresolved[0]['nmID']
 old=json.loads(PREV.read_text())['cards'].get(offer)
 if not old or str(old.get('nmID'))!=expected:raise RuntimeError('before-snapshot identity mismatch')
 client=Client();cards=[x for x in client.wb_cards(offer) if x.get('vendorCode')==offer]
 if len(cards)!=1:raise RuntimeError('fresh card missing or duplicate')
 card=cards[0];tnved=set(code_values(card))
 if str(card.get('nmID'))!=expected or str(card.get('brand') or '').strip().casefold()!='arlight' or not tnved or not tnved<=ALLOWED:raise RuntimeError('fresh identity or TNVED scope mismatch')
 if comparable_card(old)!=comparable_card(card):raise RuntimeError('non-document card fields changed since captured snapshot')
 docs=[x for x in ((card.get('documents') or {}).get('items') or []) if norm_number(x.get('number'))==norm_number(NUMBER)]
 if docs:raise RuntimeError('document already present or metadata conflict; no write')
 wanted={'type':2,'number':NUMBER,'startDate':f'{ISSUE}T00:00:00Z','endDate':f'{EXPIRY}T00:00:00Z','isEndless':False}
 payload=merge_wb(card,[wanted]);encoded=json.dumps([payload],ensure_ascii=False,separators=(',',':')).encode()
 if not payload or len(encoded)>9_500_000:raise RuntimeError('payload empty or too large')
 digest=hashlib.sha256(encoded).hexdigest()
 entry={'key':f'wb:52132:uncovered:individual:{card["nmID"]}:{digest}','phase':'prepared','at':now(),'offer_id':offer,'nmID':str(card['nmID']),'payload_sha256':digest,'payload_bytes':len(encoded),'tnved_codes':sorted(tnved)}
 JOURNAL.write_text(json.dumps(entry,ensure_ascii=False)+'\n')
 response=client.call('wb','/content/v2/cards/update',[payload],mutation=True)
 with JOURNAL.open('a') as f:f.write(json.dumps({**entry,'phase':'response','response':response,'finished_at':now()},ensure_ascii=False)+'\n')
 if response.get('error') is not False:raise RuntimeError('individual update rejected; inspect journal')
 fresh=[x for x in client.wb_cards(offer) if x.get('vendorCode')==offer]
 if len(fresh)!=1:status='missing_or_duplicate_after_write';exact=False;unchanged=False;rows=[]
 else:
  after=fresh[0];rows=[x for x in ((after.get('documents') or {}).get('items') or []) if norm_number(x.get('number'))==norm_number(NUMBER)]
  exact=(len(rows)==1 and str(rows[0].get('type'))=='2' and str(rows[0].get('startDate',''))[:10]==ISSUE and str(rows[0].get('endDate',''))[:10]==EXPIRY)
  unchanged=comparable_card(card)==comparable_card(after)
  status='verified_exact' if exact and unchanged else 'document_not_visible' if not rows else 'metadata_or_non_document_conflict'
 result={'checked_at_utc':now(),'number':NUMBER,'offer_id':offer,'nmID':str(card['nmID']),'update_response':response,'status':status,'exact_metadata':exact,'non_document_fields_unchanged':unchanged,'document_rows':rows,'wb_review_left_pending':True,'local_source_deleted':False}
 save(result);print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
