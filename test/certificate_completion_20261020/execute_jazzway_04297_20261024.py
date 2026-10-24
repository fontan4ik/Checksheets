from __future__ import annotations
import base64, collections, datetime as dt, hashlib, json, pathlib, sys, time

HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now  # noqa:E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa:E402
from run_all_found_certificates_20261014 import merge_wb  # noqa:E402

NUMBER='ЕАЭС RU С-HK.АЖ56.В.04297/24'; TYPE='certificate_of_conformity'
ISSUE='2024-04-16'; EXPIRY='2029-04-15'; FSA_ID='3420033'
FILE=ROOT/'output_to_user/certificates/group_2/JAZZWAY/documents/svetilniki-ppl-psp-pled-vstraivaemye-ss-tr-ts-004-020-15.04.2029_6a82b17ac896.pdf'
SHA='6a82b17ac896ce378096a92fb75647c11da3fa236e4ae5248a2c3f39c7bb7445'
PREFLIGHT=HERE/'jazzway_04297_crossplatform_preflight_20261024.json'
STATE=HERE/'jazzway_04297_execution_20261024.json'; JOURNAL=HERE/'jazzway_04297_mutation_journal_20261024.jsonl'
BEFORE=HERE/'jazzway_04297_wb_before_20261024.json'; READBACK=HERE/'jazzway_04297_final_crossplatform_readback_20261024.json'

