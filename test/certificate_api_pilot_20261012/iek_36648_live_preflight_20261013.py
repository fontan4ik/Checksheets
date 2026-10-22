from __future__ import annotations
import collections,csv,hashlib,json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent; ROOT=BASE.parents[1]
sys.path.insert(0,str(BASE))
from api_client import Client, now, save
NUMBER='ЕАЭС N RU Д-CN.РА07.В.36648/26'; CERT_ID=5453798
ISSUE='2026-08-19'; EXPIRY='2027-10-05'
FSA_URL='https://pub.fsa.gov.ru/rds/declaration/view/21768820/product'
ALLOWED={'8539520002','8539520009'}
CHAR_MAP=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(x): return ''.join(c for c in str(x or '').upper().translate(CHAR_MAP) if c.isalnum())
def read(p): return json.loads(p.read_text())
products=read(BASE/'ozon_products_recheck_20261013_1828Z.json'); attrs=read(BASE/'ozon_brand_tnved_inventory_recheck_20261013_1828Z.json'); docs=read(BASE/'ozon_global_certificate_binding_recheck_20261013_1831Z.json'); wb=read(BASE/'wb_live_recheck_20261013_1828Z.json')
if not all(x.get('complete') for x in (products,attrs,docs,wb)): raise RuntimeError('incomplete source snapshots')
rec=[x for x in docs['records'] if str(x.get('certificate_id'))==str(CERT_ID)]
if len(rec)!=1 or norm(rec[0]['certificate_number'])!=norm(NUMBER) or rec[0]['status_code']!='approved' or rec[0]['issue_date'][:10]!=ISSUE or rec[0]['expire_date'][:10]!=EXPIRY: raise RuntimeError('Ozon record metadata conflict')
with (ROOT/'output_to_user/certificates/group_2/IEK_GENERICA/manifest.csv').open(encoding='utf-8-sig',newline='') as f: manifest=[x for x in csv.DictReader(f) if NUMBER in x['Номер документа']]
source=ROOT/'output_to_user/certificates/group_2/IEK_GENERICA'/manifest[0]['Локальный файл']
sha=hashlib.sha256(source.read_bytes()).hexdigest()
if sha!=manifest[0]['SHA-256'] or source.stat().st_size!=int(manifest[0]['Размер, байт']): raise RuntimeError('local PDF differs from manifest hash/size')
by_offer={str(x['offer_id']):x for x in products['products']}; attr={str(x['offer_id']):x for x in attrs['products']}
wb_by=collections.defaultdict(list)
for x in wb['cards']: wb_by[str(x.get('vendorCode') or '')].append(x)
client=Client(); raw=client.ozon_bindings(CERT_ID)
if len(raw)!=rec[0]['binding_count']: raise RuntimeError('live Ozon bindings count changed')
bind={str(x.get('sku')):x for x in raw}
counts=collections.Counter(); candidates=[]
for m in manifest:
 offer=m['Артикул продавца']; p=by_offer.get(offer); a=attr.get(offer)
 if not p or not a: counts['missing_fresh_ozon']+=1; continue
 if p.get('is_archived'): counts['archived']+=1; continue
 if a.get('brand_values')!=['IEK']: counts['brand_not_IEK']+=1; continue
 codes=set(a.get('tnved_codes') or [])
 if not codes or not codes.issubset(ALLOWED): counts['tnved_missing_or_out_of_fsa_scope']+=1; continue
 b=bind.get(str(p.get('sku')))
 if not b or str(b.get('product_id'))!=str(p.get('product_id')): counts['missing_or_stale_binding']+=1; continue
 if b.get('product_status_code')!='approved': counts['ozon_'+str(b.get('product_status_code'))]+=1; continue
 hit=wb_by.get(offer,[])
 if len(hit)!=1: counts['wb_missing_or_duplicate']+=1; continue
 candidates.append({'offer':offer,'product_id':str(p['product_id']),'sku':str(p['sku']),'wb_nmID':hit[0]['nmID'],'ozon_tnved':sorted(codes)})
rows=[]
for x in candidates:
 hits=client.wb_cards(x['offer'])
 if len(hits)!=1 or str(hits[0].get('vendorCode'))!=x['offer'] or str(hits[0].get('nmID'))!=str(x['wb_nmID']):
  counts['wb_live_identity_mismatch']+=1; rows.append({**x,'state':'wb_live_identity_mismatch'}); continue
 card=hits[0]
 if str(card.get('brand') or '').strip().casefold() not in ('iek','iek holding'):
  counts['wb_brand_mismatch']+=1; rows.append({**x,'state':'wb_brand_mismatch','wb_brand':card.get('brand')}); continue
 tnv=[c for c in card.get('characteristics') or [] if int(c.get('id') or -1)==15000001]
 if len(tnv)>1:
  counts['wb_tnved_duplicate']+=1; rows.append({**x,'state':'wb_tnved_duplicate'}); continue
 wb_codes={str(v).strip().split(' ',1)[0] for v in (tnv[0].get('value') or []) if str(v).strip()} if tnv else set()
 if wb_codes and not wb_codes.issubset(ALLOWED):
  counts['wb_tnved_out_of_scope']+=1; rows.append({**x,'state':'wb_tnved_out_of_scope','wb_tnved':sorted(wb_codes)}); continue
 items=[i for i in (card.get('documents') or {}).get('items',[]) if norm(i.get('number'))==norm(NUMBER)]
 if len(items)>1: state='duplicate_document_rows'
 elif not items: state='wb_missing_document'
 else:
  item=items[0]
  if int(item.get('type') or -1)!=2: state='same_number_wrong_type'
  elif (str(item.get('startDate') or '')[:10],str(item.get('endDate') or '')[:10])!=(ISSUE,EXPIRY): state='date_conflict'
  else:
   verdict=item.get('verdict') or {}; state='wb_approved' if verdict.get('verified') is True and verdict.get('status')==1 and verdict.get('reason')=='valid' else 'wb_pending_or_invalid'
 rows.append({**x,'state':state,'wb_brand':card.get('brand'),'wb_tnved':sorted(wb_codes),'document_row':items[0] if len(items)==1 else None,'overallVerdict':(card.get('documents') or {}).get('overallVerdict'),'excludeDocuments':(card.get('documents') or {}).get('excludeDocuments')})
 counts.update(x['state'] for x in rows)
result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'certificate_id':CERT_ID,'type':'declaration','issue_date':ISSUE,'expire_date':EXPIRY,'fsa_url':FSA_URL,'fsa_currently_shown':'Действует; 19.08.2026—05.10.2027; IEK LED lamps; TNVED 8539520002, 8539520009; official articles listed on FSA page','local_source':{'path':str(source),'sha256':sha,'size_bytes':source.stat().st_size,'official_cdn_url':manifest[0]['URL файла из официального CDN']},'source_snapshots':{'ozon_products':products['checked_at'],'ozon_attributes':attrs['checked_at'],'ozon_certificates':docs['checked_at_utc'],'wb_cards':wb['checked_at']},'manifest_targets':len(manifest),'ozon_record_status':rec[0]['status_code'],'ozon_binding_count':rec[0]['binding_count'],'ozon_binding_status_counts':rec[0]['binding_status_counts'],'eligible_exact_brand_code_binding_pairs':len(candidates),'counts':dict(counts),'pairs':rows}
save('iek_36648_live_preflight_20261013.json',result)
print(json.dumps({k:result[k] for k in ('checked_at_utc','number','manifest_targets','ozon_binding_status_counts','eligible_exact_brand_code_binding_pairs','counts')},ensure_ascii=False,indent=2))
