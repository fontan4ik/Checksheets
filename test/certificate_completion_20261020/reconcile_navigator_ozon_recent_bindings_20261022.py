from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number
GROUPS=[
 {'name':'navigator_nll_08110_06643','preflight':'navigator_nll_08110_06643_fresh_preflight_20261022.json','docs':[('declaration',5945402,'ЕАЭС N RU Д-CN.РА11.В.08110/24','declaration','2024-12-02','2029-12-01'),('certificate',5945406,'ЕАЭС RU С-CN.НВ54.В.06643/24','certificate_of_conformity','2024-12-04','2029-12-03')]},
 {'name':'navigator_nll_93270_43404','preflight':'navigator_14009_93270_43404_preflight_20261022.json','docs':[('declaration',5945811,'ЕАЭС N RU Д-CN.РА08.В.93270/25','declaration','2025-10-06','2030-10-02'),('certificate',5945813,'ЕАЭС RU С-CN.АЯ46.В.43404/25','certificate_of_conformity','2025-10-03','2030-10-02')]},
 {'name':'navigator_nfl_90815_00107','preflight':'navigator_nfl_90815_00107_fresh_v2_20261022.json','docs':[('declaration',5946929,'ЕАЭС N RU Д-RU.РА11.В.90815/24','declaration','2024-12-27','2029-12-25'),('certificate',5947021,'ЕАЭС RU С-RU.НВ28.В.00107/24','certificate_of_conformity','2024-12-24','2029-12-23')]}
]
c=Client();all_certs=[]
for page in range(1,101):
 res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
 rows=res.get('certificates')
 if not isinstance(rows,list):raise RuntimeError('ozon_list_invalid')
 all_certs.extend(rows)
 if page>=int(res.get('page_count') or 0):break
else:raise RuntimeError('ozon_page_limit')
out={'checked_at_utc':now(),'read_only':True,'groups':[],'all_expected_bindings_approved':True}
for group in GROUPS:
 pre=json.loads((HERE/group['preflight']).read_text());target_pairs=set()
 for t in pre['targets']:
  if t.get('ozon_eligible') is True:target_pairs.add((str(t['product_id']),str(t['sku'])))
 row={'group':group['name'],'expected_target_products':len(target_pairs),'documents':[]}
 for label,cid,num,type_code,issue,expiry in group['docs']:
  matches=[x for x in all_certs if norm_number(x.get('certificate_number'))==norm_number(num)]
  if len(matches)!=1:raise RuntimeError('record_count:'+group['name']+':'+label+':'+str(len(matches)))
  record=matches[0]
  if record.get('type_code')!=type_code or str(record.get('issue_date',''))[:10]!=issue or str(record.get('expire_date',''))[:10]!=expiry or record.get('status_code')!='approved':raise RuntimeError('record_metadata_or_status:'+group['name']+':'+label)
  if str(record.get('certificate_id'))!=str(cid):raise RuntimeError('record_id_changed:'+group['name']+':'+label)
  bindings=c.ozon_bindings(cid);pairs={(str(x.get('product_id')),str(x.get('sku'))) for x in bindings}
  outside=sorted(pairs-target_pairs);missing=sorted(target_pairs-pairs)
  counts=collections.Counter(str(x.get('product_status_code') or 'unknown') for x in bindings if (str(x.get('product_id')),str(x.get('sku'))) in target_pairs)
  ok=not outside and not missing and counts=={'approved':len(target_pairs)}
  if not ok:out['all_expected_bindings_approved']=False
  row['documents'].append({'kind':label,'certificate_id':cid,'number':num,'record_status':record.get('status_code'),'issue_date':issue,'expiry_date':expiry,'expected_bindings':len(target_pairs),'visible_bindings':len(pairs&target_pairs),'missing_bindings':len(missing),'outside_bindings':len(outside),'binding_status_counts':dict(counts),'all_expected_pairs_approved':ok})
 out['groups'].append(row)
path=HERE/'navigator_nll_and_nfl_ozon_final_bindings_20261022.json';path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
if not out['all_expected_bindings_approved']:raise RuntimeError('not_all_approved')
print(json.dumps(out,ensure_ascii=False,indent=2))
