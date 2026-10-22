"""Read-only exact Ozon binding and WB card recheck for 36 newly sourced IEK offers."""
from __future__ import annotations
import collections, json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(API))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import OZON_TO_WB_TYPE, copy_documents, doc_key, norm_number, wb_datetime
import run_all_found_certificates_20261014 as runner
MANIFEST=HERE/'iek_missing_new_docs_manifest_20261020.json'
OUT=HERE/'iek_missing_new_docs_live_recheck_20261020.json'
manifest=json.loads(MANIFEST.read_text())
client=Client()
# Find the exact live Ozon certificate records by the official number/type.
records=[]
for page in range(1,101):
    result=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
    batch=result.get('certificates') or []
    if not isinstance(batch,list): raise RuntimeError('Invalid Ozon certificate list')
    records.extend(batch)
    if len(batch)<100: break
else: raise RuntimeError('Ozon certificate pagination limit')

def norm(s):
    tr=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
    return ''.join(c for c in str(s or '').upper().translate(tr) if c.isalnum())
def identity(s): return norm(s).replace('EAE','EAE')
by_identity=collections.defaultdict(list)
for record in records:
    by_identity[(str(record.get('type_code') or ''),identity(record.get('certificate_number')))].append(record)
results=[]
for group in manifest['groups']:
    matches=by_identity[(group['type_code'],identity(group['number']))]
    exact=[r for r in matches if str(r.get('certificate_number') or '').strip()==group['number']]
    if len(exact)!=1:
        raise RuntimeError(f"Expected one exact Ozon record for {group['number']}; got {len(exact)}")
    record=exact[0]
    cert_id=int(record['certificate_id'])
    bindings=client.ozon_bindings(cert_id)
    by_pid=collections.defaultdict(list)
    for binding in bindings: by_pid[str(binding.get('product_id'))].append(binding)
    group_result={'number':group['number'],'certificate_id':cert_id,'document_status':record.get('status_code'),
                  'expected_targets':len(group['targets']),'targets':[]}
    wanted={'type':OZON_TO_WB_TYPE[group['type_code']],'number':group['number'],
            'startDate':wb_datetime(group['issue_date']),'endDate':wb_datetime(group['expire_date']),'isEndless':False}
    for target in group['targets']:
        pid=str(target['product_id']); sku=str(target['sku']); candidates=by_pid.get(pid,[])
        exact_binding=[b for b in candidates if str(b.get('sku'))==sku]
        if candidates and not exact_binding: ozon_state='identity_conflict'
        elif len(exact_binding)>1: ozon_state='duplicate_binding'
        elif not exact_binding: ozon_state='missing_binding'
        else: ozon_state=str(exact_binding[0].get('product_status_code') or 'unknown')
        cards=client.wb_cards(target['offer_id'])
        exact_cards=[c for c in cards if c.get('vendorCode')==target['offer_id']]
        row={'offer_id':target['offer_id'],'product_id':pid,'sku':sku,'brand_expected':target['brand'],
             'ozon_binding_status':ozon_state,'ozon_exact_binding_count':len(exact_binding),
             'wb_exact_card_count':len(exact_cards)}
        if len(exact_cards)==1:
            card=exact_cards[0]
            row.update({'nmID':card.get('nmID'),'wb_brand':card.get('brand'),
                        'wb_scope_error':runner.wb_scope_error(card,group,target),
                        'wb_existing_same_number':[x for x in copy_documents(card) if norm_number(x.get('number'))==norm_number(wanted['number'])]})
            existing=row['wb_existing_same_number']
            if existing:
                row['wb_doc_state']='already_exact' if all(doc_key(x)==doc_key(wanted) and str(x.get('startDate',''))[:10]==wanted['startDate'][:10] and str(x.get('endDate',''))[:10]==wanted['endDate'][:10] for x in existing) else 'conflict'
            else: row['wb_doc_state']='missing'
        elif len(exact_cards)>1: row['wb_doc_state']='duplicate_cards'
        else: row['wb_doc_state']='no_exact_card'
        group_result['targets'].append(row)
    results.append(group_result)
    print(json.dumps({'document':group['number'],'targets':len(group_result['targets']),
       'ozon':dict(collections.Counter(x['ozon_binding_status'] for x in group_result['targets'])),
       'wb':dict(collections.Counter(x['wb_doc_state'] for x in group_result['targets']))},ensure_ascii=False),flush=True)
output={'checked_at':now(),'read_only':True,'source_manifest':str(MANIFEST),'documents':results,
        'ozon_binding_status_counts':dict(collections.Counter(x['ozon_binding_status'] for g in results for x in g['targets'])),
        'wb_card_status_counts':dict(collections.Counter(x['wb_doc_state'] for g in results for x in g['targets'])),
        'wb_review_left_pending':True,'local_files_deleted':False}
OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in output.items() if k not in ('documents','source_manifest')},ensure_ascii=False,indent=2))
