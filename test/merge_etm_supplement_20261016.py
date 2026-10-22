"""Validate and merge supplier-filtered identity evidence, without sheet writes."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import sync_etm_codes as sync

data=json.loads((ROOT/'test/etm_codes_supplement_plan_20261016.json').read_text())
if not data['scope_complete']:
    raise ValueError('Incomplete supplemental review')
incoming=ROOT/'test/etm_supplement_validation_20261016.json'
incoming.write_text(json.dumps({'version':1,'entries':data['confirmed']},ensure_ascii=False,indent=2)+'\n')
new=sync.load_verified_matches(incoming)
records=sync.load_verified_matches()
for offer,record in new.items():
    old=records.get(offer)
    if old and any(sync.normalize(old[k])!=sync.normalize(record[k]) for k in ('model','brand','etm_code')):
        raise ValueError(f'Conflicting prior identity {offer}')
    if old:
        record['evidence']=old['evidence']+[p for p in record['evidence']if p not in old['evidence']]
    records[offer]=record
candidate=ROOT/'test/etm_registry_candidate_20261016.json'
candidate.write_text(json.dumps({'version':1,'reviewed_at':'2026-10-16','entries':sorted(records.values(),key=lambda r:r['offer_id'])},ensure_ascii=False,indent=2)+'\n')
sync.load_verified_matches(candidate)
candidate.replace(ROOT/'etm_code_verified_matches.json')
print(json.dumps({'registry_entries':len(records),'supplement_entries':len(new)}))
