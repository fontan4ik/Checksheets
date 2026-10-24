from __future__ import annotations
import csv, hashlib, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number
NUMBER='ЕАЭС N RU Д-CN.РА03.В.38441/22'
TYPE='declaration'
FILE=ROOT/'output_to_user/certificates/group_1/documents/gauss/022350fc738de01663d0f848.pdf'
SHA='c76f8b5865411c71fb02db6812f4ff882f8751b8336242e7f1abbf9f9d00bb4a'
FSA_ID='16706705'
OUT=HERE/'gauss_38441_crossplatform_preflight_20261024.json'

def vals(attrs,aid):
    rows={str(a.get('id')):a for a in attrs or []}
    return [str(v.get('value') or '').strip() for v in (rows.get(str(aid)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def exact_wb(c,offer):
    r=c.call('wb','/content/v2/get/cards/list',{'settings':{'sort':{'ascending':True},'cursor':{'limit':100},'filter':{'withPhoto':-1,'textSearch':offer}}})
    if r.get('error') or not isinstance(r.get('cards'),list):raise RuntimeError('WB card read incomplete '+offer)
    return [x for x in r['cards'] if x.get('vendorCode')==offer]
def main():
    if OUT.exists():raise RuntimeError('Output exists; inspect it before rerunning')
    if not FILE.is_file() or digest(FILE).lower()!=SHA:raise RuntimeError('Source PDF missing or SHA mismatch')
    rows=[]
    with (ROOT/'output_to_user/certificates/document_assignments.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if norm_number(r.get('Номер/название документа',''))==norm_number(NUMBER):rows.append(r)
    offers=sorted({r['Артикул продавца'] for r in rows})
    if len(rows)!=12 or len(offers)!=12:raise RuntimeError(f'Expected 12 source rows/offers, got {len(rows)}/{len(offers)}')
    c=Client()
    products=c.call('ozon','/v3/product/info/list',{'offer_id':offers}).get('items') or []
    attrs=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':len(offers)}).get('result') or []
    by_offer={str(x.get('offer_id')):x for x in products};a_by={str(x.get('offer_id')):x for x in attrs}
    if set(by_offer)!=set(offers) or set(a_by)!=set(offers):raise RuntimeError('Fresh Ozon identities/attributes incomplete')
    certs=[]
    for page in range(1,101):
        result=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
        batch=result.get('certificates')
        if not isinstance(batch,list):raise RuntimeError('Ozon certificate listing incomplete')
        certs.extend(batch)
        if len(batch)<100:break
    else:raise RuntimeError('Ozon certificate page limit reached')
    exact_records=[x for x in certs if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
    wb=[];result_targets=[]
    for offer in offers:
        p=by_offer[offer];a=a_by[offer]
        pid=str(p.get('product_id') or p.get('id') or '');sku=str(p.get('sku') or '')
        brand=vals(a.get('attributes'),85);tnved=vals(a.get('attributes'),22232)
        if not pid or not sku or p.get('is_archived') is not False:raise RuntimeError('Ozon identity missing or archived: '+offer)
        if not any(v.casefold()=='gauss' for v in brand):raise RuntimeError('Ozon brand mismatch: '+offer)
        cards=exact_wb(c,offer)
        if len(cards)>1:raise RuntimeError('Duplicate WB exact cards: '+offer)
        card=cards[0] if cards else None
        wb_tnved=[]
        if card:
            for ch in (card.get('characteristics') or []):
                if str(ch.get('name') or '').casefold()=='тнвэд' or str(ch.get('id')) in ('15000001','22232'):
                    v=ch.get('value');wb_tnved += [str(z) for z in (v if isinstance(v,list) else [v]) if z]
        assignment=next(r for r in rows if r['Артикул продавца']==offer)
        if assignment.get('Применимость')!='Подтверждено статусом покрытия' or assignment.get('Бренд подтвержденный')!='Gauss':
            raise RuntimeError('Source assignment no longer confirms exact scope: '+offer)
        result_targets.append({'offer_id':offer,'product_id':pid,'sku':sku,'name':p.get('name'),'brand':brand,'tnved':tnved,'archived':p.get('is_archived'),'source_match':assignment.get('Основание сопоставления'),'official_product_url':assignment.get('URL карточки/основания'),'wb':None if not card else {'nmID':card.get('nmID'),'brand':card.get('brand'),'title':card.get('title'),'tnved':wb_tnved,'exact_document_present':any(norm_number(d.get('number',''))==norm_number(NUMBER) for d in ((card.get('documents') or {}).get('items') or []))}})
    data={'checked_at_utc':now(),'read_only':True,'document':{'number':NUMBER,'type':TYPE,'fsa_record_id':FSA_ID,'fsa_status_checked_in_UI':'Действует','issue_date':'2022-05-11','expiry_date':'2027-04-28','fsa_url':f'https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/common','source_file':str(FILE.relative_to(ROOT)),'sha256':digest(FILE),'source_url':'https://gauss.ru/dfa69bbb18d9/f5244bf2-7d7e-11f0-9c33-4db153f82175/f5244bf2-7d7e-11f0-9c33-4db153f82175.pdf','declared_tnved':['9405110033','9405110013']},'source_assignment_rows':len(rows),'target_count':len(offers),'ozon_exact_records':[{'certificate_id':x.get('certificate_id'),'status_code':x.get('status_code'),'issue_date':x.get('issue_date'),'expire_date':x.get('expire_date'),'products_count':x.get('products_count')} for x in exact_records],'targets':result_targets,'wb_tnved_match_all':all(set((v.split(' - ')[0].strip() for v in t['wb']['tnved'])) & {'9405110033','9405110013'} for t in result_targets if t['wb']) if any(t['wb'] for t in result_targets) else None,'wb_missing_exact_cards':[t['offer_id'] for t in result_targets if not t['wb']]}
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'preflight':str(OUT),'checked_at_utc':data['checked_at_utc'],'target_count':len(offers),'existing_records':data['ozon_exact_records'],'wb_missing_exact_cards':data['wb_missing_exact_cards'],'wb_tnved_match_all':data['wb_tnved_match_all'],'targets':[{'offer_id':t['offer_id'],'product_id':t['product_id'],'sku':t['sku'],'brand':t['brand'],'tnved':t['tnved'],'wb':None if not t['wb'] else {'nmID':t['wb']['nmID'],'brand':t['wb']['brand'],'tnved':t['wb']['tnved'],'present':t['wb']['exact_document_present']}} for t in result_targets]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
