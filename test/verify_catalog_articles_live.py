"""Read-only verification of catalog completeness and append-only preservation."""
import collections
import json
from pathlib import Path
import re
import gspread

root = Path(__file__).resolve().parents[1]
before = json.loads((root / 'test/catalog_articles_before_20261015.json').read_text())
source = {
    'ozon': set(json.loads((root / 'test/catalog_ozon_articles_20261015.json').read_text())),
    'wb': set(json.loads((root / 'test/catalog_wb_articles_20261015.json').read_text())),
}
book = gspread.service_account(filename=str(root / 'nomadic-bedrock-485314-b0-d7624dedd83c.json')).open_by_key('15d_fAFFFAoBE_ClIhzDxwjRW2IeDFCKpbcqyQapyKhI')
def articles(rows):
    result = []
    for row in rows[1:]:
        if not row:
            continue
        value = str(row[0]).strip()
        match = re.fullmatch(r'="(.*)"', value)
        if match:
            value = match[1]
        if value:
            result.append(value)
    return result
results = {}
for name, old_rows in before.items():
    rows = book.worksheet(name).get('A:A', value_render_option='UNFORMATTED_VALUE')
    displayed = book.worksheet(name).get('A:A', value_render_option='FORMATTED_VALUE')
    old, current_raw = collections.Counter(articles(old_rows)), collections.Counter(articles(rows))
    current = collections.Counter(articles(displayed))
    formats = {}
    for raw, visible in zip(rows[1:], displayed[1:]):
        if raw and visible:
            formats.setdefault(str(raw[0]).strip(), set()).add(str(visible[0]).strip())
    old_visible = collections.Counter()
    for key, count in old.items():
        shown = formats.get(key, {key})
        old_visible[next(iter(shown)) if len(shown) == 1 else key] += count
    expected = source['wb' if name == 'UNIT WB' else 'ozon']
    missing = expected - current.keys()
    lost = old - current_raw
    duplicates = {k: n - max(1, old_visible[k]) for k, n in current.items() if n > max(1, old_visible[k])}
    results[name] = {'added': sum(current_raw.values()) - sum(old.values()), 'missing': len(missing), 'lostExisting': sum(lost.values()), 'newDuplicates': sum(duplicates.values()), 'totalUnique': len(current)}
    print(name, results[name], flush=True)
(root / 'test/catalog_articles_verification_latest.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
raise SystemExit(1 if any(r['missing'] or r['lostExisting'] or r['newDuplicates'] for r in results.values()) else 0)