def save(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
def log(obj):
    with JOURNAL.open('a',encoding='utf-8') as f:f.write(json.dumps({'at_utc':now(),**obj},ensure_ascii=False)+'\n');f.flush()
def values(row,aid):
    a={str(x.get('id')):x for x in row.get('attributes') or []}
    return [str(x.get('value') or '').strip() for x in ((a.get(str(aid)) or {}).get('values') or []) if str(x.get('value') or '').strip()]
def codes(vals):return sorted({str(x).split(' - ',1)[0].strip() for x in vals if str(x).strip()})
def wb_codes(card):
    out=[]
    for x in card.get('characteristics') or []:
        name=''.join(str(x.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' in name or 'тнвед' in name:
            v=x.get('value');out.extend(v if isinstance(v,list) else [v])
    return codes([str(x) for x in out if x])
def list_records(c):
    out=[]
    for page in range(1,101):
        r=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}; b=r.get('certificates')
        if not isinstance(b,list):raise RuntimeError('ozon_certificate_list_incomplete')
        out.extend(b)
        if not b or page>=int(r.get('page_count') or 0):return out
    raise RuntimeError('ozon_certificate_list_limit')
def exact_records(c):return [x for x in list_records(c) if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
def fresh_ozon(c,offers):
    ps=c.call('ozon','/v3/product/info/list',{'offer_id':offers}).get('items') or []
    aa=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':len(offers)}).get('result') or []
    if len(ps)!=len(offers) or len(aa)!=len(offers):raise RuntimeError('fresh_ozon_count_mismatch')
    p={str(x.get('offer_id') or ''):x for x in ps};a={str(x.get('offer_id') or ''):x for x in aa}
    if set(p)!=set(offers) or set(a)!=set(offers):raise RuntimeError('fresh_ozon_offer_set_mismatch')
    return p,a
def main():
    if any(x.exists() for x in (STATE,JOURNAL,BEFORE,READBACK)):raise RuntimeError('execution_artifact_exists_reconcile_before_retry')
    if not FILE.is_file() or hashlib.sha256(FILE.read_bytes()).hexdigest()!=SHA:raise RuntimeError('source_pdf_hash_mismatch')
    pre=json.loads(PREFLIGHT.read_text(encoding='utf-8'))
    if (pre.get('read_only') is not True or pre.get('document',{}).get('number')!=NUMBER
        or pre.get('document',{}).get('fsa_record_id')!=FSA_ID or pre.get('document',{}).get('fsa_status')!='Действует'
        or pre.get('document',{}).get('issue_date')!=ISSUE or pre.get('document',{}).get('expire_date')!=EXPIRY
        or pre.get('document',{}).get('source_sha256')!=SHA or pre.get('assignment_count')!=39
        or pre.get('ozon_safe_count')!=39 or pre.get('wb_safe_count')!=39 or pre.get('ozon_exact_records')!=[]
        or pre.get('wb_already_exact_count')!=0):raise RuntimeError('preflight_not_clean_39_target_batch')
    if dt.date.today()>dt.date.fromisoformat(EXPIRY):raise RuntimeError('document_expired')
    c=Client();offers=sorted(x['offer_id'] for x in pre['ozon_targets'])
    if len(offers)!=39 or len(set(offers))!=39 or exact_records(c):raise RuntimeError('target_or_record_changed_after_preflight')
    products,attrs=fresh_ozon(c,offers);oz_targets=[];wb_payloads=[];wb_before=[]
    by_target={x['offer_id']:x for x in pre['ozon_targets']}
    by_wb={x['offer_id']:x for x in pre['wb_targets']}
    for offer in offers:
        p,a=products[offer],attrs[offer];brand=values(a,'85');tnv=codes(values(a,'22232'))
        row={'offer_id':offer,'product_id':str(p.get('product_id') or p.get('id') or ''),'sku':str(p.get('sku') or ''),'brand':brand,'tnved':tnv,'is_archived':p.get('is_archived')}
        exp=by_target[offer]
        if (row['product_id']!=exp['product_id'] or row['sku']!=exp['sku'] or row['is_archived'] is not False
            or brand!=['Jazzway'] or tnv!=['9405110033']):raise RuntimeError('fresh_ozon_identity_or_scope_changed:'+offer)
        oz_targets.append(row)
        cards=[x for x in c.wb_cards(offer) if str(x.get('vendorCode') or '')==offer]
        if len(cards)!=1:raise RuntimeError('fresh_wb_exact_card_count_changed:'+offer)
        card=cards[0]; expected=by_wb[offer]
        if (str(card.get('nmID') or '')!=str(expected.get('nmID') or '') or str(card.get('brand') or '').casefold() not in {'jazzway','jazz way'}
            or wb_codes(card)!=['9405110033']):raise RuntimeError('fresh_wb_identity_or_scope_changed:'+offer)
        same=[x for x in ((card.get('documents') or {}).get('items') or []) if norm_number(x.get('number'))==norm_number(NUMBER)]
        if same:raise RuntimeError('wb_same_number_appeared_after_preflight:'+offer)
        desired={'type':1,'number':NUMBER,'startDate':ISSUE+'T00:00:00Z','endDate':EXPIRY+'T00:00:00Z','isEndless':False}
        payload=merge_wb(card,[desired])
        if payload is None:raise RuntimeError('wb_merge_unexpected_noop:'+offer)
        wb_before.append({'offer_id':offer,'nmID':str(card.get('nmID')),'card':card})
        wb_payloads.append(payload)
    skus=sorted({x['sku'] for x in oz_targets})
    if len(oz_targets)!=39 or len(wb_payloads)!=39 or len(skus)!=39:raise RuntimeError('unique_complete_target_set_failed')
    expiry=dt.date.fromisoformat(EXPIRY)
    oz_payload={'params':{'name':'Сертификат соответствия № '+NUMBER,'certificate_type':'CERTIFICATE_OF_CONFORMITY',
        'certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,'issue_date':ISSUE+'T00:00:00Z',
        'expired_date':{'date':{'day':expiry.day,'month':expiry.month,'year':expiry.year}},'skus':skus,'product_type':'UNKNOWN',
        'files':[{'file_content':base64.b64encode(FILE.read_bytes()).decode('ascii'),'name':FILE.name}],
        'link_to_registry':f'https://pub.fsa.gov.ru/rss/certificate/view/{FSA_ID}/baseInfo'}}
    oz_bytes=json.dumps(oz_payload,ensure_ascii=False,separators=(',',':')).encode()
    wb_bytes=json.dumps(wb_payloads,ensure_ascii=False,separators=(',',':')).encode()
    if len(oz_bytes)>15_000_000 or len(wb_bytes)>9_500_000:raise RuntimeError('payload_size_over_verified_limit')
    save(BEFORE,{'checked_at_utc':now(),'read_only':True,'cards':wb_before})
    state={'started_at_utc':now(),'number':NUMBER,'type':TYPE,'fsa_record_id':FSA_ID,'fsa_url':f'https://pub.fsa.gov.ru/rss/certificate/view/{FSA_ID}/baseInfo',
        'issue_date':ISSUE,'expire_date':EXPIRY,'sample_date_condition':'Production from tested sample date 12.2023',
        'source_file':str(FILE.relative_to(ROOT)),'source_sha256':SHA,'target_count':39,'wb_review_left_pending':True,'local_file_deleted':False,
        'ozon':{'state':'create_pending','request_sha256':hashlib.sha256(oz_bytes).hexdigest(),'request_bytes':len(oz_bytes),'expected_pairs':oz_targets},
        'wb':{'state':'update_pending','request_sha256':hashlib.sha256(wb_bytes).hexdigest(),'request_bytes':len(wb_bytes),
              'expected_cards':[{'offer_id':x['offer_id'],'nmID':x['nmID']} for x in wb_before]}}
    save(STATE,state)
    log({'phase':'ozon_create_prepared','request_sha256':state['ozon']['request_sha256'],'request_bytes':len(oz_bytes),'target_count':39})
    try:oz_resp=c.call('ozon','/v2/product/certificate/create',oz_payload,mutation=True)
    except Exception as e:
        state['ozon'].update({'state':'create_outcome_uncertain_reconcile_before_retry','error_type':type(e).__name__});save(STATE,state)
        log({'phase':'ozon_create_uncertain','error_type':type(e).__name__});raise
    state['ozon'].update({'state':'create_response_received','response':oz_resp,'certificate_id':str(oz_resp.get('certificate_id') or ''),'create_status':oz_resp.get('status')});save(STATE,state)
    log({'phase':'ozon_create_response','response':oz_resp})
    log({'phase':'wb_update_prepared','request_sha256':state['wb']['request_sha256'],'request_bytes':len(wb_bytes),'target_count':39})
    try:wb_resp=c.call('wb','/content/v2/cards/update',wb_payloads,mutation=True)
    except Exception as e:
        state['wb'].update({'state':'update_outcome_uncertain_reconcile_before_retry','error_type':type(e).__name__});save(STATE,state)
        log({'phase':'wb_update_uncertain','error_type':type(e).__name__});raise
    state['wb'].update({'state':'update_response_received','response':wb_resp,'accepted':wb_resp.get('error') is False});save(STATE,state)
    log({'phase':'wb_update_response','response':wb_resp})
    if wb_resp.get('error') is not False:raise RuntimeError('wb_update_not_accepted_reconcile_before_retry')
    records=[]
    for i in range(6):
        records=exact_records(c)
        if records:break
        if i<5:time.sleep(3)
    if len(records)!=1:raise RuntimeError('ozon_postwrite_record_missing_or_duplicate')
    rec=records[0];cid=int(rec['certificate_id']);bindings=c.ozon_bindings(cid)
    expected={(x['product_id'],x['sku']):x['offer_id'] for x in oz_targets}
    actual={(str(x.get('product_id') or ''),str(x.get('sku') or '')):x for x in bindings}
    missing=[offer for pair,offer in expected.items() if pair not in actual]
    if rec.get('status_code')=='approved' and missing:
        bind_skus=sorted({next(x['sku'] for x in oz_targets if x['offer_id']==o) for o in missing})
        bp={'certificate_id':cid,'skus':bind_skus};log({'phase':'ozon_bind_prepared','certificate_id':cid,'skus':bind_skus})
        try:state['ozon']['bind_response']=c.call('ozon','/v1/product/certificate/bind',bp,mutation=True)
        except Exception as e:
            state['ozon'].update({'state':'bind_outcome_uncertain_reconcile_before_retry','bind_error_type':type(e).__name__});save(STATE,state);raise
        bindings=c.ozon_bindings(cid);actual={(str(x.get('product_id') or ''),str(x.get('sku') or '')):x for x in bindings}
    oz_rb=[{'offer_id':x['offer_id'],'product_id':x['product_id'],'sku':x['sku'],'visible':(x['product_id'],x['sku']) in actual,
            'binding_status':actual.get((x['product_id'],x['sku']),{}).get('product_status_code')} for x in oz_targets]
    state['ozon'].update({'certificate_id':str(cid),'record_status':rec.get('status_code'),'readback_count':sum(x['visible'] for x in oz_rb),
        'binding_status_counts':dict(collections.Counter(x['binding_status'] or 'missing' for x in oz_rb)),'readback':oz_rb})
    state['ozon']['state']='all_39_pairs_visible' if all(x['visible'] for x in oz_rb) else 'readback_incomplete';save(STATE,state)
    wb_rb=[]
    for i,expected_card in enumerate(wb_before,1):
        cards=[x for x in c.wb_cards(expected_card['offer_id']) if str(x.get('vendorCode') or '')==expected_card['offer_id']]
        if len(cards)!=1 or str(cards[0].get('nmID') or '')!=expected_card['nmID']:
            wb_rb.append({'offer_id':expected_card['offer_id'],'nmID':expected_card['nmID'],'exact_card':False,'exact_document_count':0});continue
        docs=[x for x in ((cards[0].get('documents') or {}).get('items') or []) if norm_number(x.get('number'))==norm_number(NUMBER)]
        exact=[x for x in docs if str(x.get('type'))=='1' and str(x.get('startDate') or '')[:10]==ISSUE and str(x.get('endDate') or '')[:10]==EXPIRY and x.get('isEndless') is False]
        verdicts=[x.get('verdict') or {} for x in exact]
        valid=any(v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' for v in verdicts)
        pending=bool(exact) and not valid and all(v.get('status') in (None,1) and v.get('reason') in (None,'','valid') for v in verdicts)
        wb_rb.append({'offer_id':expected_card['offer_id'],'nmID':expected_card['nmID'],'exact_card':True,'exact_document_count':len(exact),'valid':valid,'pending':pending,'verdicts':verdicts})
        if i%20==0:print(f'read_wb_back={i}/39',flush=True)
    exact_count=sum(x.get('exact_document_count')==1 for x in wb_rb); valid_count=sum(x.get('valid') is True for x in wb_rb); pending_count=sum(x.get('pending') is True for x in wb_rb)
    state['wb'].update({'readback_count':len(wb_rb),'exact_metadata_count':exact_count,'valid_count':valid_count,'pending_count':pending_count,
        'readback':wb_rb,'state':'all_metadata_visible_pending_review' if exact_count==39 else 'readback_incomplete'})
    state['finished_at_utc']=now();state['local_file_deleted']=False;save(STATE,state)
    save(READBACK,{'checked_at_utc':now(),'read_only':True,'number':NUMBER,'ozon_record':{k:rec.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date')},
        'ozon_pairs':oz_rb,'wb_cards':wb_rb,'ozon_visible_pairs':sum(x['visible'] for x in oz_rb),'wb_exact_metadata_cards':exact_count,'wb_valid':valid_count,'wb_pending':pending_count,'local_file_deleted':False})
    print(json.dumps({'state_file':str(STATE),'readback_file':str(READBACK),'ozon':{'certificate_id':str(cid),'record_status':rec.get('status_code'),'visible_pairs':sum(x['visible'] for x in oz_rb),'targets':39,'binding_status_counts':dict(collections.Counter(x['binding_status'] or 'missing' for x in oz_rb))},
        'wb':{'exact_metadata':exact_count,'valid':valid_count,'pending':pending_count,'targets':39},'local_file_deleted':False},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
