"""Bind only the 15 fresh, source-verified IEK products to approved Ozon docs.

Dry-run by default. Pass --execute after reviewing the generated preflight.
Never uploads a duplicate document and never deletes local files.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(API))
import run_all_found_certificates_20261014 as runner_module  # noqa:E402
from api_client import Client  # noqa:E402

SNAPSHOT=HERE/'live_marketplaces_snapshot_complete_20261020.json'
AUDIT=HERE/'iek_current_ozon_docs_audit_20261020.json'
PREFLIGHT=HERE/'iek_found_candidates_live_preflight_20261020.json'
MANIFEST_PATH=HERE/'iek_validated_binding_manifest_20261020.json'
JOURNAL=HERE/'reconciliation_journal.jsonl'
TARGETS={
    5453820:['LDPA2-2101-20-00-K01-1','LDPA2-2104-20-00-K01-1'],
    5448121:['LDPA0-140-3-3-20-K01-1'],
    5448059:['LT-DKU1-1011-120-50-K03-1','LT-DKU1-1011-150-50-K03-1',
             'LT-DKU1-1011-100-50-K03-1','LT-DKU1-1011-200-50-K03-1',
             'LT-DKU1-1011-030-50-K03-1','LDKU1-1013-120-5000-K03-1'],
    5448118:['LSR6-2-168-20-1-05-1','LSR11-10-480-20-1-05-1',
             'LSR6-10-168-20-1-05-1','LSR11-2-480-20-1-05-1',
             'LSR11-1-480-20-1-05-1','LSR11-2-312-20-1-05-1'],
}
ALLOWED={5453820:['9405110013','9405110033','9405610002','9405610005'],
         5448121:['9405110013','9405610002'],
         5448059:['9405420032'],
         5448118:['8539519009']}
SAMPLE_MONTH={5453820:'2025-01',5448059:'2023-12',5448118:'2023-12'}
OCR_FILES={5448059:'iek_pdf_ocr_20261020/5448059.txt',
           5448118:'iek_pdf_ocr_20261020/5448118.txt',
           5448121:'iek_candidate_docs_ocr_20261020/5448121.txt',
           5453820:'iek_candidate_docs_ocr_20261020/5453820.txt'}

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def build_manifest():
    snapshot=json.loads(SNAPSHOT.read_text())
    if snapshot.get('complete') is not True: raise RuntimeError('Fresh marketplace snapshot is incomplete')
    audits=json.loads(AUDIT.read_text())['groups']
    preflight=json.loads(PREFLIGHT.read_text())['offers']
    pre_by={x['offer_id']:x for x in preflight}
    product_by={x['offer_id']:x for x in snapshot['ozon_products']['products']}
    cert_by={str(x['certificate_id']):x for x in snapshot['ozon_certificates']['certificates']}
    offer_by={x['offer_id']:x for g in audits for x in g['offers']}
    groups=[]
    used_keys=set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text().splitlines():
            row=json.loads(line)
            if row.get('key'): used_keys.add(row['key'])
    for cid,offers in TARGETS.items():
        audit=next((x for x in audits if int(x['ozon_id'])==cid),None)
        cert=cert_by.get(str(cid))
        if not audit or not cert: raise RuntimeError(f'Missing source/current Ozon record for {cid}')
        if cert.get('status_code')!='approved' or cert.get('type_code')!='declaration' or cert.get('accordance_type_code')!='EAEU':
            raise RuntimeError(f'Document {cid} is not approved EAEU declaration')
        if (cert.get('issue_date') or '')[:10]!=(audit.get('issue_date') or '')[:10] or (cert.get('expire_date') or '')[:10]!=(audit.get('expire_date') or '')[:10]:
            raise RuntimeError(f'Date mismatch for certificate {cid}')
        local_pdf=Path(audit['local_pdf'])
        digest=sha256(local_pdf)
        if digest!=audit.get('downloaded_sha256'):
            raise RuntimeError(f'Official PDF hash changed for certificate {cid}')
        ocr_path=HERE/OCR_FILES[cid]
        if not ocr_path.is_file(): raise RuntimeError(f'Missing OCR evidence for {cid}')
        targets=[]
        for offer in offers:
            source=offer_by.get(offer); product=product_by.get(offer); live=pre_by.get(offer)
            if not source or not product or not live: raise RuntimeError(f'Missing target/source evidence for {offer}')
            if source.get('brand')!='IEK' or live.get('brand_values')!=['IEK']:
                raise RuntimeError(f'Brand mismatch for {offer}')
            if source.get('feacn') not in ALLOWED[cid] or live.get('official_tnved') not in ALLOWED[cid]:
                raise RuntimeError(f'Official document TN VED scope mismatch for {offer}')
            live_codes=[str(x).split(' - ',1)[0].strip() for x in (live.get('tnved_values') or [])]
            if live_codes!=[source.get('feacn')]: raise RuntimeError(f'Live Ozon TN VED mismatch for {offer}')
            if str(product.get('product_id'))!=str(live.get('live_product_id')) or str(product.get('sku'))!=str(live.get('live_sku')):
                raise RuntimeError(f'Ozon identity changed since preflight for {offer}')
            if product.get('is_archived') is not False or live.get('live_archived') is not False:
                raise RuntimeError(f'Archived target {offer}')
            if live.get('target_already_bound') is not False:
                raise RuntimeError(f'Target already bound or uncertain in {offer}')
            if live.get('wb_exact_matches')!=0:
                raise RuntimeError(f'WB exact card exists; route through WB reconciliation separately: {offer}')
            sample_month=SAMPLE_MONTH.get(cid)
            first=(source.get('firstSaleDate') or '')[:10]
            if sample_month and first and first[:7]<=sample_month:
                raise RuntimeError(f'Product first sale is not after sample month: {offer}')
            targets.append({'offer_id':offer,'product_id':str(product['product_id']),'sku':str(product['sku']),
                'brand':'IEK','source_url':source.get('product_url'),'source_first_sale':source.get('firstSaleDate'),
                'source_tnved':source.get('feacn'),'source_name':source.get('name')})
        skus=sorted(t['sku'] for t in targets)
        marker=hashlib.sha256(','.join(skus).encode()).hexdigest()
        if 'ozon:bind:'+str(cid)+':'+marker in used_keys: raise RuntimeError(f'Previous batch outcome exists for {cid}')
        for sku in skus:
            if 'ozon:bind_sku:'+str(cid)+':'+sku in used_keys: raise RuntimeError(f'Previous single binding outcome exists for {cid}/{sku}')
        group={'number':cert['certificate_number'],'type_code':'declaration','accordance_type':'EAEU','country':'RU',
            'issue_date':cert['issue_date'],'expire_date':cert['expire_date'],'allowed_tnved':ALLOWED[cid],
            'source_evidence_verified':True,'source_evidence_files':[str(ocr_path),str(local_pdf)],
            'sample_month':sample_month,'upload_file':{'path':str(local_pdf),'sha256':digest},
            'source_url':audit['url'],'targets':targets,'certificate_id':cid}
        groups.append(group)
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'snapshot':str(SNAPSHOT),'groups':groups,
        'blocked_document_keys':[],'candidate_count':sum(len(x['targets']) for x in groups),
        'basis':'Exact IEK official product-to-document crosswalk; active approved Ozon records; exact declaration model and TN VED scope verified in official PDF; current live Ozon brand, TN VED, product identity and unbound state rechecked. Sample-date cutoff applied where the declaration states it.'}
    MANIFEST_PATH.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--execute',action='store_true'); args=parser.parse_args()
    manifest=build_manifest()
    state_path=HERE/('iek_verified_bindings_state_20261020.json' if args.execute else 'iek_verified_bindings_dry_run_state_20261020.json')
    runner=runner_module.Runner(Client(),manifest,execute=args.execute,journal=JOURNAL,state=state_path)
    runner.process_groups()
    state=json.loads(state_path.read_text())
    summary={'execute':args.execute,'candidate_count':manifest['candidate_count'],'group_results':state.get('groups'),
        'skips':state.get('skips'),'mutations':state.get('mutations'),'state':str(state_path),'manifest':str(MANIFEST_PATH)}
    print(json.dumps(summary,ensure_ascii=False))
    if args.execute and any(x.get('status')!='processed' or x.get('eligible')!=len(next(g for g in manifest['groups'] if g['number']==x['number'])['targets']) for x in state.get('groups',[])):
        raise SystemExit('One or more candidate groups were not fully processed; inspect the state and reconcile live state before retry.')

if __name__=='__main__': main()
