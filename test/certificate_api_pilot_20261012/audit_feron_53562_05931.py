from __future__ import annotations
import collections, json, re, sys, time, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now, save

FERON = Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
WORKBOOK = FERON / 'Сопоставление_артикулов_и_файлов_документов.xlsx'
NS={'a':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
FSA_URL='https://pub.fsa.gov.ru/rds/declaration/view/17025635/common'
FSA_PRODUCTS_URL='https://pub.fsa.gov.ru/rds/declaration/view/17025635/product'
FSA_CODE='9405420012'
DOCS={'53562/22':'declaration','05931/22':'certificate_of_conformity'}
OUT=BASE/'feron_53562_05931_live_preflight_20261012.json'

def norm(s):
    tr=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Д':'D','Ё':'E','Э':'E'})
    return ''.join(c for c in str(s or '').upper().translate(tr) if c.isalnum())

def xlsx_rows():
    with zipfile.ZipFile(WORKBOOK) as z:
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rels={x.attrib['Id']:x.attrib['Target'].lstrip('/') for x in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        strings=[''.join(t.text or '' for t in x.findall('.//a:t',NS)) for x in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('a:si',NS)]
        sh=next(x for x in wb.findall('a:sheets/a:sheet',NS) if x.attrib['name']=='Артикул-файл')
        root=ET.fromstring(z.read(rels[sh.attrib[f"{{{NS['r']}}}id"]]))
    out=[]
    for row in root.findall('a:sheetData/a:row',NS):
        vals={}
        for c in row.findall('a:c',NS):
            col=''.join(ch for ch in c.attrib['r'] if ch.isalpha())
            v=c.find('a:v',NS)
            value=v.text if v is not None else ''
            if c.attrib.get('t')=='s' and value: value=strings[int(value)]
            elif c.attrib.get('t')=='inlineStr': value=''.join(t.text or '' for t in c.findall('.//a:t',NS))
            vals[col]=value
        if vals.get('A') and vals.get('G'):
            out.append(vals)
    return out

def attr_values(item, attr_id):
    result=[]
    for a in item.get('attributes') or []:
        if str(a.get('id')) != str(attr_id): continue
        values=a.get('values') or a.get('value') or []
        if not isinstance(values,list): values=[values]
        for v in values:
            if isinstance(v,dict): result.append(str(v.get('value') or v.get('text') or v.get('name') or ''))
            else: result.append(str(v))
    return [x for x in result if x]

def wb_codes(card):
    rows=[x for x in card.get('characteristics') or [] if str(x.get('id'))=='15000001']
    if len(rows)>1: raise RuntimeError('duplicate WB TNVED attribute')
    vals=rows[0].get('value') if rows else []
    if not isinstance(vals,list): vals=[vals] if vals is not None else []
    return [str(x).strip() for x in vals if str(x).strip()]

def binding_read(client,cid):
    items=[]; last_id=0; expected=None
    while True:
        data=client.call('ozon','/v1/product/certificate/products/list',{'certificate_id':int(cid),'limit':500,'last_id':last_id}).get('result',{})
        batch=data.get('items'); count=data.get('count')
        if not isinstance(batch,list) or not isinstance(count,int): raise RuntimeError(f'bad bindings {cid}')
        if expected is None: expected=count
        elif expected!=count: raise RuntimeError(f'count changed {cid}')
        items.extend(batch)
        if len(items)==expected: return items
        if not batch or len(items)>expected: raise RuntimeError(f'incomplete bindings {cid}')
        nxt=int(batch[-1].get('product_id') or 0)
        if nxt<=last_id: raise RuntimeError(f'cursor did not advance {cid}')
        last_id=nxt

rows=xlsx_rows()
target_by_doc={}
for suffix in DOCS:
    matches=[r for r in rows if suffix in r.get('G','')]
    if not matches: raise RuntimeError('no workbook rows '+suffix)
    target_by_doc[suffix]=matches
base_rows=target_by_doc['53562/22']
unique_offers={r['A']:r for r in base_rows}
if len(base_rows)!=len(unique_offers): raise RuntimeError('duplicate offer in workbook rows')
if {r['A'] for r in base_rows}!={r['A'] for r in target_by_doc['05931/22']}: raise RuntimeError('document offer sets diverge')
if any(not r.get('D') or not r.get('E') for r in base_rows): raise RuntimeError('missing workbook Ozon identity')
if any(r.get('O') for r in base_rows): raise RuntimeError('manual-review rows require case review')
copy_audit={}
for suffix in DOCS:
    docrows=target_by_doc[suffix]
    original_name=docrows[0].get('R','')
    original=FERON/'00_Оригиналы_файлов'/original_name
    copies=[]
    for row in docrows:
        path=FERON/row['H']
        copies.append({'offer_id':row['A'],'path':str(path),'exists':path.is_file(),'sha256':digest(path) if path.is_file() else None})
    copy_audit[suffix]={'row_count':len(docrows),'unique_offer_count':len({r['A'] for r in docrows}),
        'original_path':str(original),'original_exists':original.is_file(),'original_sha256':digest(original) if original.is_file() else None,
        'copy_count':len(copies),'all_copies_exist':all(x['exists'] for x in copies),
        'copy_hash_counts':dict(collections.Counter(x['sha256'] for x in copies)),
        'all_copies_match_original':original.is_file() and all(x['sha256']==digest(original) for x in copies),
        'copies':copies}

client=Client()
products={}
offers=sorted(unique_offers)
for i in range(0,len(offers),100):
    body=client.call('ozon','/v3/product/info/list',{'offer_id':offers[i:i+100]})
    items=body.get('items') or body.get('result',{}).get('items')
    if not isinstance(items,list): raise RuntimeError('bad Ozon product info')
    for item in items:
        offer=str(item.get('offer_id'))
        if offer in products: raise RuntimeError('duplicate Ozon offer '+offer)
        products[offer]={'product_id':str(item.get('id')),'sku':str(item.get('sku')),
            'is_archived':bool(item.get('is_archived')),'name':item.get('name'),
            'tnved_attribute_22232':attr_values(item,22232)}
if set(products)!=set(unique_offers): raise RuntimeError('Ozon live offer set does not equal workbook target')
identity_errors=[]
for offer,row in unique_offers.items():
    live=products[offer]
    if live['product_id']!=str(row['D']) or live['sku']!=str(row['E']):
        identity_errors.append({'offer_id':offer,'workbook':{'product_id':row['D'],'sku':row['E']},'live':live})

certificates=[]
for page in range(1,101):
    res=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result',{})
    batch=res.get('certificates')
    if not isinstance(batch,list): raise RuntimeError('bad Ozon certificate list')
    certificates.extend(batch)
    if len(batch)<100: break
else: raise RuntimeError('Ozon certificate page limit')
cert_match={}
for suffix,typ in DOCS.items():
    hits=[c for c in certificates if c.get('type_code')==typ and norm(c.get('certificate_number','')).endswith(norm(suffix))]
    cert_match[suffix]=[]
    for c in hits:
        binds=binding_read(client,c['certificate_id'])
        counts=collections.Counter(str(x.get('product_status_code') or 'MISSING') for x in binds)
        target_skus={str(r['E']) for r in target_by_doc[suffix]}
        actual={str(x.get('sku')):str(x.get('product_id')) for x in binds}
        cert_match[suffix].append({'certificate_id':str(c['certificate_id']),'certificate_number':c.get('certificate_number'),
            'type_code':c.get('type_code'),'status_code':c.get('status_code'),'issue_date':c.get('issue_date'),
            'expire_date':c.get('expire_date'),'binding_count':len(binds),'binding_status_counts':dict(counts),
            'target_binding_count':len(target_skus & set(actual)),'missing_target_skus':sorted(target_skus-set(actual)),
            'outside_target_skus':sorted(set(actual)-target_skus),
            'product_id_mismatches':[{'sku':s,'expected':str(next(r['D'] for r in target_by_doc[suffix] if str(r['E'])==s)),'actual':actual[s]}
                                     for s in sorted(target_skus & set(actual))
                                     if actual[s]!=str(next(r['D'] for r in target_by_doc[suffix] if str(r['E'])==s))],
            'all_target_bindings_approved':target_skus.issubset(actual) and all(x.get('product_status_code')=='approved' for x in binds if str(x.get('sku')) in target_skus),
            'all_bindings':binds})

wb={}; missing=[]; duplicates=[]; failures=[]
state={'started_at':now(),'workbook_target_count':len(base_rows),'wb_read_count':0,'wb_cards_by_offer':{},'wb_missing':missing,'wb_duplicates':duplicates,'wb_failures':failures}
save(OUT.name,state)
for idx,offer in enumerate(offers,1):
    try:
        cards=client.wb_cards(offer)
        cards=[c for c in cards if str(c.get('vendorCode'))==offer]
        if not cards: missing.append(offer)
        elif len(cards)>1: duplicates.append({'offer_id':offer,'nmIDs':[str(c.get('nmID')) for c in cards]})
        else:
            c=cards[0]
            wb[offer]={'nmID':str(c.get('nmID')),'vendorCode':str(c.get('vendorCode')),
                'tnved_values':wb_codes(c),'name':c.get('title'),
                'document_rows':c.get('documents',{}).get('items') or [],
                'overallVerdict':c.get('documents',{}).get('overallVerdict'),
                'excludeDocuments':c.get('documents',{}).get('excludeDocuments')}
    except Exception as e:
        failures.append({'offer_id':offer,'error_type':type(e).__name__,'error':str(e)})
    state['wb_read_count']=idx
    if idx%20==0 or idx==len(offers):
        state['wb_cards_by_offer']=wb; state['updated_at']=now(); save(OUT.name,state)
        print(json.dumps({'wb_read':idx,'target_count':len(offers),'cards':len(wb),'missing':len(missing),'duplicates':len(duplicates),'failures':len(failures)},ensure_ascii=False),flush=True)

wb_summary={}
for suffix,typ in DOCS.items():
    doc_rows=0; valid_rows=0; statuses=collections.Counter(); missing_doc=[]; wrong_dates=[]
    for offer,card in wb.items():
        exact=[d for d in card['document_rows'] if int(d.get('type') or 0)==(2 if typ=='declaration' else 1) and norm(d.get('number','')).endswith(norm(suffix))]
        if len(exact)==1:
            d=exact[0]; doc_rows+=1
            verdict=d.get('verdict') or {}
            statuses[f"{verdict.get('status')}:{verdict.get('reason')}:{verdict.get('verified')}"]+=1
            if verdict.get('verified') is True and verdict.get('status')==1: valid_rows+=1
        else: missing_doc.append({'offer_id':offer,'match_count':len(exact)})
    wb_summary[suffix]={'card_count':len(wb),'exact_document_card_count':doc_rows,'final_valid_card_count':valid_rows,
        'verdict_counts':dict(statuses),'missing_or_duplicate_document_rows':missing_doc}

# Current TNVED mapping: only exact code 9405420012 is within the FSA product entry.
ozon_tnved_counts=collections.Counter()
for item in products.values():
    codes={v.split(' ',1)[0].strip() for v in item['tnved_attribute_22232'] if v.strip()}
    ozon_tnved_counts['|'.join(sorted(codes)) if codes else '(missing)']+=1
wb_tnved_counts=collections.Counter()
for item in wb.values():
    codes={v.split(' ',1)[0].strip() for v in item['tnved_values'] if v.strip()}
    wb_tnved_counts['|'.join(sorted(codes)) if codes else '(missing)']+=1

out={'checked_at_utc':now(),'audit_type':'read_only_preflight','fsa':{'record_id':17025635,'common_url':FSA_URL,'product_url':FSA_PRODUCTS_URL,
    'status':'Действует','number':'ЕАЭС N RU Д-CN.РА06.В.53562/22','registration_date':'2022-09-15','valid_through':'2027-09-14',
    'applicant':'ООО СИЛА СВЕТА','scope':'Прожекторы светодиодные общего назначения, Feron series/type LL','tnved_code':FSA_CODE},
    'workbook':{'path':str(WORKBOOK),'sha256':digest(WORKBOOK),'53562_rows':len(target_by_doc['53562/22']),
        '05931_rows':len(target_by_doc['05931/22']),'offer_set_equal':{r['A'] for r in target_by_doc['53562/22']}=={r['A'] for r in target_by_doc['05931/22']},
        'offers':offers,'manual_review_flags':[{'offer_id':r['A'],'flag':r.get('O')} for r in base_rows if r.get('O')],
        'scope_evidence_counts':dict(collections.Counter(r.get('N','') for r in base_rows))},
    'local_files':copy_audit,'ozon':{'live_offer_count':len(products),'identity_mismatches':identity_errors,
        'archived_offers':[o for o,v in products.items() if v['is_archived']],
        'tnved_counts':dict(ozon_tnved_counts),'certificate_list_count':len(certificates),
        'matching_records_by_document':cert_match,'product_rows':products},
    'wildberries':{'read_count':len(wb),'missing_cards':missing,'duplicate_cards':duplicates,'failures':failures,
        'tnved_counts':dict(wb_tnved_counts),'document_coverage':wb_summary,'cards_by_offer':wb},
    'write_performed':False,'cleanup_allowed':False}
save(OUT.name,out)
print(json.dumps({'audit_path':str(OUT),'workbook_targets':len(offers),'ozon_identity_errors':len(identity_errors),
    'ozon_archived':sum(v['is_archived'] for v in products.values()),'ozon_tnved_counts':dict(ozon_tnved_counts),
    'matching_ozon_records':{s:[{'id':r['certificate_id'],'number':r['certificate_number'],'status':r['status_code'],'bindings':r['binding_status_counts'],'target':r['target_binding_count'],'missing':len(r['missing_target_skus'])} for r in rs] for s,rs in cert_match.items()},
    'wb_missing':len(missing),'wb_duplicates':len(duplicates),'wb_failures':len(failures),'wb_tnved_counts':dict(wb_tnved_counts),
    'wb_document_coverage':{s:{k:v for k,v in d.items() if k not in ['missing_or_duplicate_document_rows']} for s,d in wb_summary.items()},
    'files':{s:{k:v for k,v in d.items() if k not in ['copies']} for s,d in copy_audit.items()}},ensure_ascii=False,indent=2),flush=True)
