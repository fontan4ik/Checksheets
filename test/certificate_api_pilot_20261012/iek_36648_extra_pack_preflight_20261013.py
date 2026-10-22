from __future__ import annotations
import collections,csv,hashlib,json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent; ROOT=BASE.parents[1]
sys.path.insert(0,str(BASE))
from api_client import Client,now,save
NUMBER='ЕАЭС N RU Д-CN.РА07.В.36648/26'; CERT_ID=5453798
ISSUE='2026-08-19'; EXPIRY='2027-10-05'; TNVED={'8539520002','8539520009'}
EXTRA_OFFERS=['LLA-A60-10-230-30-E27-6-12','LLA-A60-10-230-30-E27-6-6','LLA-A60-15-230-30-E27-6-12','LLA-A60-15-230-30-E27-6-6','LLA-A60-8-230-30-E27-6-12','LLA-A60-8-230-30-E27-6-6','LLA-G45-8-230-30-E14-6-12','LLA-G45-8-230-30-E14-6-6']
MAP=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(v): return ''.join(c for c in str(v or '').upper().translate(MAP) if c.isalnum())
client=Client()
with (ROOT/'output_to_user/certificates/group_2/IEK_GENERICA/manifest.csv').open(encoding='utf-8-sig',newline='') as f: manifest=list(csv.DictReader(f))
scoped=[r for r in manifest if NUMBER in r['Номер документа']]
article_map={}
for r in scoped: article_map.setdefault(r['Артикул продавца'],r)
source_rows=[]
for offer in EXTRA_OFFERS:
 matches=[]
 for r in scoped:
  article=r['Артикул официального каталога']
  if offer==article or offer.startswith(article+'-'): matches.append(r)
 if not matches: raise RuntimeError(f'official IEK model mapping missing for {offer}')
 distinct={r['Артикул официального каталога']:r for r in matches}
 longest=max(distinct, key=len)
 if len([a for a in distinct if len(a)==len(longest)])!=1: raise RuntimeError(f'official IEK model mapping ambiguous for {offer}: {sorted(distinct)}')
 row=distinct[longest]
 source_rows.append({'offer':offer,'article':row['Артикул официального каталога'],'official_name':row['Название товара в каталоге IEK'],'pdf':row['Локальный файл'],'sha256':row['SHA-256'],'official_xml':row['URL официального XML-каталога'],'official_cdn':row['URL файла из официального CDN']})
 # resolve local relative path and verify exact PDF source bytes
 src=ROOT/'output_to_user/certificates/group_2/IEK_GENERICA'/row['Локальный файл']
 if hashlib.sha256(src.read_bytes()).hexdigest()!=row['SHA-256']: raise RuntimeError('document SHA mismatch')

live=client.call('ozon','/v3/product/info/list',{'offer_id':EXTRA_OFFERS})
items=live.get('items') or live.get('result',{}).get('items')
if not isinstance(items,list) or len(items)!=len(EXTRA_OFFERS): raise RuntimeError('Ozon product info incomplete')
byoffer={str(x.get('offer_id')):x for x in items}
if set(byoffer)!=set(EXTRA_OFFERS): raise RuntimeError('Ozon offer identity set mismatch')
old=json.loads((BASE/'ozon_products_recheck_20261013_1828Z.json').read_text())
old_by={str(x['offer_id']):x for x in old['products']}
attrs={}
for offer in EXTRA_OFFERS:
 body=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':[offer]},'limit':1})
 aa=body.get('result') or body.get('items')
 if not isinstance(aa,list) or len(aa)!=1 or str(aa[0].get('offer_id'))!=offer: raise RuntimeError('Ozon attributes missing for '+offer)
 ids={str(a.get('id')):a for a in aa[0].get('attributes') or []}
 brand=[str(v.get('value') or '') for v in (ids.get('85') or {}).get('values') or []]
 vals=[str(v.get('value') or '') for v in (ids.get('22232') or {}).get('values') or []]
 codes=sorted({v.split(' - ',1)[0].strip() for v in vals if v.strip()})
 attrs[offer]={'brand':brand,'tnved_codes':codes,'raw_tnved':vals}

