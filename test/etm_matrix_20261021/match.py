import csv,json,re,unicodedata,hashlib,math
from pathlib import Path
from collections import defaultdict,Counter

here=Path(__file__).parent
api=json.loads((here.parent/'ozon_etm_matrix_api_20261021.json').read_text())
manifest=json.loads((here/'ftp_manifest.json').read_text())
def norm(v):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(v)).translate(str.maketrans({'–':'-','—':'-','−':'-','‑':'-'}))).upper()
aliases={'INHOME':'INHOME','NAVIGATOR':'NAVIGATORGROUP','ОНЛАЙТ':'NAVIGATORGROUP','ONLIGHT':'NAVIGATORGROUP','SCHNEIDERELECTRIC':'SE(SCHNEIDER)','SYSTEMEELECTRIC':'SESYSTEME','DEKRAFT':'SEDEKRAFT','LEGRAND':'LEGRANDEURO','ФАZА':'ФАЗА','ФАZA':'ФАЗА'}
def brand(v):
    n=norm(v);return aliases.get(n,n)
items={}; by_article=defaultdict(set); source_counts={}; conflicts=set()
for f in manifest:
    p=Path(f['local']); assert hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256']
    rows=csv.DictReader(p.open(encoding='cp1251',newline=''),delimiter=';'); count=0
    seen={}
    for row in rows:
        code=row['Код ЭТМ'].strip(); art=row['Артикул'].strip(); b=row['Производитель'].strip(); unit=row['Единица измерения'].strip()
        if not code: raise ValueError('Missing ETM code')
        q=float(row['Количество'].replace(',','.').replace('\xa0','').replace(' ','')); assert math.isfinite(q) and q>=0
        q=int(q) if q.is_integer() else q
        identity=(norm(art),brand(b),unit)
        if code in seen and seen[code]!=(identity,q): raise ValueError('Conflicting duplicate warehouse code '+code)
        seen[code]=(identity,q)
        if code not in items: items[code]=dict(code=code,article=art,brand=b,unit=unit,name=row['Полное наименование'],stocks={})
        e=items[code]
        if (norm(e['article']),brand(e['brand']),e['unit'])!=identity: conflicts.add(code)
        e['stocks'][f['warehouse']]=q;by_article[norm(art)].add(code);count+=1
    source_counts[f['warehouse']]=dict(rows=count,codes=len(seen))

headers=['Артикул Ozon','Бренд Ozon','Код ЭТМ','Остаток ЭТМ Самара','Остаток ЭТМ Москва','Статус','Способ сопоставления','Артикул ЭТМ','Производитель ЭТМ','Единица ЭТМ','Название Ozon','Название ЭТМ','Product ID Ozon','SKU Ozon','В архиве Ozon','Коды-кандидаты','Производители кандидатов','Примечание']
output=[]; stats=Counter(); brand_stats=defaultdict(Counter)
for p in api['rows']:
    article=p['offer_id']; full=norm(article); base=re.sub(r'-\d+$','',full)
    keys=list(dict.fromkeys([full,base])); codes=set().union(*(by_article.get(k,set()) for k in keys))
    same={c for c in codes if brand(items[c]['brand'])==brand(p['brand']) and p['brand'] and p['brand']!='Нет бренда'}
    exact_same={c for c in same if norm(items[c]['article'])==full}
    if exact_same:same=exact_same
    method=''; selected=None; note=''
    if len(same)==1:
        code=next(iter(same))
        if code in conflicts: status='Конфликт данных ЭТМ'
        else:
            selected=items[code]; status='Найден'
            method='Без суффикса '+full[len(base):]+' + бренд' if base!=full and norm(selected['article'])==base else 'Артикул + бренд'
            if norm(p['brand'])!=norm(selected['brand']):method+=' (названия бренда согласованы)'
    elif len(same)>1:status='Несколько кодов ЭТМ'
    elif codes: status='Проверить бренд';note='Артикул найден, бренд не совпал или не указан в Ozon'
    else:status='Нет в FTP-выгрузке'
    if selected:
        stocks=selected['stocks'];sc=stocks.get('Самара');mc=stocks.get('Москва')
        if sc is None or mc is None:note='Код отсутствует в прайсе '+('Самары' if sc is None else 'Москвы')+'; пустой остаток не означает ноль'
    else:sc=mc=None
    e=selected or {}
    row=[article,p['brand'],e.get('code',''),sc,mc,status,method,e.get('article',''),e.get('brand',''),e.get('unit',''),p['name'],e.get('name',''),p['product_id'],p['sku'],'Да' if p['archived'] else 'Нет',', '.join(sorted(codes)) if not selected else '',', '.join(sorted({items[c]['brand'] for c in codes})) if not selected else '',note.strip('; ')]
    output.append(row);stats[status]+=1;brand_stats[p['brand'] or '(бренд не указан)'][status]+=1
assert len(output)==api['total'] and len({r[12] for r in output})==len(output)
assert sum(stats.values())==len(output)
for row in output:
    if row[2]:
        e=items[row[2]];assert row[3]==e['stocks'].get('Самара') and row[4]==e['stocks'].get('Москва')
        assert brand(row[1])==brand(e['brand'])
        assert norm(e['article']) in (norm(row[0]),re.sub(r'-\d+$','',norm(row[0])))
    else:assert row[3] is None and row[4] is None
output.sort(key=lambda r:(r[1].casefold(),r[0].casefold(),r[12]))
brand_rows=[]
for b,c in sorted(brand_stats.items(),key=lambda t:-sum(t[1].values())):
    brand_rows.append([b,sum(c.values()),c['Найден'],c['Нет в FTP-выгрузке'],c['Проверить бренд'],c['Несколько кодов ЭТМ']+c['Конфликт данных ЭТМ']])
result=dict(headers=headers,rows=output,brand_rows=brand_rows,stats=dict(stats),total=api['total'],api_at=api['at'],archived=api['archived_total'],ftp=manifest,source_counts=source_counts,conflictingCodes=len(conflicts),matched_positive_smr=sum(r[3] is not None and r[3]>0 for r in output),matched_positive_msk=sum(r[4] is not None and r[4]>0 for r in output))
(here/'matched.json').write_text(json.dumps(result,ensure_ascii=False))
print(json.dumps({k:v for k,v in result.items() if k not in ('rows','brand_rows','headers','ftp')},ensure_ascii=False,indent=2))
print('Problem examples:',json.dumps([r[:10]+r[15:] for r in output if r[5] not in ('Найден','Нет в FTP-выгрузке')][:15],ensure_ascii=False))
