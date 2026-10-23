#!/usr/bin/env python3
"""Read-only exact-product preflight for Jazzway BSPS 12V documents."""
from __future__ import annotations
import collections, csv, hashlib, json, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number

OFFER='3329358-1'
DOCS=[
 {'number':'ЕАЭС N RU Д-HK.РА08.В.69871/24','type':'declaration','issue':'2024-09-24','expiry':'2029-09-23','source':'output_to_user/certificates/additional_search/brand_research/jazzway/followup_2026_10_02/jazzway_driver_037_2029.pdf','sha':'ab6ec523525995a0114a526df28d1fc93497d4bdb4a90f911e566bd8e6535a1e'},
 {'number':'ЕАЭС RU C-HK.НВ90.В.00268/24','type':'certificate_of_conformity','issue':'2024-09-24','expiry':'2029-09-23','source':'output_to_user/certificates/additional_search/brand_research/jazzway/followup_2026_10_02/jazzway_driver_004_020_2029.pdf','sha':'956b78369981ad73a13d14d30e335118204936d5c873c02c65415faf7f3379ab'}]

def values(attrs, ident):
 by={str(x.get('id')):x for x in attrs or []}
 return [str(v.get('value') or '').strip() for v in (by.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]

def records(c):
 out=[]
 for page in range(1,101):
  res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
  batch=res.get('certificates')
  if not isinstance(batch,list): raise RuntimeError('ozon_cert_list_invalid')
  out+=batch
  if not batch or page>=int(res.get('page_count') or 0): return out
 raise RuntimeError('ozon_cert_list_page_limit')

def main():
 assignments=[]
 with (ROOT/'output_to_user/certificates/document_assignments.csv').open(newline='',encoding='utf-8-sig') as f:
  assignments=[r for r in csv.DictReader(f) if r.get('Артикул продавца')==OFFER and any(d['number']==r.get('Номер/название документа') for d in DOCS)]
 if len(assignments)!=2: raise RuntimeError('assignment_count_mismatch:'+str(len(assignments)))
 for doc in DOCS:
  p=ROOT/doc['source']
  if hashlib.sha256(p.read_bytes()).hexdigest()!=doc['sha']: raise RuntimeError('source_sha_mismatch:'+doc['number'])
 client=Client()
 products=client.call('ozon','/v3/product/info/list',{'offer_id':[OFFER]}).get('items') or []
 attrs=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':[OFFER]},'limit':1}).get('result') or []
 if len(products)!=1 or len(attrs)!=1: raise RuntimeError('ozon_product_missing_or_ambiguous')
 product,attribute=products[0],attrs[0]
 brand=values(attribute.get('attributes'),85); tnved=values(attribute.get('attributes'),22232)
 existing=records(client)
 ozon_matches={d['number']:[{k:r.get(k) for k in ['certificate_id','certificate_number','type_code','status_code','issue_date','expire_date']} for r in existing if norm_number(r.get('certificate_number'))==norm_number(d['number'])] for d in DOCS}
 wb=client.wb_cards(OFFER)
 cards=[x for x in wb if str(x.get('vendorCode') or '')==OFFER]
 wb_result=[]
 if len(cards)==1:
  card=cards[0]
  docs=(card.get('documents') or {}).get('items') or []
  for d in DOCS:
   same=[x for x in docs if norm_number(x.get('number'))==norm_number(d['number'])]
   wb_result.append({'number':d['number'],'same_number_items':same,'exact_count':sum(1 for x in same if str(x.get('type'))==('2' if d['type']=='declaration' else '1') and str(x.get('startDate') or '')[:10]==d['issue'] and str(x.get('endDate') or '')[:10]==d['expiry'] and x.get('isEndless') is False)})
 report={'checked_at_utc':now(),'read_only':True,'offer_id':OFFER,'assignment_rows':assignments,
  'ozon_product':{'product_id':str(product.get('product_id') or product.get('id') or ''),'sku':str(product.get('sku') or ''),'name':product.get('name'),'is_archived':product.get('is_archived'),'brand':brand,'tnved':tnved},
  'ozon_document_matches':ozon_matches,'wb_card_count':len(cards),'wb_card':{k:cards[0].get(k) for k in ['vendorCode','nmID','brand','title','tnved']} if len(cards)==1 else None,
  'wb_document_matches':wb_result,'sample_date_issue':'Both originals refer to manufacturing date in sampling act; the date visible in those copies is 08.2024 and individual lot dates were not available.',
  'writes_performed':False,'local_files_deleted':False}
 out=HERE/'jazzway_driver_3329358_preflight_20261023.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
