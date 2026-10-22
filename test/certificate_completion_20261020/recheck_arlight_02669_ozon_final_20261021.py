from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012';sys.path.insert(0,str(API))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number
PREFLIGHT=HERE/'arlight_02669_crossplatform_preflight_live_20261021.json'
STATE=HERE/'arlight_02669_ozon_execution_20261021.json'
OUT=HERE/'arlight_02669_ozon_final_recheck_20261021.json'
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/B40746683BE4E24A9A25CD278FD53917.pdf'
NUMBER='ЕАЭС RU С-HK.АБ53.В.02669/21'; EXPECTED=578; CERT_ID='5928221'
def save(p,x):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
def main():
 if OUT.exists():raise RuntimeError('final_recheck_exists')
 pre=json.loads(PREFLIGHT.read_text()); state=json.loads(STATE.read_text())
 client=Client(); info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
 if str(info.get('certificate_id'))!=CERT_ID or norm_number(info.get('certificate_number'))!=norm_number(NUMBER) or info.get('type_code')!='certificate_of_conformity' or str(info.get('issue_date',''))[:10]!='2021-12-08' or str(info.get('expire_date',''))[:10]!='2026-12-07' or info.get('status_code')!='approved':raise RuntimeError('ozon_document_metadata_not_approved_exact')
 bindings=client.ozon_bindings(int(CERT_ID)); by_id={str(x.get('product_id')):x for x in bindings}
 expected={str(x['product_id']):str(x['sku']) for x in pre['ozon_targets']}
 if len(bindings)!=EXPECTED or len(by_id)!=EXPECTED or set(by_id)!=set(expected):raise RuntimeError('ozon_binding_product_set_mismatch')
 rows=[]; status=collections.Counter()
 for pid,sku in expected.items():
  b=by_id[pid]; ok=str(b.get('sku'))==sku; st=str(b.get('product_status_code') or 'unknown')
  rows.append({'product_id':pid,'sku':sku,'bound_exact_pair':ok,'status':st})
  if not ok:raise RuntimeError('ozon_binding_sku_mismatch')
  status[st]+=1
 if status!={'approved':EXPECTED}:raise RuntimeError(f'ozon_bindings_not_all_approved:{dict(status)}')
 out={'checked_at':now(),'complete':True,'certificate_id':CERT_ID,'number':NUMBER,'certificate_status':info.get('status_code'),'issue_date':str(info.get('issue_date'))[:10],'expiry_date':str(info.get('expire_date'))[:10],'target_count':EXPECTED,'binding_count':len(bindings),'exact_target_binding_count':len(rows),'identity_mismatch_count':0,'binding_status_counts':dict(status),'bindings':rows,'source_pdf_sha256':digest(SOURCE),'source_pdf_deleted':False}
 save(OUT,out)
 state['final_recheck']={'checked_at':out['checked_at'],'path':str(OUT),'certificate_status':out['certificate_status'],'binding_count':len(bindings),'binding_status_counts':dict(status)}
 state['binding_status_counts']=dict(status);state['certificate_status']=info.get('status_code');state['final_recheck_path']=str(OUT);state['updated_at']=now();save(STATE,state)
 print(json.dumps({k:out[k] for k in ('checked_at','certificate_id','certificate_status','target_count','binding_count','exact_target_binding_count','identity_mismatch_count','binding_status_counts')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
