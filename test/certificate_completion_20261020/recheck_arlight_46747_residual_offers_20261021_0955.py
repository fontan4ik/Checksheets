from __future__ import annotations
import json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(API))
from api_client import Client,now
OUT=HERE/'arlight_46747_residual_offers_20261021_0955.json'
if OUT.exists(): raise RuntimeError('output_exists')
client=Client()
product_id=608926685
response=client.call('ozon','/v3/product/info/list',{'product_id':[product_id]})
items=response.get('items')
if not isinstance(items,list): raise RuntimeError('Ozon product info response missing items')
products=[x for x in items if str(x.get('product_id') or x.get('id') or '')==str(product_id)]
if len(products)!=1: raise RuntimeError(f'Ozon product identity mismatch: {len(products)}')
p=products[0]
attrs=[]
for a in p.get('attributes') or []:
 name=str(a.get('name') or a.get('attribute_name') or '')
 values=a.get('values') or a.get('value')
 attrs.append({'name':name,'values':values})
relevant=[a for a in attrs if any(x in a['name'].casefold() for x in ('дата','изготов','парт','manufactur','date','batch'))]
wb=client.wb_cards('045399-1')
result={'checked_at':now(),'read_only':True,'number':'ЕАЭС RU С-CN.АЯ46.В.46747/26','certificate_id':5445163,'sample_date_cutoff':'2026-01','candidate_offer':'029543(1)-1','ozon_product':{'product_id':str(p.get('product_id') or p.get('id') or ''),'offer_id':str(p.get('offer_id') or ''),'sku':str(p.get('sku') or ''),'name':p.get('name') or p.get('name_ru'),'created_at':p.get('created_at'),'relevant_date_or_batch_attributes':relevant,'attribute_count':len(attrs)},'wb_missing_offer':'045399-1','wb_exact_card_count':len(wb),'wb_cards':[{'nmID':str(x.get('nmID') or ''),'vendorCode':x.get('vendorCode'),'brand':x.get('brand'),'title':x.get('title')} for x in wb],'mutation_performed':False,'local_files_deleted':False}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
