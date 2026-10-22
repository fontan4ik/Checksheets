from __future__ import annotations
import collections, csv, json, sys, re
from pathlib import Path
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
sys.path.insert(0,str(BASE))
from api_client import Client, now, save
OZ_PRODUCTS=BASE/'ozon_products_recheck_20261013_1828Z.json'
OZ_ATTR=BASE/'ozon_brand_tnved_inventory_recheck_20261013_1828Z.json'
OZ_CERT=BASE/'ozon_global_certificate_binding_recheck_20261013_1831Z.json'
WB=BASE/'wb_live_recheck_20261013_1828Z.json'
MANIFEST=ROOT/'output_to_user/certificates/group_2/IEK_GENERICA/manifest.csv'
DOCS={
 '36541/26': {'id':5447881,'number':'ЕАЭС N RU Д-CN.РА07.В.36541/26','type':2,
             'dates':('2026-08-19','2030-09-29'),'tnved':{'8539520001','8539520002','8539520003','8539520009','9405210012'},
             'fsa':'https://pub.fsa.gov.ru/rds/declaration/view/21768746'},
 '51281/26': {'id':5447878,'number':'ЕАЭС RU С-CN.АЯ46.В.51281/26','type':1,
             'dates':('2026-08-27','2030-10-02'),'tnved':{'8539520001','8539520002','8539520003','8539520009','9405210012'},
             'fsa':'https://pub.fsa.gov.ru/rss/certificate/view/3719852'},
}
CHAR_MAP=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(x): return ''.join(c for c in str(x or '').upper().translate(CHAR_MAP) if c.isalnum())
def load(p): return json.loads(p.read_text())
prod_doc=load(OZ_PRODUCTS); attr_doc=load(OZ_ATTR); cert_doc=load(OZ_CERT); wb_doc=load(WB)
for name,d in [('ozon_products',prod_doc),('ozon_attributes',attr_doc),('ozon_certificates',cert_doc),('wb',wb_doc)]:
 if not d.get('complete'): raise RuntimeError(name+' snapshot incomplete')
if len({str(x['offer_id']) for x in prod_doc['products']})!=len(prod_doc['products']): raise RuntimeError('duplicate Ozon offers')
sku_values=[str(x.get('sku') or '') for x in prod_doc['products'] if str(x.get('sku') or '')]
if len(set(sku_values))!=len(sku_values): raise RuntimeError('duplicate non-empty Ozon SKU')
products={str(x['offer_id']):x for x in prod_doc['products']}
attr={str(x['offer_id']):x for x in attr_doc['products']}
wb_cards=collections.defaultdict(list)
for x in wb_doc['cards']: wb_cards[str(x.get('vendorCode') or '')].append(x)
with MANIFEST.open(encoding='utf-8-sig',newline='') as f: manifest=list(csv.DictReader(f))
manifest_by_doc={suffix:[r for r in manifest if suffix in r['Номер документа']] for suffix in DOCS}
records={str(x['certificate_id']):x for x in cert_doc['records']}
client=Client()
results={'checked_at_utc':now(),'read_only':True,'source_snapshots':{
 'ozon_products':prod_doc['checked_at'],'ozon_attributes':attr_doc['checked_at'],'ozon_certificates':cert_doc['checked_at_utc'],'wb_catalog':wb_doc['checked_at']},'documents':{},'wb_candidate_cards':[]}
# Load raw, current Ozon binding detail so rejection reasons are retained for repair decisions.
raw_bindings={}
for suffix,d in DOCS.items():
 record=records.get(str(d['id']))
 if not record or norm(record.get('certificate_number'))!=norm(d['number']): raise RuntimeError('Ozon record mismatch '+suffix)
 raw=client.ozon_bindings(d['id'])
 raw_bindings[suffix]={str(x.get('sku')):x for x in raw}
 if len(raw)!=record['binding_count']: raise RuntimeError('live binding count mismatch '+suffix)

