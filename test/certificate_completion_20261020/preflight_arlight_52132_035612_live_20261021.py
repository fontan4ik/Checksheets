#!/usr/bin/env python3
"""Read-only current preflight for missed exact Arlight 52132/25 assignment."""
from __future__ import annotations
import json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number
OFF='035612-1';NUMBER='ЕАЭС N RU Д-CN.РА09.В.52132/25';OUT=HERE/'arlight_52132_035612_live_preflight_20261021.json'
def vals(a,aid):
 m={str(x.get('id')):x for x in a.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (m.get(str(aid)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def main():
 if OUT.exists():raise RuntimeError('output_exists_inspect_before_retry')
 c=Client();ps=c.call('ozon','/v3/product/info/list',{'offer_id':[OFF]}).get('items') or []; ats=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':[OFF]},'limit':1}).get('result') or []
 if len(ps)!=1 or len(ats)!=1:raise RuntimeError('Ozon product data incomplete')
 p,a=ps[0],ats[0]; certs=[]
 for pg in range(1,101):
  body=c.call('ozon','/v1/product/certificate/list',{'page':pg,'page_size':100}).get('result') or {};batch=body.get('certificates')
  if not isinstance(batch,list):raise RuntimeError('certificate page incomplete')
  certs.extend(batch)
  if len(batch)<100:break
 else:raise RuntimeError('certificate page limit')
 found=[x for x in certs if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 if len(found)!=1:raise RuntimeError(f'exact certificate count {len(found)}')
 rec=found[0];bindings=c.ozon_bindings(int(rec['certificate_id']));pid=str(p.get('product_id') or p.get('id') or '');sku=str(p.get('sku') or '')
 bound=[x for x in bindings if str(x.get('product_id'))==pid]
 wb=c.wb_cards(OFF)
 if len(wb)>1:raise RuntimeError('WB target card ambiguous')
 card=wb[0] if wb else None; docs=((card or {}).get('documents') or {}).get('items') or []
 exact=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
 result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'fsa_record_url':'https://pub.fsa.gov.ru/rds/declaration/view/20749531/common','offer_id':OFF,'ozon_product':{'product_id':pid,'expected_product_id':'4030879075','sku':sku,'expected_sku':'3859305981','name':p.get('name'),'is_archived':p.get('is_archived'),'brand_values':vals(a,85),'tnved_values':vals(a,22232),'tnved_codes':sorted({str(x).split(' - ',1)[0].strip() for x in vals(a,22232)}),'identity_exact':pid=='4030879075' and sku=='3859305981'},'ozon_record':{k:rec.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date','accordance_type_code','products_count')},'ozon_binding_count':len(bound),'ozon_binding_rows':bound,'wb_card_found':bool(card),'wb_card':None if card is None else {'nmID':str(card.get('nmID')),'vendorCode':card.get('vendorCode'),'brand':card.get('brand'),'title':card.get('title'),'matching_docs':[{'type':d.get('type'),'number':d.get('number'),'startDate':d.get('startDate'),'endDate':d.get('endDate'),'verdict':d.get('verdict')} for d in exact]}}
 tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
 print(json.dumps({'preflight':str(OUT),'checked_at_utc':result['checked_at_utc'],'ozon_product':result['ozon_product'],'ozon_record':result['ozon_record'],'ozon_binding_count':len(bound),'wb_card':result['wb_card']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
