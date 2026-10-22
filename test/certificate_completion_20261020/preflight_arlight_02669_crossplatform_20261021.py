from __future__ import annotations
import collections, csv, datetime as dt, hashlib, json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / 'test/certificate_api_pilot_20261012'
sys.path.insert(0, str(API))
from api_client import Client, now, digest
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents, doc_key
from run_all_found_certificates_20261014 import deduplicate_equivalent_wb_rows
PDF = ROOT / 'output_to_user/certificates/group_1/documents/arlight/B40746683BE4E24A9A25CD278FD53917.pdf'
ASSIGNMENTS = HERE / 'all_confirmed_source_assignments_live_20261021.csv'
OUT = HERE / 'arlight_02669_crossplatform_preflight_live_20261021.json'
NUMBER = 'ЕАЭС RU С-HK.АБ53.В.02669/21'
ISSUE, EXPIRY, TNVED = '2021-12-08', '2026-12-07', '9405109803'
FSA_URL = 'https://pub.fsa.gov.ru/rss/certificate/view/3008100'
SERIES = ('ART', 'SNAP', 'CLIP', 'MAG', 'FLEX', 'LGD')
EXPECTED_SHA = '9b9c776c47d6e805fc9a18b4717a64407b348289c7b0dcf4f8c42de5e90b275f'

def attr_values(row, attr_id):
    attrs = {str(a.get('id')): a for a in row.get('attributes') or []}
    return [str(v.get('value') or '').strip() for v in (attrs.get(str(attr_id)) or {}).get('values') or [] if str(v.get('value') or '').strip()]

def series_hits(value):
    text = str(value or '').upper()
    return sorted(s for s in SERIES if re.search(r'(?<![A-Z0-9])' + re.escape(s) + r'(?![A-Z0-9])', text))

