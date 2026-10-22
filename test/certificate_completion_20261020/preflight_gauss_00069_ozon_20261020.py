from __future__ import annotations
import csv, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]/'test/certificate_api_pilot_20261012'
ROOT=HERE.parents[1]
sys.path.insert(0,str(BASE))
from api_client import Client, now
NUMBER='ЕАЭС RU С-CN.НВ12.В.00069/22'
OCR=(HERE/'gauss_00069_appendix_ocr_20261020.txt').read_text(encoding='utf-8')
SNAP=json.loads((HERE/'live_marketplaces_snapshot_final_20261020.json').read_text())
EXPECTED={r['offer_id']:r for r in csv.DictReader((HERE/'all_confirmed_source_assignments_live_20261020.csv').open(encoding='utf-8-sig',newline='')) if r['normalized_number']=='RUCCNHB12B0006922' and r['ozon_state']=='missing_binding'}
def article(offer): return re.sub(r'-(?:1|2|3|4|5|10)$','',offer)
selected=[];excluded=[]
for offer,r in EXPECTED.items():
 p=next(x for x in SNAP['ozon_products']['products'] if x.get('offer_id')==offer)
 code=(p.get('tnved_values') or [''])[0].split(' - ')[0]
 art=article(offer)
 article_in_pdf=bool(re.search(r'(?<![A-Za-z0-9])'+re.escape(art)+r'(?![A-Za-z0-9])',OCR,re.I))
 item={'offer_id':offer,'product_id':str(p['product_id']),'sku':str(p['sku']),'tnved':code,'article':art,'article_in_pdf_ocr':article_in_pdf,'name':p.get('name')}
 (selected if code in {'8539520001','8539520003','8539520009'} and article_in_pdf else excluded).append(item)
client=Client()
info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result',{})
# Refresh product identity, seller brand and TN VED attributes for candidate product IDs.
offers=[x['offer_id'] for x in selected]
current=[]
for start in range(0,len(offers),100):
 batch=offers[start:start+100]
 data=client.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []
 by_offer={str(x.get('offer_id')):x for x in data}
 for offer in batch:
  x=by_offer.get(offer)
  expected=next(y for y in selected if y['offer_id']==offer)
  if not x or str(x.get('id') or x.get('product_id'))!=expected['product_id'] or str(x.get('sku'))!=expected['sku'] or x.get('is_archived'):
   raise RuntimeError(f'Live product identity changed: {offer} expected={expected} live={x}')
  current.append({'offer_id':offer,'product_id':str(x.get('id') or x.get('product_id')),'sku':str(x.get('sku'))})
# Refresh all candidate links against every exact-number Ozon record.
snap_certs=SNAP['ozon_certificates']['certificates']
ids=sorted({int(c['certificate_id']) for c in snap_certs if re.sub(r'[^A-Z0-9]','',str(c.get('certificate_number','')).upper().replace('ЕАЭС','EAEC').replace('С','C').replace('Н','H').replace('В','B'))})
# safer collect snapshot number using same manual normalizer
trans=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(v): return ''.join(z for z in str(v or '').upper().translate(trans) if z.isalnum())
ids=sorted({int(c['certificate_id']) for c in snap_certs if norm(c.get('certificate_number'))==norm(NUMBER)})
existing={}
for certid in ids:
 bindings=client.ozon_bindings(certid)
 for b in bindings:
  existing.setdefault(str(b.get('product_id')),[]).append({'certificate_id':certid,'sku':str(b.get('sku')),'status':b.get('product_status_code')})
for x in selected:
 pairs=existing.get(x['product_id'],[])
 if any(b['sku']!=x['sku'] for b in pairs): raise RuntimeError(f'Binding identity mismatch: {x["offer_id"]} {pairs}')
 statuses={b['status'] for b in pairs}
 x['live_binding_statuses']=sorted(statuses)
 x['live_certificate_ids']=sorted({b['certificate_id'] for b in pairs})
 x['live_state']='approved' if 'approved' in statuses else 'pending' if statuses & {'awaiting_verification','background_check','pending'} else 'declined' if 'declined' in statuses else 'missing'
missing_only=[x for x in selected if x['live_state']=='missing']
result={'checked_at':now(),'number':NUMBER,'ozon_info':info,'snapshot_certificate_ids':ids,'candidate_count':len(selected),'excluded_count':len(excluded),'tnved_counts':dict(Counter(x['tnved'] for x in selected)),'candidates':selected,'missing_only':missing_only,'excluded':excluded,'fresh_product_identity_count':len(current),'candidate_live_state_counts':dict(Counter(x['live_state'] for x in selected)),'wb_snapshot_valid_count':sum(1 for x in selected if next((r['wb_state'] for r in csv.DictReader((HERE/'all_confirmed_source_assignments_live_20261020.csv').open(encoding='utf-8-sig',newline='')) if r['offer_id']==x['offer_id'] and r['normalized_number']=='RUCCNHB12B0006922'),'')=='valid')}
(HERE/'gauss_00069_preflight_20261020.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:result[k] for k in ('checked_at','number','ozon_info','snapshot_certificate_ids','candidate_count','excluded_count','tnved_counts','fresh_product_identity_count','candidate_live_state_counts','wb_snapshot_valid_count')},ensure_ascii=False,indent=2))
print('missing_only',','.join(x['offer_id'] for x in missing_only))
print('pending',','.join(x['offer_id'] for x in selected if x['live_state']=='pending'))
print('excluded',','.join(x['offer_id'] for x in excluded))
