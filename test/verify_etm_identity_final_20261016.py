"""Read back CODES, verify reviewed identities and protect pre-existing values."""
import collections
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import sync_etm_codes as sync

ws=sync.gsheets_utils.get_worksheet(sync.SHEET_NAME)
rows=sync.read_sheet_rows(ws)
cols=sync.resolve_sheet_columns(rows[0])
before=json.loads((ROOT/'test/etm_identity_before_20261016.json').read_text())['values']
oldcols=sync.resolve_sheet_columns(before[0])
def values(data, columns):
    for number,row in enumerate(data[1:],2):
        def value(key):
            return str(row[columns[key]-1]).strip() if len(row)>=columns[key] else ''
        if value('article'):
            yield {'row':number,'offer_id':value('article'),'model':value('model'),
                   'brand':value('brand'),'code':value('etm_code')}
baseline={r['offer_id']:r for r in values(before,oldcols)}
current=list(values(rows,cols))
records=sync.load_verified_matches()
original={r['offer_id']:r for r in json.loads((ROOT/'test/etm_codes_remaining_20261016.json').read_text())['rows']}
changes=[]
mismatches=[]
for row in current:
    previous=baseline.get(row['offer_id'],{})
    if previous.get('code') and previous['code']!=row['code']:
        changes.append({'offer_id':row['offer_id'],'before':previous['code'],'after':row['code']})
    record=records.get(row['offer_id'])
    if record and (row['code']!=record['etm_code'] or
                   sync.normalize(row['model'])!=sync.normalize(record['model']) or
                   sync.normalize(row['brand'])!=sync.normalize(record['brand'])):
        mismatches.append({'offer_id':row['offer_id'],'expected':record['etm_code'],'actual':row['code']})
remaining=[]
for row in current:
    if row['code']:
        continue
    old=original.get(row['offer_id'],{})
    test=row['offer_id'].startswith(('IEK-PROBE','IEK-VAT','QZA-READONLY')) or row['offer_id']=='TEST-1'
    remaining.append({**row,'reason':'intentional_test_offer' if test else 'no_confirmed_etm_identity',
                      'original_reason':old.get('reason'),'original_candidates':old.get('candidates',[])})
report={'at':sync.datetime.now(sync.timezone.utc).isoformat(),'total':len(current),
        'filled':sum(bool(r['code'])for r in current),'blank':len(remaining),
        'initial_blank':len(original),
        'resolved_of_initial_blank':sum(r['offer_id']in original and bool(r['code'])for r in current),
        'new_since_live_baseline':sum(not baseline.get(r['offer_id'],{}).get('code')and bool(r['code'])for r in current),
        'changed_existing':changes,'registry_entries':len(records),'registry_mismatches':mismatches,
        'remaining_by_brand':dict(collections.Counter(r['brand']or'(empty)'for r in remaining)),
        'remaining_by_reason':dict(collections.Counter(r['reason']for r in remaining)),
        'remaining':remaining}
(ROOT/'test/etm_identity_final_verification_20261016.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items()if k!='remaining'},ensure_ascii=False))
if changes or mismatches:
    raise SystemExit(1)