def tnved_wb(card):
    values=[]
    for char in card.get('characteristics') or []:
        name=''.join(str(char.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' not in name and 'тнвед' not in name: continue
        raw=char.get('value'); raw=raw if isinstance(raw,list) else [raw]
        values.extend(str(v or '').split(' - ',1)[0].strip() for v in raw if v)
    return sorted(set(values))

def list_certificates(client):
    rows=[]; page=1; pages=None; seen=set()
    while pages is None or page<=pages:
        result=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
        batch=result.get('certificates')
        if not isinstance(batch,list): raise RuntimeError('ozon_certificate_list_incomplete')
        for c in batch:
            cid=str(c.get('certificate_id') or '')
            if not cid or cid in seen: raise RuntimeError('ozon_certificate_duplicate_or_missing_id')
            seen.add(cid)
        rows.extend(batch); pages=int(result.get('page_count') or page)
        if not batch: break
        page+=1
    return rows

def save(obj):
    tmp=OUT.with_suffix('.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)); tmp.replace(OUT)

def main():
    if OUT.exists(): raise RuntimeError('preflight_output_exists')
    if digest(PDF)!=EXPECTED_SHA: raise RuntimeError('source_pdf_hash_changed')
    with ASSIGNMENTS.open(encoding='utf-8-sig',newline='') as stream:
        rows=[r for r in csv.DictReader(stream) if PDF.name in str(r.get('source_files') or '')]
    offers=sorted({str(r.get('offer_id') or '') for r in rows})
    if len(rows)!=578 or len(offers)!=578 or '' in offers: raise RuntimeError(f'unexpected_assignments:{len(rows)}:{len(offers)}')
    if any(r.get('brand')!='Arlight' or r.get('type')!='certificate_of_conformity' for r in rows): raise RuntimeError('assignment_brand_or_type_conflict')
    products={}
    for r in rows:
        offer=str(r['offer_id']); entry={'offer_id':offer,'product_id':str(r['ozon_product_id']),'sku':str(r['ozon_sku']),'wb_nmID':str(r['wb_nmID'])}
        if offer in products and products[offer]!=entry: raise RuntimeError('conflicting_assignment_identity:'+offer)
        products[offer]=entry
    client=Client()
    # Refresh each assigned Ozon product and regulatory attributes.
    ids=sorted({x['product_id'] for x in products.values()})
    details={}
    for start in range(0,len(ids),100):
        batch=ids[start:start+100]
        result=client.call('ozon','/v3/product/info/list',{'product_id':[int(x) for x in batch]}).get('items')
        if not isinstance(result,list): raise RuntimeError('ozon_product_details_missing')
        for item in result:
            pid=str(item.get('product_id') or item.get('id') or '')
            if pid not in batch or pid in details: raise RuntimeError('ozon_product_identity_mismatch')
            details[pid]=item
    if set(details)!=set(ids): raise RuntimeError('ozon_product_details_incomplete')
    attrs={}
    for start in range(0,len(offers),100):
        batch=offers[start:start+100]
        result=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result')
        if not isinstance(result,list): raise RuntimeError('ozon_attributes_missing')
        for item in result:
            offer=str(item.get('offer_id') or '')
            if offer not in batch or offer in attrs: raise RuntimeError('ozon_attribute_identity_mismatch')
            attrs[offer]=item
    if set(attrs)!=set(offers): raise RuntimeError('ozon_attributes_incomplete')
    ozon=[]
    for offer in offers:
        target=products[offer]; detail=details[target['product_id']]; attr=attrs[offer]
        brands=attr_values(attr,85); codes=sorted({x.split(' - ',1)[0].strip() for x in attr_values(attr,22232) if x.strip()})
        name=str(detail.get('name') or detail.get('name_ru') or '')
        identity=(str(detail.get('product_id') or detail.get('id') or '')==target['product_id'] and str(detail.get('offer_id') or '')==offer and str(detail.get('sku') or '')==target['sku'] and str(attr.get('offer_id') or '')==offer)
        hits=series_hits(name)
        scope=identity and detail.get('is_archived') is False and brands==['Arlight'] and codes==[TNVED] and bool(hits)
        ozon.append({**target,'identity_matches':identity,'archived':detail.get('is_archived'),'brand_values':brands,'tnved_codes':codes,'series_hits':hits,'product_name':name,'in_scope':scope})
    certs=list_certificates(client)
    matches=[c for c in certs if norm_number(c.get('certificate_number'))==norm_number(NUMBER)]
    # A complete WB catalogue read is needed so duplicate seller cards remain visible.
    cards=[]; cursor={'limit':100}; seen=set(); reported_total=None
    while True:
        data=client.call('wb','/content/v2/get/cards/list',{'settings':{'sort':{'ascending':True},'cursor':cursor,'filter':{'withPhoto':-1}}})
        batch=data.get('cards')
        if data.get('error') or not isinstance(batch,list): raise RuntimeError('wb_catalog_invalid')
        cards.extend(batch)
        returned=data.get('cursor') or {}
        total=returned.get('total')
        if reported_total is None and isinstance(total,int): reported_total=total
        if len(batch)<100: break
        signature=(returned.get('updatedAt'),returned.get('nmID'))
        if None in signature or signature in seen: raise RuntimeError('wb_catalog_cursor_incomplete')
        seen.add(signature); cursor={'limit':100,'updatedAt':signature[0],'nmID':signature[1]}
        if len(cards)%5000<100: print(json.dumps({'phase':'live_wb_catalog_read','cards':len(cards),'total':reported_total}),flush=True)
    raw=len(cards); cards,dups=deduplicate_equivalent_wb_rows(cards)
    if reported_total is not None and raw<reported_total: raise RuntimeError(f'wb_catalog_truncated:{raw}:{reported_total}')
    by_offer=collections.defaultdict(list)
    for card in cards:
        offer=str(card.get('vendorCode') or '')
        if offer in products: by_offer[offer].append(card)
    oz_by_offer={r['offer_id']:r for r in ozon}
    wb=[]
    target_doc={'type':1,'number':NUMBER,'startDate':ISSUE+'T00:00:00Z','endDate':EXPIRY+'T00:00:00Z','isEndless':False}
    for offer in offers:
        found=by_offer.get(offer,[]); oz=oz_by_offer[offer]
        if len(found)!=1:
            wb.append({'offer_id':offer,'assigned_nmID':products[offer]['wb_nmID'],'card_count':len(found),'eligible_for_add':False,'reason':'wb_card_missing_or_ambiguous'})
            continue
        card=found[0]; codes=tnved_wb(card); wb_series=series_hits(card.get('title')); existing=copy_documents(card)
        matches_doc=[d for d in existing if norm_number(d.get('number'))==norm_number(NUMBER)]
        exact=[d for d in matches_doc if doc_key(d)==(1,norm_number(NUMBER)) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY and d.get('isEndless') is False]
        identity=str(card.get('nmID') or '')==products[offer]['wb_nmID'] and str(card.get('vendorCode') or '')==offer
        brand=str(card.get('brand') or '').strip().casefold()=='arlight'
        same_series=bool(set(oz['series_hits']) & set(wb_series))
        code_ok=(not codes or codes==[TNVED])
        eligible=oz['in_scope'] and identity and brand and same_series and code_ok and not matches_doc
        if matches_doc and exact: reason='already_exact_document_present'
        elif matches_doc: reason='existing_document_conflict'
        elif not oz['in_scope']: reason='ozon_product_out_of_scope_or_unconfirmed'
        elif not identity: reason='wb_assigned_identity_changed'
        elif not brand: reason='wb_brand_mismatch'
        elif not same_series: reason='wb_model_series_not_confirmed'
        elif not code_ok: reason='wb_tnved_conflict'
        else: reason='eligible_for_add'
        wb.append({'offer_id':offer,'assigned_nmID':products[offer]['wb_nmID'],'nmID':str(card.get('nmID') or ''),'brand':card.get('brand'),'title':card.get('title'),'tnved_codes':codes,'ozon_series':oz['series_hits'],'wb_series':wb_series,'existing_matching_number_count':len(matches_doc),'exact_document_count':len(exact),'eligible_for_add':eligible,'reason':reason,'current_doc_count':len(existing),'prior_documents':[{'type':d.get('type'),'number':d.get('number'),'startDate':d.get('startDate'),'endDate':d.get('endDate'),'isEndless':d.get('isEndless')} for d in existing]})
    result={'checked_at':now(),'read_only':True,'certificate_number':NUMBER,'fsa_record_id':3008100,'fsa_registry_url':FSA_URL,'issue_date':ISSUE,'expire_date':EXPIRY,'fsa_status':'Действует','fsa_product_scope':'Arlight general-purpose lights: surface-mounted ART/SNAP/CLIP, recessed ART, stationary MAG/FLEX, pendant CLIP/MAG/LGD','fsa_tnved_scope':[TNVED],'production_type':'serial_production','production_lot_cutoff_found_in_certificate':False,'source_pdf':str(PDF),'source_pdf_sha256':digest(PDF),'assignment_rows':len(rows),'unique_source_offers':len(offers),'ozon_products_checked':len(ozon),'ozon_scope_counts':dict(collections.Counter('in_scope' if r['in_scope'] else 'out_of_scope_or_unconfirmed' for r in ozon)),'ozon_certificate_records_checked':len(certs),'ozon_normalized_record_matches':matches,'ozon_targets':ozon,'wb_catalog_cards_read_raw':raw,'wb_catalog_cards_unique_equivalent':len(cards),'wb_equivalent_duplicate_rows_removed':dups,'wb_total_reported':reported_total,'wb_source_offers_checked':len(wb),'wb_reasons':dict(collections.Counter(r['reason'] for r in wb)),'wb_cards':wb,'mutations_performed':False,'local_file_cleanup_allowed':False}
    save(result)
    print(json.dumps({k:result[k] for k in ('checked_at','assignment_rows','unique_source_offers','ozon_scope_counts','ozon_normalized_record_matches','wb_catalog_cards_read_raw','wb_total_reported','wb_reasons','mutations_performed','local_file_cleanup_allowed')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
