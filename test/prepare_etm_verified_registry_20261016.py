"""Build reviewed manufacturer-family matches; no sheet writes."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sync_etm_codes as sync

evidence = json.loads((ROOT / 'test/etm_dkc_stekker_primary_evidence_20261016.json').read_text())
identities = {r['offer_id']:r['marketplace'] for r in json.loads(
    (ROOT / 'test/etm_remaining_marketplace_identity_20261016.json').read_text())['rows']}
entries = []
for row in evidence['candidate_rows']:
    expected = {'dkc':'dkc it', 'stekker':'feron'}[sync.normalize(row['brand'])]
    candidates = [c for c in row['ftp_candidates']
                  if sync.normalize(c['Производитель']) == expected
                  and sync.normalize(c['Артикул']) == sync.normalize(row['model'])]
    codes = {sync.normalize_code(c['Код ЭТМ']) for c in candidates}
    if len(codes) != 1:
        raise ValueError(f"Nonunique candidate {row['offer_id']}")
    candidate = candidates[0]
    entries.append({
        'offer_id':row['offer_id'], 'model':row['model'], 'brand':row['brand'],
        'etm_code':codes.pop(), 'etm_article':candidate['Артикул'],
        'etm_manufacturer':candidate['Производитель'],
        'evidence':[
            {'source':'ETM FTP warehouses 13/14',
             'url':'ftp://edi.etm.ru/from_etm/13/price.csv',
             'note':f"Exact manufacturer article; {candidate['Полное наименование']}"},
            {'source':'Manufacturer official catalog',
             'url':'https://www.dkc.ru/ru/catalog/668/' if expected=='dkc it' else 'https://stekker.ru/upload/qr/Catalog/Stekker_2025.pdf',
             'note':'DKC IT product family of DKC; article verified' if expected=='dkc it' else 'Stekker exact article/model; Feron brand relationship https://feron.ru/about/'},
            {'source':'Ozon seller product identity',
             'url':'https://api-seller.ozon.ru/v3/product/info/list',
             'note':identities[row['offer_id']]['name']}
        ]
    })
path = ROOT / 'etm_code_verified_matches.json'
path.write_text(json.dumps({'version':1,'reviewed_at':'2026-10-16','entries':entries},ensure_ascii=False,indent=2)+'\n')
records = sync.load_verified_matches(path)
ws = sync.gsheets_utils.get_worksheet(sync.SHEET_NAME)
rows = sync.read_sheet_rows(ws)
snapshot = ROOT / 'test/etm_identity_before_20261016.json'
if not snapshot.exists():
    snapshot.write_text(json.dumps({'values':rows},ensure_ascii=False))
planned, stats = sync.plan_verified_updates(rows,sync.resolve_sheet_columns(rows[0]),records)
print(json.dumps({'entries':len(entries),'eligible':len(planned),'stats':stats},ensure_ascii=False))
