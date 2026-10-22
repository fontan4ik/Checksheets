import csv,json,hashlib
from pathlib import Path
from collections import Counter
here=Path(__file__).parent
d=json.loads((here/'matched_before_revision.json').read_text())
needed={c for r in d['rows'] for c in ([r[2]] if r[2] else r[15].split(', ')) if c}
items={}
for source in d['ftp']:
    p=Path(source['local']);assert hashlib.sha256(p.read_bytes()).hexdigest()==source['sha256']
    for r in csv.DictReader(p.open(encoding='cp1251',newline=''),delimiter=';'):
        code=r['Код ЭТМ'].strip()
        if code not in needed:continue
        e=items.setdefault(code,dict(article=r['Артикул'].strip(),brand=r['Производитель'].strip(),unit=r['Единица измерения'].strip(),name=r['Полное наименование'],stocks={}))
        q=float(r['Количество'].replace(',','.').replace(' ',''));e['stocks'][source['warehouse']]=int(q) if q.is_integer() else q
rows=[]
for original in d['rows']:
    codes=[original[2]] if original[2] else original[15].split(', ') if original[15] else ['']
    problem=int(original[5]!='Найден')
    for code in codes:
        r=original.copy()
        if code:
            e=items[code];r[2]=code;r[3]=e['stocks'].get('Самара');r[4]=e['stocks'].get('Москва')
            r[7:10]=[e['article'],e['brand'],e['unit']];r[11]=e['name']
            if problem:r[6]='По артикулу; требуется проверка';r[17]='Привязка по артикулу. '+('Несколько кодов ЭТМ: каждый сохранён отдельной строкой. ' if len(codes)>1 else '')+('Бренд Ozon отсутствует; оставлен пустым.' if not r[1] else 'Бренд Ozon сохранён; производитель ЭТМ указан отдельно.')
        else:r[17]='Совпадение в FTP-прайсах не найдено.'
        r.insert(5,problem);rows.append(r)
d['headers'].insert(5,'Проблемные');d['rows']=rows
d['brand_rows']=[[('' if r[0]=='(бренд не указан)' else r[0]),*r[1:]] for r in d['brand_rows']]
d['bound_products']=len({r[13] for r in rows if r[2]})
d['problem_products']=len({r[13] for r in rows if r[5]})
d['bound_problem_products']=len({r[13] for r in rows if r[2] and r[5]})
d['output_rows']=len(rows)
assert len({r[13] for r in rows})==d['total']
assert len({(r[13],r[2]) for r in rows})==len(rows)
prior={r[12]:r for r in json.loads((here/'matched_before_revision.json').read_text())['rows']}
for r in rows:
    assert r[1]==prior[r[13]][1]
    assert r[5] in (0,1)
    if r[2]:assert r[3]==items[r[2]]['stocks'].get('Самара') and r[4]==items[r[2]]['stocks'].get('Москва')
    if r[5]==0:assert prior[r[13]][5]=='Найден' and r[2]==prior[r[13]][2]
special=[r for r in rows if r[0]=='695008-1'];assert {r[2] for r in special}=={'6481407','9870718'} and all(r[5]==1 for r in special)
(here/'matched.json').write_text(json.dumps(d,ensure_ascii=False))
print(json.dumps({k:d[k] for k in ['total','output_rows','bound_products','problem_products','bound_problem_products']},ensure_ascii=False))
