from __future__ import annotations
import base64,datetime as dt,hashlib,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number
NUMBER='ЕАЭС N RU Д-CN.РА03.В.38441/22';TYPE='declaration'
FILE=ROOT/'output_to_user/certificates/group_1/documents/gauss/022350fc738de01663d0f848.pdf'
SHA='c76f8b5865411c71fb02db6812f4ff882f8751b8336242e7f1abbf9f9d00bb4a'
PREFLIGHT=HERE/'gauss_38441_crossplatform_preflight_20261024.json'
STATE=HERE/'gauss_38441_execution_20261024.json'
FSA='https://pub.fsa.gov.ru/rds/declaration/view/16706705/common'

def save(s):
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(STATE)
def list_docs(c):
    out=[]
    for page in range(1,101):
        r=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
        batch=r.get('certificates')
        if not isinstance(batch,list):raise RuntimeError('Ozon certificate listing incomplete')
        out.extend(batch)
        if len(batch)<100:return out
    raise RuntimeError('Ozon certificate page limit reached')
def exact_wb(c,offer):
    r=c.call('wb','/content/v2/get/cards/list',{'settings':{'sort':{'ascending':True},'cursor':{'limit':100},'filter':{'withPhoto':-1,'textSearch':offer}}})
    if r.get('error') or not isinstance(r.get('cards'),list):raise RuntimeError('WB card read incomplete '+offer)
    return [x for x in r['cards'] if x.get('vendorCode')==offer]
