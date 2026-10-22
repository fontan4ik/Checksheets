"""Promote reviewed identity evidence into the production registry; no sheet writes."""
import json
import shutil
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sync_etm_codes as sync

plan = json.loads((ROOT/'test/etm_codes_remaining_candidate_plan_20261016.json').read_text())
registry_path = ROOT/'etm_code_verified_matches.json'
records = sync.load_verified_matches(registry_path)
approved_ftp = set(records) | {
    '48948-1','51852-1','49171-5','39592-5','49425-2','51850-1','sq0602-0008',
    '38098-1','41185-1','4690612012223-1','4690612033099-1','4690612033105-5',
    '18015-10','6300','6311','6299','6301','6294','6303','6316','6295','6310',
    '6298','6297','6296','6302-1','6348-1','11858','41162','41160','41163','41161',
    '41175','41176','41177','4690612008769-25','4690612003047-25','4690612003030-25',
    '4690612012223-25','4690612012230-25','4690612012247-25','4690612012254-25',
    '4690612004921-25','2850645А-25','1036322А-25','SNMPSM2-1'
}
for row in plan['rows']:
    if row['decision'] != 'eligible_for_reviewed_registry':
        continue
    code = str(row['recommended_code'])
    proofs = [p for p in row['reviewed_candidates'] if str(p['code']) == code]
    if {str(p['code']) for p in row['reviewed_candidates']} != {code}:
        raise ValueError(f"Conflicting candidates: {row['offer_id']}")
    accepted = []
    for proof in proofs:
        if proof['method'] == 'ETM_API_article_and_manufacturer':
            api = row['direct_api']
            product = api.get('product',{})
            if api.get('http_status') != 200 or api.get('api_status') != 200:
                raise ValueError('Unconfirmed API response')
            if sync.normalize(row['model']) not in {
                sync.normalize(product.get('gdsArt')), sync.normalize(product.get('gdsExtArt'))}:
                continue
            if sync.normalize(row['brand']).replace(' ','') != sync.normalize(product.get('gdsMnfName')).replace(' ',''):
                continue
            if str(product.get('gdsCode')) != code:
                raise ValueError('API code differs from candidate')
            accepted.append(proof)
        elif row['offer_id'] in approved_ftp:
            accepted.append(proof)
    if not accepted:
        continue
    primary = accepted[0]['evidence']
    evidence = []
    for proof in accepted:
        details = proof['evidence']
        is_api = proof['method'] == 'ETM_API_article_and_manufacturer'
        evidence.append({
            'source':'ETM goods API' if is_api else 'ETM FTP warehouses 13/14',
            'url':f"https://ipro.etm.ru/api/v1/goods/{quote(row['model'],safe='')}?type=mnf" if is_api else 'ftp://edi.etm.ru/from_etm/',
            'note':f"{details.get('statement', 'Exact manufacturer article and brand')}; ETM {details['etm_article']} / {details['etm_manufacturer']}: {details['etm_name']}"
        })
    evidence.append({'source':'Ozon seller product identity',
                     'url':'https://api-seller.ozon.ru/v3/product/info/list',
                     'note':row['marketplace']['name']})
    record = {'offer_id':row['offer_id'],'model':row['model'],'brand':row['brand'],
              'etm_code':code,'etm_article':primary['etm_article'],
              'etm_manufacturer':primary['etm_manufacturer'],'evidence':evidence}
    previous = records.get(row['offer_id'])
    if previous and previous['etm_code'] != code:
        raise ValueError(f"Existing reviewed code conflict: {row['offer_id']}")
    if previous:
        record['evidence'] = previous['evidence'] + [p for p in evidence if p not in previous['evidence']]
    records[row['offer_id']] = record

candidate = ROOT/'test/etm_registry_candidate_20261016.json'
candidate.write_text(json.dumps({'version':1,'reviewed_at':'2026-10-16',
    'entries':sorted(records.values(),key=lambda r:r['offer_id'])},ensure_ascii=False,indent=2)+'\n')
sync.load_verified_matches(candidate)
backup = ROOT/'test/etm_verified_registry_before_expand_20261016.json'
if not backup.exists():
    shutil.copy2(registry_path,backup)
candidate.replace(registry_path)
print(json.dumps({'registry_entries':len(records),'api_queries_reviewed':plan['api_queries_available']}))
