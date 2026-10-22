"""Fresh exact live recheck for 70 source-scoped Gauss 00069/22 targets."""
from __future__ import annotations
import collections,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import doc_key,norm_number
import run_all_found_certificates_20261014 as runner
PRE=json.loads((HERE/'gauss_00069_preflight_20261020.json').read_text())
CANDIDATES=PRE['candidates']
NUMBER=PRE['number']; CERT_ID=int(PRE['ozon_info']['certificate_id'])
client=Client()
info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
if int(info.get('certificate_id') or 0)!=CERT_ID or info.get('status_code')!='approved':
    raise RuntimeError('Exact Ozon certificate record changed or is not approved')
bindings=client.ozon_bindings(CERT_ID)
by_pid=collections.defaultdict(list)
for b in bindings: by_pid[str(b.get('product_id'))].append(b)
rows=[]
for i,t in enumerate(CANDIDATES,1):
    exact=[b for b in by_pid.get(str(t['product_id']),[]) if str(b.get('sku'))==str(t['sku'])]
    if len(exact)!=1: ozon_state='missing_or_duplicate_or_identity_mismatch'
    else: ozon_state=str(exact[0].get('product_status_code') or 'unknown')
    cards=client.wb_cards(t['offer_id'])
    exact_cards=[c for c in cards if c.get('vendorCode')==t['offer_id']]
    row={'offer_id':t['offer_id'],'product_id':str(t['product_id']),'sku':str(t['sku']),
         'tnved_expected':t['tnved'],'ozon_binding_status':ozon_state,'wb_exact_card_count':len(exact_cards)}
    if len(exact_cards)==1:
        c=exact_cards[0]
        docs=[d for d in ((c.get('documents') or {}).get('items') or []) if norm_number(d.get('number'))==norm_number(NUMBER)]
        valid=[d for d in docs if doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate',''))[:10]=='2022-08-24' and str(d.get('endDate',''))[:10]=='2027-08-23' and (d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('status')==1 and (d.get('verdict') or {}).get('reason')=='valid']
        row.update({'nmID':c.get('nmID'),'wb_brand':c.get('brand'),'wb_scope_error':runner.wb_scope_error(c,{'allowed_tnved':['8539520001','8539520003','8539520009']},{'brand':'Gauss'}),'matching_docs':len(docs),'valid_doc_count':len(valid),'wb_verdicts':[d.get('verdict') for d in docs], 'wb_document_metadata':[{k:d.get(k) for k in ('type','number','startDate','endDate','isEndless')} for d in docs]})
    else: row.update({'wb_scope_error':'no_exact_card' if not exact_cards else 'duplicate_exact_cards','matching_docs':0,'valid_doc_count':0})
    rows.append(row)
    if i%10==0: print(f'WB exact readback {i}/{len(CANDIDATES)}',flush=True)
counts={}
for key in ('ozon_binding_status','wb_scope_error'):
    counts[key]=dict(collections.Counter(str(r.get(key)) for r in rows))
out={'checked_at':now(),'read_only':True,'number':NUMBER,'ozon_certificate_id':CERT_ID,
     'ozon_document_status':info.get('status_code'),'ozon_record_products_count':info.get('products_count'),
     'ozon_live_binding_count':len(bindings),'expected_targets':len(CANDIDATES),
     'ozon_target_status_counts':dict(collections.Counter(r['ozon_binding_status'] for r in rows)),
     'wb_exact_target_cards':sum(r['wb_exact_card_count']==1 for r in rows),
     'wb_valid_exact_document_cards':sum(r['valid_doc_count']==1 for r in rows),
     'wb_target_state_counts':dict(collections.Counter('valid' if r['valid_doc_count']==1 else r['wb_scope_error'] for r in rows)),
     'rows':rows,'local_file_deleted':False}
(HERE/'gauss_00069_crossplatform_live_recheck_20261020.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k!='rows'},ensure_ascii=False,indent=2))