# Exact article/brand/TN VED, current Ozon identity and approved binding, unique current WB card.
for suffix,d in DOCS.items():
 record=records[str(d['id'])]
 target_rows=manifest_by_doc[suffix]
 by_binding={str(x.get('sku')):x for x in raw_bindings[suffix].values()}
 rows=[]; counts=collections.Counter()
 for m in target_rows:
  offer=str(m['Артикул продавца']); p=products.get(offer); a=attr.get(offer)
  if not p or not a: counts['not_in_fresh_ozon']+=1; continue
  if p.get('is_archived'): counts['archived']+=1; continue
  brands=a.get('brand_values') or []
  codes=set(a.get('tnved_codes') or [])
  if brands!=['IEK']: counts['brand_outside_IEK']+=1; continue
  if not codes or not codes.issubset(d['tnved']): counts['tnved_missing_or_outside_fsa_scope']+=1; continue
  binding=by_binding.get(str(p['sku']))
  if not binding or str(binding.get('product_id'))!=str(p['product_id']): counts['missing_or_stale_ozon_binding']+=1; continue
  if binding.get('product_status_code')!='approved':
   counts['ozon_'+str(binding.get('product_status_code'))]+=1
   counts['rejected_reason_'+str(binding.get('reason') or binding.get('error') or 'not_returned')]+=1
   continue
  exact=wb_cards.get(offer,[])
  if len(exact)!=1 or str(exact[0].get('nmID'))=='': counts['wb_missing_or_ambiguous']+=1; continue
  rows.append({'offer':offer,'product_id':str(p['product_id']),'sku':str(p['sku']), 'brand':brands,'ozon_tnved_codes':sorted(codes), 'ozon_binding_status':binding.get('product_status_code'), 'wb_nmid':exact[0]['nmID']})
 # direct live exact card retrieval
 live_rows=[]
 for item in rows:
  hits=client.wb_cards(item['offer'])
  if len(hits)!=1 or str(hits[0].get('vendorCode'))!=item['offer'] or str(hits[0].get('nmID'))!=str(item['wb_nmid']):
   live_rows.append({'offer':item['offer'],'state':'WB exact identity missing_or_ambiguous','hit_count':len(hits)}); counts['wb_live_mismatch']+=1; continue
  card=hits[0]; wb_brand=str(card.get('brand') or '').strip().casefold()
  chars=card.get('characteristics') or []
  tnved_rows=[x for x in chars if int(x.get('id') or -1)==15000001]
  if len(tnved_rows)>1:
   live_rows.append({'offer':item['offer'],'state':'WB duplicate TNVED characteristics'}); counts['wb_duplicate_tnved']+=1; continue
  wb_codes=set(str(v).strip().split(' ',1)[0] for v in (tnved_rows[0].get('value') or []) if str(v).strip()) if tnved_rows else set()
  if wb_brand not in ('iek','iek holding'):
   live_rows.append({'offer':item['offer'],'state':'WB brand mismatch','wb_brand':card.get('brand')}); counts['wb_brand_mismatch']+=1; continue
  if wb_codes and not wb_codes.issubset(d['tnved']):
   live_rows.append({'offer':item['offer'],'state':'WB TNVED outside FSA scope','wb_tnved_codes':sorted(wb_codes)}); counts['wb_tnved_outside_scope']+=1; continue
  docs=card.get('documents') or {}; items=docs.get('items') or []
  matched=[x for x in items if norm(x.get('number'))==norm(d['number'])]
  if len(matched)>1:
   state='duplicate_document_rows'; counts[state]+=1
  elif matched:
   x=matched[0]
   if int(x.get('type') or -1)!=d['type']:
    state='same_number_wrong_type'; counts[state]+=1
   elif (str(x.get('startDate') or '')[:10],str(x.get('endDate') or '')[:10])!=d['dates']:
    state='date_conflict'; counts[state]+=1
   else:
    verdict=x.get('verdict') or {}; status=verdict.get('status'); verified=verdict.get('verified')
    state={1:'wb_approved',2:'wb_pending',3:'wb_declined'}.get(status,'wb_unknown_verdict')
    counts[state]+=1
  else:
   state='wb_missing_doc'; counts[state]+=1
  live_rows.append({**item,'state':state,'wb_brand':card.get('brand'),'wb_tnved_codes':sorted(wb_codes),'excludeDocuments':docs.get('excludeDocuments'), 'document_row':matched[0] if len(matched)==1 else None})
 results['documents'][suffix]={
  'ozon_record_id':d['id'],'ozon_record_status':record.get('status_code'),'ozon_record_number':record.get('certificate_number'),
  'ozon_binding_count':record['binding_count'],'ozon_binding_status_counts':record['binding_status_counts'],
  'manifest_targets':len(target_rows),'exact_eligible_targets_after_fsa_brand_tnved_binding_wb_snapshot':len(rows),
  'pre_filter_counts':dict(counts),'candidates':live_rows,'official_fsa_url':d['fsa']}

# compact addable/approval/status totals, so later mutations can be exact and idempotent
results['summary']={s:dict(collections.Counter(x['state'] for x in v['candidates'])) for s,v in results['documents'].items()}
save('iek_lamps_wb_preflight_20261013_1840Z.json',results)
print(json.dumps({'saved':'iek_lamps_wb_preflight_20261013_1840Z.json','checked_at_utc':results['checked_at_utc'],'summary':results['summary'],'pre_filter_counts':{s:v['pre_filter_counts'] for s,v in results['documents'].items()}},ensure_ascii=False,indent=2))
