#!/usr/bin/env python3
"""Read-only fresh preflight for the three approved Stekker docs assigned to 50831-1."""
from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number
OFF='50831-1'; NUMBERS=['RU Д-CN.PA06.B.58663/25','RU Д-CN.PA01.В.08463/26','RU C-CN.ИП18.B.00156/21']
OUT=HERE/'stekker_50831_live_preflight_20261021.json'
def val(a,aid):
 m={str(x.get('id')):x for x in a.get('attributes') or []}
 return [str(x.get('value') or '').strip() for x in (m.get(str(aid)) or {}).get('values') or [] if str(x.get('value') or '').strip()]
def main():
 if OUT.exists():raise RuntimeError('output_exists_inspect_first')
 c=Client();pbody=c.call('ozon','/v3/product/info/list',{'offer_id':[OFF]}).get('items') or []
 abody=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':[OFF]},'limit':1}).get('result') or []
 if len(pbody)!=1 or len(abody)!=1:raise RuntimeError('Ozon product or attributes response incomplete')
 product,attrs=pbody[0],abody[0]
 certs=[]
 for page in range(1,101):
  res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {};batch=res.get('certificates')
  if not isinstance(batch,list):raise RuntimeError('certificate list incomplete')
  certs.extend(batch)
  if len(batch)<100:break
 else:raise RuntimeError('certificate list limit')
 target=[]
 for number in NUMBERS:
  found=[x for x in certs if norm_number(x.get('certificate_number'))==norm_number(number)]
  if len(found)!=1:target.append({'requested_number':number,'record_count':len(found),'records':found});continue
  rec=found[0];binds=c.ozon_bindings(int(rec['certificate_id']));existing=[x for x in binds if str(x.get('product_id'))==str(product.get('product_id') or product.get('id'))]
  target.append({'requested_number':number,'certificate_id':rec.get('certificate_id'),'actual_number':rec.get('certificate_number'),'type_code':rec.get('type_code'),'status_code':rec.get('status_code'),'issue_date':rec.get('issue_date'),'expire_date':rec.get('expire_date'),'accordance_type_code':rec.get('accordance_type_code'),'product_count':rec.get('products_count'),'target_binding_count':len(existing),'target_binding_rows':existing})
 wb=c.wb_cards(OFF)
 if len(wb)>1:raise RuntimeError('WB exact card ambiguous')
 wbrow=None
 if wb:
  card=wb[0];docs=(card.get('documents') or {}).get('items') or []
  wbrow={'nmID':str(card.get('nmID')),'brand':card.get('brand'),'vendorCode':card.get('vendorCode'),'title':card.get('title'),'docs':[{'type':d.get('type'),'number':d.get('number'),'startDate':d.get('startDate'),'endDate':d.get('endDate'),'verdict':d.get('verdict')} for d in docs if any(norm_number(d.get('number'))==norm_number(n) for n in NUMBERS)]}
 res={'checked_at_utc':now(),'read_only':True,'offer_id':OFF,'ozon_product':{'product_id':str(product.get('product_id') or product.get('id') or ''),'sku':str(product.get('sku') or ''),'name':product.get('name'),'is_archived':product.get('is_archived'),'brand_values':val(attrs,85),'tnved_values':val(attrs,22232),'tnved_codes':sorted({str(x).split(' - ',1)[0].strip() for x in val(attrs,22232)})},'ozon_documents':target,'wb_card_found':bool(wb),'wb_card':wbrow}
 tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
 print(json.dumps({'preflight':str(OUT),'checked_at_utc':res['checked_at_utc'],'ozon_product':res['ozon_product'],'documents':[{'number':x['requested_number'],'id':x.get('certificate_id'),'status':x.get('status_code'),'missing_target_link':x.get('target_binding_count')==0} for x in target],'wb_card_found':bool(wb),'wb_docs':wbrow and wbrow['docs']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
