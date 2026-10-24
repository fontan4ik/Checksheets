from __future__ import annotations
import csv, hashlib, json, pathlib, sys
from collections import Counter

HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now  # noqa:E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa:E402

NUMBER='ЕАЭС RU С-HK.АЖ56.В.04297/24'; ISSUE='2024-04-16'; EXPIRY='2029-04-15'; FSA_ID='3420033'
FILE=ROOT/'output_to_user/certificates/group_2/JAZZWAY/documents/svetilniki-ppl-psp-pled-vstraivaemye-ss-tr-ts-004-020-15.04.2029_6a82b17ac896.pdf'
SHA='6a82b17ac896ce378096a92fb75647c11da3fa236e4ae5248a2c3f39c7bb7445'
OUT=HERE/'jazzway_04297_crossplatform_preflight_20261024.json'

def vals(row, aid):
    attrs={str(x.get('id')):x for x in row.get('attributes') or []}
    return [str(x.get('value') or '').strip() for x in ((attrs.get(str(aid)) or {}).get('values') or []) if str(x.get('value') or '').strip()]
def codes(v): return sorted({str(x).split(' - ',1)[0].strip() for x in v if str(x).strip()})
def wb_codes(card):
    out=[]
    for x in card.get('characteristics') or []:
        n=''.join(str(x.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' in n or 'тнвед' in n:
            v=x.get('value');out.extend(v if isinstance(v,list) else [v])
    return codes([str(x) for x in out if x])
def certs(c):
    out=[]
    for page in range(1,101):
        r=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; b=r.get('certificates')
        if not isinstance(b,list):raise RuntimeError('ozon_certificate_list_incomplete')
        out.extend(b)
        if not b or page>=int(r.get('page_count') or 0):return out
    raise RuntimeError('ozon_certificate_list_limit')
def main():
    if OUT.exists():raise RuntimeError('preflight_exists_reconcile_before_overwrite')
    if not FILE.is_file() or hashlib.sha256(FILE.read_bytes()).hexdigest()!=SHA:raise RuntimeError('source_pdf_hash_mismatch')
    rows=[]
    with (ROOT/'output_to_user/certificates/document_assignments.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r.get('Номер/название документа')==NUMBER:
                rows.append({'offer_id':r.get('Артикул продавца','').strip(),'brand':r.get('Бренд подтвержденный'),
                             'applicability':r.get('Применимость'),'file':r.get('Локальный файл'),
                             'sha256':r.get('SHA256 фактический'),'source_url':r.get('URL документа')})
    offers=sorted({x['offer_id'] for x in rows})
    if len(rows)!=39 or len(offers)!=39 or any(x['brand']!='Jazzway' or x['applicability']!='Подтверждено статусом покрытия' or x['sha256']!=SHA for x in rows):
        raise RuntimeError('assignment_rows_not_exactly_confirmed_39')
    c=Client()
    products=c.call('ozon','/v3/product/info/list',{'offer_id':offers}).get('items') or []
    attrs=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':len(offers)}).get('result') or []
    if len(products)!=39 or len(attrs)!=39:raise RuntimeError('fresh_ozon_count_mismatch')
    pby={str(x.get('offer_id') or ''):x for x in products}; aby={str(x.get('offer_id') or ''):x for x in attrs}
    if set(pby)!=set(offers) or set(aby)!=set(offers):raise RuntimeError('fresh_ozon_offer_set_mismatch')
    oz=[]
    for offer in offers:
        p,a=pby[offer],aby[offer];brand=vals(a,'85');tnv=codes(vals(a,'22232'))
        oz.append({'offer_id':offer,'product_id':str(p.get('product_id') or p.get('id') or ''),'sku':str(p.get('sku') or ''),
                   'brand':brand,'tnved':tnv,'is_archived':p.get('is_archived'),'name':p.get('name'),
                   'safe':p.get('is_archived') is False and brand==['Jazzway'] and tnv==['9405110033']})
    found=[x for x in certs(c) if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
    wb=[]
    for i,offer in enumerate(offers,1):
        cards=[x for x in c.wb_cards(offer) if str(x.get('vendorCode') or '')==offer]
        if len(cards)!=1:wb.append({'offer_id':offer,'exact_card_count':len(cards),'safe':False});continue
        card=cards[0]; same=[x for x in ((card.get('documents') or {}).get('items') or []) if norm_number(x.get('number'))==norm_number(NUMBER)]
        exact=[x for x in same if str(x.get('type'))=='1' and str(x.get('startDate') or '')[:10]==ISSUE and str(x.get('endDate') or '')[:10]==EXPIRY and x.get('isEndless') is False]
        tnv=wb_codes(card)
        wb.append({'offer_id':offer,'nmID':str(card.get('nmID') or ''),'brand':card.get('brand'),'tnved':tnv,
                   'same_number_docs':same,'already_exact':len(same)==1 and len(exact)==1,
                   'safe':str(card.get('brand') or '').casefold() in {'jazzway','jazz way'} and tnv==['9405110033'] and not same})
        if i%20==0:print(f'read_wb_cards={i}/39',flush=True)
    result={'checked_at_utc':now(),'read_only':True,'document':{'number':NUMBER,'type':'certificate_of_conformity','fsa_record_id':FSA_ID,
        'fsa_url':f'https://pub.fsa.gov.ru/rss/certificate/view/{FSA_ID}/baseInfo','fsa_status':'Действует','issue_date':ISSUE,'expire_date':EXPIRY,
        'fsa_tnved':['9405110033'],'fsa_product_scope':'JAZZWAY/ФАZA recessed ceiling LED luminaires, model series PPL/PSP/PLED including PLED DL6; production from tested sample date 12.2023',
        'source_file':str(FILE.relative_to(ROOT)),'source_sha256':SHA,'source_official_url':'https://jazz-way.com/docs/sertifikaty/svetilniki-ppl-psp-pled-vstraivaemye-ss-tr-ts-004-020-15.04.2029.pdf'},
        'assignment_count':len(rows),'assignment_rows':rows,'ozon_target_count':len(oz),'ozon_safe_count':sum(x['safe'] for x in oz),
        'ozon_tnved_counts':dict(Counter(c for x in oz for c in x['tnved'])),'ozon_exact_records':[{k:x.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date','products_count')} for x in found],
        'ozon_targets':oz,'wb_target_count':len(wb),'wb_safe_count':sum(x.get('safe',False) for x in wb),'wb_already_exact_count':sum(x.get('already_exact',False) for x in wb),
        'wb_tnved_counts':dict(Counter(c for x in wb for c in x.get('tnved',[]))),'wb_targets':wb,'no_mutations':True,'local_file_deleted':False}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'artifact':str(OUT),'checked_at_utc':result['checked_at_utc'],'ozon':{'targets':39,'safe':result['ozon_safe_count'],'tnved_counts':result['ozon_tnved_counts'],'records':result['ozon_exact_records']},
        'wb':{'targets':39,'safe':result['wb_safe_count'],'already_exact':result['wb_already_exact_count'],'tnved_counts':result['wb_tnved_counts']},'no_mutations':True},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
