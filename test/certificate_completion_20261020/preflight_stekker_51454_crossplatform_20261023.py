#!/usr/bin/env python3
"""Read-only preflight for exact Stekker 51454 voluntary-certificate targets."""
from __future__ import annotations
import csv,datetime as dt,hashlib,json,sys,collections
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number
NUMBER='РОСС RU.32001.04ИБФ1.ОСП28.51454';ISSUE='2024-04-17';EXPIRY='2027-04-16'
SOURCE=ROOT/'output_to_user/certificates/additional_search/docs/stekker/feron_store/51454_Наконечники_гильзы_кабельные_Добровольный_сертификат.jpg'
SHA=''

def code_values(attrs,ident):
 by={str(x.get('id')):x for x in attrs or []}
 return [str(v.get('value') or '').strip() for v in (by.get(str(ident)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def all_ozon_records(c):
 out=[]
 for p in range(1,101):
  d=c.call('ozon','/v1/product/certificate/list',{'page':p,'page_size':100}).get('result') or {};b=d.get('certificates')
  if not isinstance(b,list):raise RuntimeError('invalid_certificate_list')
  out+=b
  if not b or p>=int(d.get('page_count') or 0):return out
 raise RuntimeError('ozon_page_limit')
def main():
 global SHA
 SHA=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
 rows=[]
 with (ROOT/'output_to_user/certificates/document_assignments.csv').open(newline='',encoding='utf-8-sig') as f:
  rows=[x for x in csv.DictReader(f) if x.get('Номер/название документа')==NUMBER]
 if len(rows)!=55 or len({x['Артикул продавца'] for x in rows})!=55:raise RuntimeError(f'assignment_target_count:{len(rows)}')
 for x in rows:
  if x['Тип документа']!='Добровольный сертификат соответствия' or x['Применимость']!='Подтверждено источником' or x['SHA256 фактический']!=SHA or x['Аудит файла']!='SHA-256 совпадает':raise RuntimeError('source_assignment_metadata_conflict:'+x['Артикул продавца'])
 client=Client(); offers=sorted(x['Артикул продавца'] for x in rows)
 products={};attrs={}
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]
  for x in client.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []:products.setdefault(str(x.get('offer_id') or ''),[]).append(x)
  for x in client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or []:attrs.setdefault(str(x.get('offer_id') or ''),[]).append(x)
 targets=[]
 for row in rows:
  offer=row['Артикул продавца'];pp=products.get(offer,[]);aa=attrs.get(offer,[]);block=[];pr=pp[0] if len(pp)==1 else {};ar=aa[0] if len(aa)==1 else {}
  if len(pp)!=1 or len(aa)!=1:block.append('ozon_product_missing_or_ambiguous')
  brand=[x.casefold() for x in code_values(ar.get('attributes'),85)]
  tnved=[x.split(' - ',1)[0].strip() for x in code_values(ar.get('attributes'),22232)]
  expected=offer.rsplit('-',1)[0]
  if pr.get('is_archived') is not False:block.append('ozon_not_active')
  if brand!=['stekker']:block.append('ozon_brand_mismatch:'+','.join(brand))
  if expected not in str(pr.get('name') or '') and expected not in row['Основание сопоставления']:block.append('ozon_article_or_model_not_visible')
  targets.append({'offer_id':offer,'product_id':str(pr.get('product_id') or pr.get('id') or ''),'sku':str(pr.get('sku') or ''),'ozon_name':pr.get('name'),'ozon_brand':brand,'ozon_tnved':tnved,'source_name':row['Название товара Ozon'],'source_url':row['URL карточки/основания'],'wb_nmID':None,'wb_brand':None,'wb_tnved':None,'wb_name':None,'wb_exact_preexisting':None,'ozon_blockers':block,'wb_blockers':[]})
 records=all_ozon_records(client);same=[x for x in records if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 record_result=[]
 for r in same:record_result.append({'certificate_id':str(r.get('certificate_id')),'number':r.get('certificate_number'),'type_code':r.get('type_code'),'accordance_type_code':r.get('accordance_type_code'),'status_code':r.get('status_code'),'issue_date':str(r.get('issue_date') or '')[:10],'expire_date':str(r.get('expire_date') or '')[:10]})
 ozon_safe={x['offer_id'] for x in targets if not x['ozon_blockers']}
 wb_safe=set();wb_count=collections.Counter()
 for t in targets:
  cards=client.wb_cards(t['offer_id'])
  if len(cards)!=1: t['wb_blockers'].append('wb_card_missing_or_ambiguous');continue
  card=cards[0];t['wb_nmID']=str(card.get('nmID') or '');t['wb_brand']=str(card.get('brand') or '');t['wb_tnved']=card.get('tnved');t['wb_name']=card.get('title') or card.get('subject')
  if str(card.get('brand') or '').strip().casefold()!='stekker':t['wb_blockers'].append('wb_brand_mismatch')
  if not t['wb_nmID']:t['wb_blockers'].append('wb_nmid_missing')
  docs=((card.get('documents') or {}).get('items') or []);samewb=[x for x in docs if norm_number(x.get('number'))==norm_number(NUMBER)]
  exact=[x for x in samewb if str(x.get('type') or '')=='1' and str(x.get('startDate') or '')[:10]==ISSUE and str(x.get('endDate') or '')[:10]==EXPIRY and x.get('isEndless') is False]
  if samewb and (len(samewb)!=1 or len(exact)!=1):t['wb_blockers'].append('wb_same_number_metadata_conflict')
  t['wb_exact_preexisting']=len(exact)==1
  if not t['wb_blockers']:wb_safe.add(t['offer_id'])
  wb_count['exact_preexisting' if len(exact)==1 else 'new_needed']+=1
 types=client.call('ozon','/v1/product/certificate/types',{},method='GET')
 accordance=client.call('ozon','/v2/product/certificate/accordance-types/list',{},method='GET')
 report={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'type_code':'certificate_of_conformity','marketplace_mapping':{'ozon_type':'certificate_of_conformity','wb_type':1},'issue_date':ISSUE,'expiry_date':EXPIRY,'source_file':str(SOURCE),'source_sha256':SHA,'source_size_bytes':SOURCE.stat().st_size,'source_format':SOURCE.suffix.lower(),'assignment_count':len(rows),'ozon_target_count':len(ozon_safe),'ozon_blocker_count':len(targets)-len(ozon_safe),'ozon_record_matches':record_result,'ozon_certificate_types':types,'ozon_accordance_types':accordance,'wb_target_count':len(wb_safe),'wb_blocker_count':len(targets)-len(wb_safe),'wb_existing_exact_count':wb_count['exact_preexisting'],'wb_new_needed_count':wb_count['new_needed'],'targets':targets,'no_marketplace_writes':True,'no_local_files_deleted':True}
 out=HERE/'stekker_51454_crossplatform_preflight_20261023.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ('targets','ozon_certificate_types','ozon_accordance_types')},ensure_ascii=False,indent=2))
 print('TARGETS',json.dumps([{'offer':x['offer_id'],'ozon':x['ozon_blockers'],'wb':x['wb_blockers'],'nmid':x['wb_nmID'],'wb_exact':x['wb_exact_preexisting']} for x in targets],ensure_ascii=False))
if __name__=='__main__':main()