info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
if str(info.get('certificate_id'))!=str(CERT_ID) or info.get('status_code')!='approved' or info.get('type_code')!='declaration' or str(info.get('accordance_type_code') or '').upper() not in ('EAEU','EAEU'): raise RuntimeError('Current Ozon declaration metadata/status mismatch: '+json.dumps(info,ensure_ascii=False))
if str(info.get('issue_date',''))[:10]!=ISSUE or str(info.get('expire_date',''))[:10]!=EXPIRY: raise RuntimeError('Current Ozon declaration dates differ')
bindings=client.ozon_bindings(CERT_ID)
if len(bindings)!=int(info.get('products_count',len(bindings))): raise RuntimeError('Ozon live binding count mismatch')
by_sku=collections.defaultdict(list)
for b in bindings: by_sku[str(b.get('sku') or '')].append(b)
wb_snapshot=json.loads((BASE/'wb_live_recheck_20261013_1828Z.json').read_text())
wb_idx=collections.defaultdict(list)
for c in wb_snapshot['cards']: wb_idx[str(c.get('vendorCode') or '')].append(c)
rows=[]; problems=[]
for offer in EXTRA_OFFERS:
 p=byoffer[offer]; pid=str(p.get('id') or p.get('product_id') or ''); sku=str(p.get('sku') or '')
 oldp=old_by.get(offer)
 identity={'product_id':pid,'sku':sku,'is_archived':p.get('is_archived'),'name':p.get('name')}
 if not pid or not sku or (oldp and (str(oldp.get('product_id'))!=pid or str(oldp.get('sku'))!=sku)) or p.get('is_archived') is True: problems.append({'offer':offer,'reason':'stale_or_archived_product_identity','live':identity})
 if attrs[offer]['brand']!=['IEK'] or not attrs[offer]['tnved_codes'] or not set(attrs[offer]['tnved_codes']).issubset(TNVED): problems.append({'offer':offer,'reason':'brand_or_tnved_outside_FSA_scope','attributes':attrs[offer]})
 records=by_sku.get(sku,[])
 if len(records)>1: problems.append({'offer':offer,'reason':'duplicate_Ozon_binding','bindings':records})
 if records and (str(records[0].get('product_id'))!=pid): problems.append({'offer':offer,'reason':'binding_product_id_conflict','binding':records[0]})
 cards=client.wb_cards(offer)
 if len(cards)!=1 or str(cards[0].get('vendorCode'))!=offer: problems.append({'offer':offer,'reason':'exact_WB_card_missing_or_ambiguous','count':len(cards)})
 else:
  card=cards[0]
  wb_brand=str(card.get('brand') or '').strip().casefold()
  tnv=[x for x in card.get('characteristics') or [] if int(x.get('id') or -1)==15000001]
  wb_codes={str(v).strip().split(' ',1)[0] for v in ((tnv[0].get('value') or []) if len(tnv)==1 else []) if str(v).strip()}
  if wb_brand not in ('iek','iek holding'): problems.append({'offer':offer,'reason':'WB_brand_mismatch','brand':card.get('brand')})
  if len(tnv)>1 or (wb_codes and not wb_codes.issubset(TNVED)): problems.append({'offer':offer,'reason':'WB_TNVED_conflict','tnved':sorted(wb_codes),'rows':len(tnv)})
  matches=[d for d in (card.get('documents') or {}).get('items') or [] if norm(d.get('number'))==norm(NUMBER)]
  if len(matches)>1: wb_state='duplicate'
  elif not matches: wb_state='missing'
  else:
   d=matches[0]
   if int(d.get('type') or -1)!=2 or (str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10])!=(ISSUE,EXPIRY): wb_state='metadata_conflict'
   elif d.get('verdict',{}).get('verified') is True and d.get('verdict',{}).get('status')==1 and d.get('verdict',{}).get('reason')=='valid': wb_state='valid'
   else: wb_state='pending_or_invalid'
  rows.append({'offer':offer,**identity,'brand':attrs[offer]['brand'],'ozon_tnved':attrs[offer]['tnved_codes'],'ozon_binding':records[0] if records else None,'wb_nmID':card.get('nmID'),'wb_brand':card.get('brand'),'wb_tnved':sorted(wb_codes),'wb_document_state':wb_state,'wb_document':matches[0] if len(matches)==1 else None,'official_catalog_article':next(x['article'] for x in source_rows if x['offer']==offer)})
result={'checked_at_utc':now(),'read_only':True,'certificate_id':CERT_ID,'number':NUMBER,'issue_date':ISSUE,'expire_date':EXPIRY,'fsa_url':'https://pub.fsa.gov.ru/rds/declaration/view/21768820/product','ozon_live_record':info,'record_binding_count':len(bindings),'already_bound_status_counts':dict(collections.Counter(str(b.get('product_status_code')) for b in bindings)),'targets':rows,'problems':problems,'will_bind_skus':[r['sku'] for r in rows if not r['ozon_binding']],'snapshot_checked_at':{'ozon_products':old['checked_at'],'wb':wb_snapshot['checked_at']}}
save('iek_36648_extra_pack_preflight_20261013.json',result)
print(json.dumps({'checked_at_utc':result['checked_at_utc'],'targets':len(rows),'problems':problems,'already_bound_status_counts':result['already_bound_status_counts'],'will_bind_count':len(result['will_bind_skus']),'wb_states':dict(collections.Counter(r['wb_document_state'] for r in rows))},ensure_ascii=False,indent=2))
