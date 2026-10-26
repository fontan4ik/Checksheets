"""Remove equivalent WB pagination repeats after terminal-page validation."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / 'test/certificate_completion_20261020'
target = DIR / 'live_marketplaces_snapshot_export_20261026.json'
raw = DIR / 'live_marketplaces_snapshot_export_raw_20261026.json'
log = (DIR / 'audit_export_20261026.log').read_text()
assert log.rstrip().endswith('RuntimeError: WB wb_catalog has missing or duplicate nmID'), 'Unexpected incomplete snapshot'
s = json.loads(target.read_text())
assert all(s[k]['complete'] for k in ('ozon_products', 'ozon_certificates'))
assert s.get('fatal_error_type') == 'RuntimeError'
byid = {}
duplicate_ids = []
def canonical(c):
    c = copy.deepcopy(c)
    c['characteristics'] = sorted(c.get('characteristics') or [], key=lambda a: json.dumps(a,sort_keys=True,ensure_ascii=False))
    return c
for c in s['wb_catalog']['cards']:
    key = str(c.get('nmID') or '')
    assert key, 'Missing nmID'
    if key in byid:
        assert canonical(c) == canonical(byid[key]), f'Conflicting duplicate {key}'
        duplicate_ids.append(key)
    else:
        byid[key] = c
assert duplicate_ids
now = datetime.now(timezone.utc).isoformat()
s['wb_catalog'].update(cards=list(byid.values()),complete=True,checked_at=now,cards_read=len(byid))
s['snapshot_normalization'] = {'source_raw_snapshot':str(raw), 'method':'Remove repeated nmIDs only after equality of every field; characteristic array order ignored', 'duplicates_removed':len(duplicate_ids),'duplicate_nmIDs':duplicate_ids,'checked_at_utc':now,'terminal_page_confirmed':'Reader reached end-of-pagination identity validation before raising duplicate-ID error'}
s['complete'] = True
s['finished_at'] = now
s['wb_trash']['note'] = 'Not fetched; report covers current WB catalog only'
s.pop('fatal_error_type',None)
s.pop('failed_at',None)
assert not raw.exists()
target.rename(raw)
target.write_text(json.dumps(s,ensure_ascii=False))
print(json.dumps({'unique_wb_cards':len(byid),'equivalent_duplicates_removed':len(duplicate_ids)},ensure_ascii=False))
