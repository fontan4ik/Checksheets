"""Remove one unsupported Gauss product/document pair from both marketplaces."""
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]; API=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(API))
from api_client import Client,now,save
from reconcile_approved_ozon_docs_to_wb import norm_number,copy_documents,doc_key,comparable_card,UPDATE_CARD_FIELDS

OFFER='613100150P-2'; PRODUCT_ID='3084920081'; SKU='3124680447'; NMID='669266414'; CERT_ID=5948463
NUMBER='ЕАЭС RU С-CN.НВ54.В.02947/22'; ISSUE='2022-06-08'; EXPIRY='2027-06-07'
JOURNAL=HERE/'gauss_02947_613100150P_correction_journal_20261023.jsonl'
OUT=HERE/'gauss_02947_613100150P_correction_readback_20261023.json'

def append(row):
 with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush()
def is_target(d):
 return (doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate') or '')[:10]==ISSUE and str(d.get('endDate') or '')[:10]==EXPIRY)
def wbitems(c):return ((c.get('documents') or {}).get('items') or [])

def main():
 if JOURNAL.exists() or OUT.exists(): raise RuntimeError('Correction artifacts exist; inspect before any retry')
 c=Client()
 pr=c.call('ozon','/v3/product/info/list',{'offer_id':[OFFER]}).get('items') or []
 if len(pr)!=1 or str(pr[0].get('id') or pr[0].get('product_id'))!=PRODUCT_ID or str(pr[0].get('sku'))!=SKU: raise RuntimeError('Ozon exact product identity changed')
 recs=[]
 for page in range(1,100):
  result=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; batch=result.get('certificates')
  if not isinstance(batch,list): raise RuntimeError('Malformed certificate list')
  recs.extend(batch)
  if len(batch)<100: break
 else: raise RuntimeError('Certificate pagination exceeded')
 cert=[r for r in recs if str(r.get('certificate_id'))==str(CERT_ID)]
 if len(cert)!=1 or cert[0].get('status_code')!='approved' or norm_number(cert[0].get('certificate_number'))!=norm_number(NUMBER): raise RuntimeError('Exact approved record changed')
 bindings=c.ozon_bindings(CERT_ID); target=[b for b in bindings if str(b.get('product_id'))==PRODUCT_ID]
 if len(target)!=1 or str(target[0].get('sku'))!=SKU or target[0].get('product_status_code')!='approved': raise RuntimeError('No exact approved binding to correct')
 cards=[x for x in c.wb_cards(OFFER) if x.get('vendorCode')==OFFER]
 if len(cards)!=1 or str(cards[0].get('nmID'))!=NMID: raise RuntimeError('WB exact card identity changed')
 card=cards[0]; docs=wbitems(card); matches=[d for d in docs if is_target(d)]
 if len(matches)!=1 or (matches[0].get('verdict') or {}).get('reason')!='valid': raise RuntimeError('WB target document row absent/ambiguous or verdict changed')
 kept=[x for x in copy_documents(card) if not is_target(x)]
 payload={k:card[k] for k in UPDATE_CARD_FIELDS if k in card}
 payload['documents']={'items':kept,'excludeDocuments':False}
 
 for field in UPDATE_CARD_FIELDS:
  if field!='documents' and field in card and payload.get(field)!=card[field]: raise RuntimeError('WB writable non-document field would change: '+field)
 pre={'checked_at_utc':now(),'read_only':True,'offer_id':OFFER,'product_id':PRODUCT_ID,'sku':SKU,'wb_nmID':NMID,'certificate_id':CERT_ID,'certificate_number':cert[0].get('certificate_number'),'scope_evidence':'The scanned certificate annex lists model 613100150 but not 613100150P. The product identity is 613100150P; do not infer P variant coverage.','ozon_binding_before':target[0],'wb_document_before':matches[0]}
 save(OUT.name,{'phase':'preflight','preflight':pre})
 append({'phase':'prepared','platform':'wb','endpoint':'/content/v2/cards/update','offer_id':OFFER,'nmID':NMID,'payload_sha256':hashlib.sha256(json.dumps([payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'at_utc':now()})
 wbresp=c.call('wb','/content/v2/cards/update',[payload],mutation=True)
 append({'phase':'response','platform':'wb','response':wbresp,'at_utc':now()})
 if wbresp.get('error') is not False: raise RuntimeError('WB correction not accepted; reconcile before retry')
 fresh=[x for x in c.wb_cards(OFFER) if x.get('vendorCode')==OFFER]
 if len(fresh)!=1 or str(fresh[0].get('nmID'))!=NMID: raise RuntimeError('WB card readback missing/changed')
 if any(is_target(d) for d in wbitems(fresh[0])): raise RuntimeError('WB document removal not yet visible; do not retry')
 wb_absent=True; prior=copy_documents(card); after=copy_documents(fresh[0])
 prior_kept=[x for x in prior if not is_target(x)]
 prior_preserved=all(any(doc_key(y)==doc_key(x) and str(y.get('startDate',''))[:10]==str(x.get('startDate',''))[:10] and str(y.get('endDate',''))[:10]==str(x.get('endDate',''))[:10] for y in after) for x in prior_kept)
 unrelated=comparable_card(card)==comparable_card(fresh[0])
 if not prior_preserved or not unrelated: raise RuntimeError('WB unrelated/pre-existing data preservation check failed')
 append({'phase':'prepared','platform':'ozon','endpoint':'/v1/product/certificate/unbind','certificate_id':CERT_ID,'product_ids':[PRODUCT_ID],'at_utc':now()})
 ozresp=c.call('ozon','/v1/product/certificate/unbind',{'certificate_id':CERT_ID,'product_id':[PRODUCT_ID]},mutation=True)
 append({'phase':'response','platform':'ozon','response':ozresp,'at_utc':now()})
 after_bindings=c.ozon_bindings(CERT_ID)
 oz_absent=not any(str(b.get('product_id'))==PRODUCT_ID for b in after_bindings)
 if not oz_absent: raise RuntimeError('Ozon target binding remains; do not retry')
 result={'checked_at_utc':now(),'phase':'corrected','reason':'Exact model 613100150P is not listed in the certificate annex; only 613100150 is.','ozon':{'unbind_response':ozresp,'target_binding_absent':oz_absent},'wb':{'update_response':wbresp,'target_document_absent':wb_absent,'prior_documents_preserved':prior_preserved,'unrelated_fields_preserved':unrelated,'remaining_documents':after},'certificate_record_kept':True,'local_source_deleted':False}
 save(OUT.name,result)
 print(json.dumps({'output':str(OUT),'phase':result['phase'],'ozon_unbound':oz_absent,'wb_document_removed':wb_absent,'other_wb_documents_preserved':prior_preserved,'unrelated_fields_preserved':unrelated},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
