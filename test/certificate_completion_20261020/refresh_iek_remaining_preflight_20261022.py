from __future__ import annotations
import collections, json, sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=Path(__file__).resolve().parent
API=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(API))
import run_all_found_certificates_20261014 as runner_module
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number
MANIFEST=BASE/'iek_remaining_official_docs_manifest_20261020.json'
OUT=BASE/'iek_remaining_live_preflight_20261022.json'

def main():
    manifest=json.loads(MANIFEST.read_text())
    client=Client()
    records=[]
    for page in range(1,101):
        data=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
        batch=data.get('certificates')
        if not isinstance(batch,list): raise RuntimeError('Ozon certificate page incomplete')
        records.extend(batch)
        if not batch or page>=int(data.get('page_count') or 0): break
    if page>=100 and batch: raise RuntimeError('Ozon certificate pagination limit')
    ozon_docs=[]; targets_by_offer={}
    for g in manifest['groups']:
        matches=[c for c in records if norm_number(c.get('certificate_number'))==norm_number(g['number'])]
        if len(matches)!=1: raise RuntimeError(f"Expected one Ozon record for {g['number']}, found {len(matches)}")
        c=matches[0]
        if c.get('type_code')!=g['type_code'] or c.get('accordance_type_code')!='EAEU' or str(c.get('issue_date',''))[:10]!=g['issue_date'][:10] or str(c.get('expire_date',''))[:10]!=g['expire_date'][:10]:
            raise RuntimeError(f"Ozon document identity/date mismatch: {g['number']}")
        bindings=client.ozon_bindings(c['certificate_id'])
        bypid={str(x.get('product_id')):x for x in bindings}
        rows=[]
        for t in g['targets']:
            b=bypid.get(str(t['product_id']))
            exact=bool(b and str(b.get('sku'))==str(t['sku']))
            rows.append({'offer_id':t['offer_id'],'product_id':str(t['product_id']),'sku':str(t['sku']),'exact_binding_visible':exact,'product_status_code':b.get('product_status_code') if b else None})
            targets_by_offer.setdefault(t['offer_id'],[]).append((g,t))
        counts=collections.Counter(x['product_status_code'] or 'missing' for x in rows if x['exact_binding_visible'])
        ozon_docs.append({'number':g['number'],'certificate_id':c['certificate_id'],'document_status':c.get('status_code'),'expected_targets':len(g['targets']),'exact_bindings':sum(x['exact_binding_visible'] for x in rows),'target_status_counts':dict(counts),'targets':rows})
        print(f"Ozon {len(ozon_docs)}/{len(manifest['groups'])}: {g['number']} {dict(counts)}",flush=True)
    if sum(x['exact_bindings'] for x in ozon_docs)!=manifest['candidate_count']:
        raise RuntimeError('Ozon exact binding count is incomplete')
    wb_rows=[];wb_counts=collections.Counter()
    for i,(offer,groups) in enumerate(targets_by_offer.items(),1):
        cards=client.wb_cards(offer)
        exact=[c for c in cards if c.get('vendorCode')==offer]
        if len(exact)!=1:
            status='wb_card_missing' if not exact else 'wb_card_duplicate'
            for g,t in groups:
                row={'offer_id':offer,'number':g['number'],'result':status,'matches':len(exact)}
                wb_rows.append(row);wb_counts[row['result']]+=1
        else:
            card=exact[0]
            for g,t in groups:
                err=runner_module.wb_scope_error(card,g,t)
                row={'offer_id':offer,'number':g['number'],'nmID':card.get('nmID'),'brand':card.get('brand'),'vendorCode':card.get('vendorCode'),'result':err or 'exact_scope_safe'}
                wb_rows.append(row);wb_counts[row['result']]+=1
        if i%20==0: print(f'WB exact-offer checks {i}/{len(targets_by_offer)}: {dict(wb_counts)}',flush=True)
    result={'checked_at':now(),'read_only':True,'source_verified_groups':len(manifest['groups']),'source_target_edges':manifest['candidate_count'],'ozon_documents':ozon_docs,'ozon_document_count':len(ozon_docs),'ozon_exact_binding_edges':sum(x['exact_bindings'] for x in ozon_docs),'ozon_status_counts':dict(collections.Counter(x['document_status'] for x in ozon_docs)),'ozon_target_status_counts':dict(collections.Counter(status for x in ozon_docs for status,n in x['target_status_counts'].items() for _ in range(n))),'wb_offers_checked':len(wb_rows),'wb_result_counts':dict(wb_counts),'wb_checks':wb_rows,'wb_review_left_pending':True,'local_files_deleted':False}
    tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2));tmp.replace(OUT)
    print(json.dumps({k:v for k,v in result.items() if k not in ('ozon_documents','wb_checks')},ensure_ascii=False,indent=2),flush=True)
    print('Saved',OUT,flush=True)
if __name__=='__main__':main()
