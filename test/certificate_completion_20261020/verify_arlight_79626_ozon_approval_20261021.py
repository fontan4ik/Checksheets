"""Fresh live Ozon verification for Arlight 79626/26 before local cleanup."""
from __future__ import annotations
import collections, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number
NUMBER='ЕАЭС N RU Д-CN.РА03.В.79626/26'
CERT_ID=5920732
ISSUE='2026-04-29'
EXPIRY='2031-04-27'
TARGET=json.loads((HERE/'arlight_79626_preflight_live_20261021.json').read_text())['ozon_targets']
OUT=HERE/'arlight_79626_ozon_final_readback_20261021.json'
if OUT.exists(): raise RuntimeError('output_exists')
client=Client()
info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
bindings=client.ozon_bindings(CERT_ID)
by_id={str(x.get('product_id')):x for x in bindings}
rows=[]
for target in TARGET:
 b=by_id.get(str(target['product_id']))
 rows.append({'offer_id':target['offer_id'],'product_id':target['product_id'],'sku':target['sku'],
              'bound':bool(b and str(b.get('sku'))==str(target['sku'])),
              'status':str((b or {}).get('product_status_code') or '')})
statuses=collections.Counter(x['status'] for x in rows if x['bound'])
exact=(str(info.get('certificate_id'))==str(CERT_ID)
       and norm_number(info.get('certificate_number'))==norm_number(NUMBER)
       and str(info.get('issue_date',''))[:10]==ISSUE
       and str(info.get('expire_date',''))[:10]==EXPIRY
       and info.get('status_code')=='approved')
result={'checked_at':now(),'number':NUMBER,'certificate_id':CERT_ID,'document_metadata_exact':exact,
        'certificate_status':info.get('status_code'),'issue_date':str(info.get('issue_date',''))[:10],
        'expiry_date':str(info.get('expire_date',''))[:10],'expected_target_bindings':len(TARGET),
        'verified_target_bindings':sum(x['bound'] for x in rows),'binding_status_counts':dict(statuses),
        'complete':exact and len(rows)==70 and all(x['bound'] and x['status']=='approved' for x in rows),
        'bindings':rows}
tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2));tmp.replace(OUT)
print(json.dumps({k:v for k,v in result.items() if k!='bindings'},ensure_ascii=False,indent=2))
if not result['complete']: raise RuntimeError('ozon_approval_or_bindings_incomplete')
