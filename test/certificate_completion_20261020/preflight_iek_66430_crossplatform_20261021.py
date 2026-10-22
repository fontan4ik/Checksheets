"""Read-only live preflight for the one exact IEK 66430/26 offer."""
from __future__ import annotations
import collections,hashlib,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import copy_documents,norm_number,doc_key
MAN=json.loads((HERE/'expanded_found_certificates_manifest_20261020.json').read_text())
g=next(x for x in MAN['groups'] if x['number']=='RU Д-CN.РА02.В.66430/26')
NUM='ЕАЭС N RU Д-CN.РА02.В.66430/26'; ISSUE='2026-03-18'; EXP='2027-10-17'; TNV={'8536201007'}
SRC=pathlib.Path(g['upload_file']['path']); OUT=HERE/'iek_66430_preflight_live_20261021.json'
if OUT.exists(): raise RuntimeError('output_exists')
targets=g['targets']; assert len(targets)==1
c=Client(); offers=[x['offer_id'] for x in targets]
products=c.call('ozon','/v3/product/info/list',{'offer_id':offers}).get('items')
attrs=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':len(offers)}).get('result')
if len(products or [])!=1 or len(attrs or [])!=1: raise RuntimeError('ozon_target_refresh_incomplete')
p=products[0]; a=attrs[0]; attr={str(x.get('id')):x for x in a.get('attributes') or []}
brand=[str(x.get('value') or '').strip() for x in (attr.get('85') or {}).get('values') or []]
tnv=sorted({str(x.get('value') or '').split(' - ',1)[0].strip() for x in (attr.get('22232') or {}).get('values') or [] if x.get('value')})
product_ok=(str(p.get('product_id') or p.get('id') or '')==str(targets[0]['product_id']) and str(p.get('sku') or '')==str(targets[0]['sku']) and p.get('is_archived') is False and brand==['IEK'] and tnv==sorted(TNV) and 'выключател' in str(p.get('name') or '').casefold())
certs=[]
for page in range(1,101):
 res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
 batch=res.get('certificates')
 if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_invalid')
 certs.extend(x for x in batch if norm_number(x.get('certificate_number'))==norm_number(NUM))
 if not batch or page>=int(res.get('page_count') or 0): break
else: raise RuntimeError('ozon_certificate_pages_limit')
records=[]
for rec in certs:
 info=c.call('ozon','/v1/product/certificate/info',{'certificate_number':rec.get('certificate_number')}).get('result') or {}
 binds=c.ozon_bindings(int(info.get('certificate_id') or rec.get('certificate_id')))
 records.append({'info':info,'bindings':binds})
wb=c.wb_cards(offers[0]); wb_row=None
if len(wb)==1:
 card=wb[0]; docs=copy_documents(card); same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUM)]
 exact=[d for d in same if int(d.get('type') or 0)==2 and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXP and d.get('isEndless') is False]
 card_tnv=[]
 for item in card.get('characteristics') or []:
  name=''.join(str(item.get('name') or '').casefold().split()).replace('ё','е')
  if 'тнвэд' in name or 'тнвед' in name:
   raw=item.get('value'); vals=raw if isinstance(raw,list) else [raw]
   card_tnv.extend(str(v or '').split(' - ',1)[0].strip() for v in vals if v)
 title=str(card.get('title') or '')
 wb_ok=(str(card.get('vendorCode') or '')==offers[0] and str(card.get('brand') or '').strip().casefold()=='iek' and 'выключател' in title.casefold() and (not card_tnv or set(card_tnv)<=TNV))
 wb_row={'nmID':str(card.get('nmID') or ''),'title':title,'brand':card.get('brand'),'tnved_codes':sorted(set(card_tnv)),'identity_and_scope_ok':wb_ok,'existing_same_number_count':len(same),'existing_exact_document':len(exact)==1,'existing_document_status':(exact[0].get('verdict') if len(exact)==1 else None),'full_card':card}
result={'checked_at':now(),'read_only':True,'number':NUM,'fsa':{'record_id':21245281,'status':'active','issue_date':ISSUE,'expiry_date':EXP,'scope':'IEK KARAT/Home AVDT32/34','tnved':['8536201007'],'scheme':'1d','release':'serial production','url':'https://pub.fsa.gov.ru/rds/declaration/view/21245281/product'},'source_pdf':str(SRC),'source_pdf_sha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'manifest_source_sha256':g['upload_file']['sha256'],'targets':targets,'ozon_product':{'offer_id':offers[0],'product_id':str(p.get('product_id') or p.get('id') or ''),'sku':str(p.get('sku') or ''),'name':p.get('name'),'brand_values':brand,'tnved_codes':tnv,'identity_and_scope_ok':product_ok},'ozon_records':records,'wb_card_count':len(wb),'wb_target':wb_row,'local_file_deleted':False}
result['eligible_for_missing_link_completion']=bool(product_ok and len(records)<=1 and (not records or records[0]['info'].get('status_code')=='approved') and len(wb)==1 and wb_row and wb_row['identity_and_scope_ok'] and (not wb_row['existing_same_number_count'] or wb_row['existing_exact_document']))
tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2));tmp.replace(OUT)
print(json.dumps({k:v for k,v in result.items() if k not in {'targets','ozon_records','wb_target'}},ensure_ascii=False,indent=2))
if not result['eligible_for_missing_link_completion']: raise RuntimeError('preflight_not_eligible')
