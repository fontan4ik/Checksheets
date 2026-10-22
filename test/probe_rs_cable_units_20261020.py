import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));import rs_sync_local as r,config
models={'LC1-C5E04-121-T-R','LC1-C5E04-121-T-P-R','LC1-C5E04-321-T-P-R','LC1-C5E04-311','LC1-C5E04-111-T-R'};s=r.create_rs_session();h=r.get_rs_headers();out={'warehouse':config.RS_WAREHOUSE_ID,'positions':{},'residues':{}};p=Path(__file__).with_name('new_rs_cable_units_20261020.json');page=1
while True:
 d=s.get(f'{config.RS_BASE_URL}/position/{config.RS_WAREHOUSE_ID}/instock?page={page}&rows=1000',headers=h,timeout=30).json()
 if page==1:print('catalog meta',d['meta'],flush=True)
 for x in d['items']:
  if x.get('VENDOR_CODE') in models or x.get('ARTICLE') in models:out['positions'][x.get('VENDOR_CODE') or x.get('ARTICLE')]=x
 p.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 if page%10==0:print('page',page,'found',len(out['positions']),flush=True)
 if len(out['positions'])==len(models) or page>=d['meta']['last_page']:break
 page+=1;time.sleep(.3)
for model,x in out['positions'].items():
 z=s.get(f'{config.RS_BASE_URL}/residue/{config.RS_WAREHOUSE_ID}/{x["CODE"]}',headers=h,timeout=30);out['residues'][model]=z.json();time.sleep(.3)
p.write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2),flush=True)
