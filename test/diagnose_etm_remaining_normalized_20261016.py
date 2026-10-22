"""Read-only normalized FTP identity candidates, never writes Sheets."""
import json,csv,re,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'test/etm_codes_remaining_20261016.json').read_text())['rows']
def norm(s):
 s=str(s or '').casefold().translate(str.maketrans('авекмнорстух','abekmhopctyx'))
 s=re.sub(r'[^a-zа-яё0-9]','',s)
 return s.lstrip('0')or'0'
keys={norm(x[k])for x in rows for k in ['offer_id','model']};candidates=collections.defaultdict(dict);brandcounts=collections.Counter()
for wh in ['13','14']:
 with (ROOT/f'test/tmp/etm_ftp_downloads/from_etm/{wh}/price.csv').open(encoding='cp1251')as f:
  for r in csv.DictReader(f,delimiter=';'):
   a=norm(r['Артикул']);brandcounts[r['Производитель']]+=1
   if a not in keys:continue
   candidates[a][r['Код ЭТМ']]={k:r[k]for k in ['Код ЭТМ','Артикул','Производитель','Полное наименование','Емкость Упаковки','КратностьРЦ','КратностьОП','Единица измерения']}
result=[]
for x in rows:
 found={}
 for k in ['model','offer_id']:found.update(candidates[norm(x[k])])
 result.append({**x,'normalized_candidates':list(found.values())})
(ROOT/'test/etm_codes_remaining_normalized_20261016.json').write_text(json.dumps({'warning':'Normalization produces candidates only; manufacturer and identity must be confirmed separately.','rows':result,'related_manufacturers':{b:n for b,n in brandcounts.items()if any(s in b.casefold()for s in ['arlight','arlait','арлайт','navigator','inhome','saffit','stekk'])}},ensure_ascii=False,indent=2)+'\n')
print('extra_normalized_candidates',[(x['offer_id'],x['brand'],[(c['Артикул'],c['Производитель'],c['Код ЭТМ'])for c in x['normalized_candidates']])for x in result if x['normalized_candidates']and not x['candidates']])
print('related_manufacturers',{b:n for b,n in brandcounts.items()if any(s in b.casefold()for s in ['arlight','арлайт','navigator','inhome','saffit','stekk'])})