if STATE.exists():raise RuntimeError('Existing state prevents duplicate writes; reconcile it instead')
pre=json.loads(PREFLIGHT.read_text(encoding='utf-8'))
doc=pre.get('document') or {};targets=pre.get('targets') or []
if not pre.get('read_only') or pre.get('target_count')!=12 or len(targets)!=12:raise RuntimeError('Preflight not complete for all 12 source models')
if doc.get('number')!=NUMBER or doc.get('fsa_record_id')!='16706705' or doc.get('fsa_status_checked_in_UI')!='Действует':raise RuntimeError('FSA preflight mismatch')
if doc.get('issue_date')!='2022-05-11' or doc.get('expiry_date')!='2027-04-28':raise RuntimeError('FSA dates mismatch')
if not FILE.is_file() or digest(FILE).lower()!=SHA or doc.get('sha256')!=SHA:raise RuntimeError('Source PDF missing or SHA changed')
if dt.date.today()>dt.date.fromisoformat('2027-04-28'):raise RuntimeError('Source declaration expired')
offers=[x['offer_id'] for x in targets]
client=Client()
products=client.call('ozon','/v3/product/info/list',{'offer_id':offers}).get('items') or []
attrs=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':len(offers)}).get('result') or []
p_by={str(x.get('offer_id')):x for x in products};a_by={str(x.get('offer_id')):x for x in attrs}
if set(p_by)!=set(offers) or set(a_by)!=set(offers):raise RuntimeError('Fresh Ozon target set mismatch')
def av(a,aid):
    aa={str(x.get('id')):x for x in (a.get('attributes') or [])}
    return [str(v.get('value') or '').strip() for v in (aa.get(str(aid)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
expected={(x['offer_id'],str(x['product_id']),str(x['sku'])) for x in targets}
actual=set()
for offer,p in p_by.items():
    a=a_by[offer];pid=str(p.get('product_id') or p.get('id') or '');sku=str(p.get('sku') or '')
    if p.get('is_archived') is not False or not pid or not sku:raise RuntimeError('Ozon product is archived or missing identity: '+offer)
    if not any(v.casefold()=='gauss' for v in av(a,85)):raise RuntimeError('Ozon brand mismatch: '+offer)
    target=next(x for x in targets if x['offer_id']==offer)
    if pid!=str(target['product_id']) or sku!=str(target['sku']):raise RuntimeError('Ozon product identity changed: '+offer)
    actual.add((offer,pid,sku))
if actual!=expected:raise RuntimeError('Fresh Ozon target identity set changed')
# WB is read-only: exact cards conflict with FSA TN VED or are absent; never overwrite product codes.
wb_live=[]
for target in targets:
    offer=target['offer_id'];cards=exact_wb(client,offer)
    if len(cards)>1:raise RuntimeError('WB duplicate exact cards; blocked '+offer)
    card=cards[0] if cards else None
    tnved=[]
    if card:
        for ch in card.get('characteristics') or []:
            if str(ch.get('id')) in ('15000001','22232') or str(ch.get('name') or '').casefold()=='тнвэд':
                v=ch.get('value');tnved += [str(z).split(' - ')[0].strip() for z in (v if isinstance(v,list) else [v]) if z]
    wb_live.append({'offer_id':offer,'nmID':(card or {}).get('nmID'),'brand':(card or {}).get('brand'),'tnved':tnved,'eligible':bool(card and ({'9405110033','9405110013'} & set(tnved)))})
state={'started_at_utc':now(),'number':NUMBER,'type':TYPE,'fsa_record_id':'16706705','fsa_url':FSA,'validity':{'from':'2022-05-11','through':'2027-04-28'},'source_file':str(FILE.relative_to(ROOT)),'source_sha256':digest(FILE),'targets':targets,'ozon':{'state':'fresh_preflight_complete','expected_pairs':[{'offer_id':o,'product_id':p,'sku':s} for o,p,s in sorted(expected)],'brands_verified':True,'tnved_conflict':{'declaration':['9405110033','9405110013'],'ozon_cards':['9405190039'],'handling':'No marketplace classification was changed; exact models are listed in the active declaration. Ozon status must be verified after the API operation.'}},'wb':{'read_only':True,'exact_cards':wb_live,'missing_exact_cards':[x['offer_id'] for x in wb_live if x['nmID'] is None],'tnved_mismatch_cards':[x['offer_id'] for x in wb_live if x['nmID'] is not None and not x['eligible']],'write_sent':False},'local_file_deleted':False}
save(state)
records=[x for x in list_docs(client) if x.get('type_code')==TYPE and norm_number(x.get('certificate_number',''))==norm_number(NUMBER)]
if len(records)>1:
    state['ozon'].update({'state':'blocked_multiple_exact_records','existing_ids':[x.get('certificate_id') for x in records]});save(state);raise RuntimeError('Duplicate Ozon document records; no mutation sent')
if records:
    rec=records[0];cid=rec.get('certificate_id');links=client.ozon_bindings(int(cid))
    state['ozon'].update({'state':'existing_record_reconciled','certificate_id':cid,'record_status':rec.get('status_code'),'existing_bindings':links})
    pairs={(str(x.get('product_id')),str(x.get('sku'))):x for x in links}
    absent=[x for x in targets if (str(x['product_id']),str(x['sku'])) not in pairs]
    if rec.get('status_code')!='approved':state['ozon']['state']='existing_record_pending_or_declined_no_rebind'
    elif absent:
        state['ozon'].update({'state':'bind_sent','bind_started_at_utc':now(),'bind_target_offers':[x['offer_id'] for x in absent]});save(state)
        response=client.call('ozon','/v1/product/certificate/bind',{'certificate_id':int(cid),'skus':sorted({str(x['sku']) for x in absent})},mutation=True)
        state['ozon']['bind_response']=response
    else:state['ozon']['state']='already_bound'
else:
    end=dt.date.fromisoformat('2027-04-28')
    params={'name':'Декларация о соответствии № '+NUMBER,'certificate_type':'DECLARATION','certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,'issue_date':'2022-05-11T00:00:00Z','expired_date':{'date':{'day':end.day,'month':end.month,'year':end.year}},'skus':sorted({str(x['sku']) for x in targets}),'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(FILE.read_bytes()).decode('ascii'),'name':FILE.name}],'link_to_registry':FSA}
    request=json.dumps({'params':params},ensure_ascii=False,separators=(',',':')).encode()
    if len(request)>15_000_000:raise RuntimeError('Ozon request exceeds verified safe ceiling')
    state['ozon'].update({'state':'create_sent','mutation_started_at_utc':now(),'request_sha256':hashlib.sha256(request).hexdigest(),'request_bytes':len(request)});save(state)
    # One non-retried creation call. On an uncertain result, reconcile live state before any retry.
    try:response=client.call('ozon','/v2/product/certificate/create',{'params':params},mutation=True)
    except Exception as e:
        state['ozon'].update({'state':'create_uncertain_reconcile_before_retry','error_type':type(e).__name__,'finished_at_utc':now()});save(state);raise
    state['ozon']['create_response']=response;state['ozon']['create_status']=response.get('status');state['ozon']['certificate_id']=response.get('certificate_id');state['ozon']['invalid_params']=[x for x in (response.get('params') or []) if x.get('state')=='INVALID'];state['ozon']['mutation_finished_at_utc']=now();save(state)
# Exact post-write list + bindings; only attach missing pairs if live record is globally approved.
records=[x for x in list_docs(client) if x.get('type_code')==TYPE and norm_number(x.get('certificate_number',''))==norm_number(NUMBER)]
if len(records)!=1:
    state['ozon'].update({'state':'postwrite_record_missing_or_duplicate','postwrite_record_count':len(records)});save(state)
else:
    rec=records[0];cid=int(rec['certificate_id']);links=client.ozon_bindings(cid)
    pairs={(str(x.get('product_id')),str(x.get('sku'))):x for x in links}
    absent=[x for x in targets if (str(x['product_id']),str(x['sku'])) not in pairs]
    if rec.get('status_code')=='approved' and absent:
        state['ozon'].update({'state':'bind_sent_after_approved_create','bind_started_at_utc':now(),'bind_target_offers':[x['offer_id'] for x in absent]});save(state)
        resp=client.call('ozon','/v1/product/certificate/bind',{'certificate_id':cid,'skus':sorted({str(x['sku']) for x in absent})},mutation=True)
        state['ozon']['bind_response']=resp
        links=client.ozon_bindings(cid);pairs={(str(x.get('product_id')),str(x.get('sku'))):x for x in links}
    visible=[{'offer_id':o,'product_id':p,'sku':s,'binding_status':pairs.get((p,s),{}).get('product_status_code')} for o,p,s in sorted(expected) if (p,s) in pairs]
    all_present=len(visible)==len(expected)
    all_approved=all(x['binding_status']=='approved' for x in visible)
    state['ozon'].update({'certificate_id':str(cid),'record_status':rec.get('status_code'),'issue_date':rec.get('issue_date'),'expire_date':rec.get('expire_date'),'readback_bindings':visible,'expected_target_count':len(expected),'visible_exact_binding_count':len(visible),'all_target_pairs_present':all_present,'all_target_bindings_approved':all_approved,'state':'approved_and_all_pairs_bound' if all_present and all_approved and rec.get('status_code')=='approved' else ('links_present_pending_review' if all_present else 'readback_incomplete')})
    save(state)
state['finished_at_utc']=now();state['local_file_deleted']=False;save(state)
print(json.dumps({'state_file':str(STATE),'number':NUMBER,'ozon':{k:state['ozon'].get(k) for k in ('state','certificate_id','record_status','visible_exact_binding_count','expected_target_count','all_target_pairs_present','all_target_bindings_approved','invalid_params')},'wb':{'write_sent':False,'missing_exact_cards':state['wb']['missing_exact_cards'],'tnved_mismatch_cards':state['wb']['tnved_mismatch_cards']},'local_file_deleted':False},ensure_ascii=False,indent=2))
