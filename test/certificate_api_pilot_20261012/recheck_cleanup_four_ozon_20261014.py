from __future__ import annotations
import collections, csv, datetime as dt, json, time, unicodedata, re
from pathlib import Path
from api_client import Client
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
PLAN=json.loads((BASE/'cleanup_newly_bound_local_certificates_20261012_plan.json').read_text(encoding='utf-8'))
PRODUCTS=json.loads((BASE/'ozon_catalog_scoped_recheck_20261014.json').read_text(encoding='utf-8'))['products']
product_by_offer={str(x.get('offer_id')):x for x in PRODUCTS if x.get('offer_id')}
def norm(s):
 s=unicodedata.normalize('NFKC',str(s or '')).casefold().replace('ё','е')
 s=''.join(c for c in s if c.isalnum())
 return s.replace('еаэс','').replace('eaeu','')
rows=[]
with (ROOT/'output_to_user/certificates/document_assignments.csv').open(encoding='utf-8-sig',newline='') as f:
 for r in csv.DictReader(f):rows.append(r)
client=Client();host='https://api-seller.ozon.ru'
def post(path,payload):
 r=client.http.post(host+path,json=payload,headers=client.ozon_headers,timeout=(15,120))
 try:b=r.json()
 except ValueError:b={}
 if r.status_code!=200:raise RuntimeError(f'Ozon read failed at {path}: HTTP {r.status_code}')
 time.sleep(.25);return b
results=[]
for item in PLAN['accepted']:
 number=item['number'];cid=int(item['certificate_id'])
 record=post('/v1/product/certificate/info',{'certificate_number':number}).get('result') or {}
 binds=[];last=0;count=None
 while True:
  result=post('/v1/product/certificate/products/list',{'certificate_id':cid,'last_id':last,'limit':500}).get('result') or {}
  batch=result.get('items');n=result.get('count')
  if not isinstance(batch,list) or not isinstance(n,int):raise RuntimeError(f'malformed binding result for {number}')
  if count is None:count=n
  elif count!=n:raise RuntimeError(f'binding count changed for {number}')
  binds.extend(batch)
  if len(binds)==count:break
  if not batch or len(binds)>count:raise RuntimeError(f'incomplete bindings for {number}')
  nxt=max(int(x.get('product_id') or 0) for x in batch)
  if nxt<=last:raise RuntimeError(f'cursor did not advance for {number}')
  last=nxt
 suffix=re.search(r'([0-9]{3,}/[0-9]{2})\s*$',number).group(1)
 assignments=[r for r in rows if suffix in str(r.get('Номер/название документа') or '')]
 offers={str(r.get('Артикул продавца') or '') for r in assignments}
 expected={(str(product_by_offer[o].get('product_id')),str(product_by_offer[o].get('sku'))) for o in offers if o in product_by_offer}
 live={(str(x.get('product_id') or ''),str(x.get('sku') or '')) for x in binds}
 statuses=collections.Counter(str(x.get('product_status_code') or '') for x in binds)
 results.append({'number':number,'certificate_id':cid,'status_code':record.get('status_code'),'issue_date':record.get('issue_date'),'expire_date':record.get('expire_date'),'assignment_offer_count':len(offers),'current_expected_pair_count':len(expected),'live_pair_count':len(live),'exact_pair_set_match':live==expected,'missing_pairs':len(expected-live),'extra_pairs':len(live-expected),'binding_status_counts':dict(statuses),'all_approved':len(binds)>0 and statuses=={'approved':len(binds)}})
 # Keep all read results; any mismatch blocks cleanup and is audited below.
out={'checked_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only':True,'all_four_ozon_records_approved':all(x['status_code']=='approved' and x['all_approved'] for x in results),'all_four_exact_target_sets_match':all(x['exact_pair_set_match'] for x in results),'documents':results}
path=BASE/'cleanup_four_live_recheck_ozon_20261014.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
