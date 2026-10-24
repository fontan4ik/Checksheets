from __future__ import annotations
import base64, collections, datetime as dt, hashlib, json, pathlib, sys

BASE = pathlib.Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT / 'test/certificate_api_pilot_20261012'))
from api_client import Client, digest, now
from group4_ozon import doc_identity
from group4_wb import CARD_FIELDS, prepare_card, compare_readback, signature

NUMBER = 'ЕАЭС N RU Д-CN.РА03.В.38440/22'
TYPE = 'declaration'
FILE = ROOT / 'output_to_user/certificates/group_1/documents/gauss/7232c1a1be2cdcd03f9de1f8.pdf'
EXPECTED_SHA = 'aa626fa757c6f796109a15a14a105a18257ebf7fbbbd770448ba76a718561e2b'
OFFERS = ['143424218-1','143424318-1','143426345-1','843425236-1','843425336-1']
ISSUE = '2022-05-11'
EXPIRY = '2027-04-28'
PREFLIGHT = BASE / 'gauss_38440_crossplatform_preflight_20261024.json'
STATE_PATH = BASE / 'gauss_38440_execution_20261024.json'
PAYLOAD_PATH = BASE / 'gauss_38440_wb_payload_20261024.json'


def save(state):
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(STATE_PATH)


def norm_brand(card):
    return str(card.get('brand') or '').casefold().strip()


def exact_ozon_records(client):
    records=[]
    for page in range(1,30):
        body=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
        batch=body.get('certificates') or []
        records.extend(batch)
        if len(batch)<100: break
    return [x for x in records if x.get('type_code')=='declaration' and doc_identity(x.get('certificate_number',''))==doc_identity(NUMBER)]


def bindings(client, certificate_id):
    return client.ozon_bindings(certificate_id)


def exact_wb_cards(client, offer):
    data=client.call('wb','/content/v2/get/cards/list',{'settings':{
        'sort':{'ascending':True},'cursor':{'limit':100},'filter':{'withPhoto':-1,'textSearch':offer}}})
    if data.get('error') or not isinstance(data.get('cards'),list):
        raise RuntimeError(f'Invalid WB card response for {offer}')
    return [x for x in data['cards'] if x.get('vendorCode')==offer]


if STATE_PATH.exists():
    raise RuntimeError(f'Existing execution state prevents duplicate run: {STATE_PATH}')
if not PREFLIGHT.is_file(): raise RuntimeError('Cross-platform preflight missing')
pre=json.loads(PREFLIGHT.read_text(encoding='utf-8'))
if not FILE.is_file() or digest(FILE).lower()!=EXPECTED_SHA:
    raise RuntimeError('Official source file missing or SHA-256 changed')
if [x.get('offer_id') for x in pre.get('source_targets',[])] != OFFERS:
    raise RuntimeError('Preflight target set/order changed')
if pre.get('document',{}).get('registry_id')!='16706704':
    raise RuntimeError('FSA record not confirmed in preflight')

client=Client()
state={'started_at':now(),'number':NUMBER,'type_code':TYPE,'fsa_record_id':'16706704',
       'validity':{'from':ISSUE,'through':EXPIRY},'source_file':str(FILE),'source_sha256':digest(FILE),
       'target_offers':OFFERS,'ozon':{'state':'fresh_preflight'},'wb':{'state':'fresh_preflight'},
       'local_file_delete_allowed':False}
save(state)

# Fresh Ozon identity + explicit brand proof immediately before any write.
info=client.call('ozon','/v3/product/info/list',{'offer_id':OFFERS}).get('items') or []
by_offer={str(x.get('offer_id')):x for x in info}
if set(by_offer)!=set(OFFERS): raise RuntimeError('Fresh Ozon product set differs from the five exact targets')
attr=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':OFFERS},'limit':len(OFFERS)}).get('result') or []
brand_by={}
for row in attr:
    vals=[]
    for a in row.get('attributes',[]):
        if str(a.get('id'))=='85': vals += [v.get('value') for v in a.get('values',[])]
    brand_by[str(row.get('offer_id'))]=vals
if set(brand_by)!=set(OFFERS) or any(not any(str(v).casefold()=='gauss' for v in brand_by[o]) for o in OFFERS):
    raise RuntimeError('Fresh Ozon brand attributes do not confirm GAUSS for all five offers')
products={}
for offer,p in by_offer.items():
    pid=str(p.get('product_id') or p.get('id') or '')
    sku=str(p.get('sku') or '')
    if not pid or not sku or p.get('is_archived'):
        raise RuntimeError(f'Fresh Ozon identity missing, archived, or SKU-less: {offer}')
    products[offer]={'offer_id':offer,'product_id':pid,'sku':sku,'name':p.get('name'),'brand':brand_by[offer]}
state['ozon'].update({'fresh_products':products,'brands_verified':True})
save(state)

# Create only if a fresh exact-number search still finds no record.
records=exact_ozon_records(client)
if len(records)>1:
    state['ozon'].update({'state':'blocked_multiple_live_records','matching_ids':[x.get('certificate_id') for x in records]});save(state)
    raise RuntimeError('Multiple Ozon records for the exact declaration; no mutation sent')
if records:
    rec=records[0];cid=rec.get('certificate_id');status=rec.get('status_code')
    attached=bindings(client,cid)
    by_pair={(str(b.get('sku')),str(b.get('product_id'))):b for b in attached}
    pending=[o for o,p in products.items() if (p['sku'],p['product_id']) in by_pair and by_pair[(p['sku'],p['product_id'])].get('product_status_code')!='approved']
    missing=[o for o,p in products.items() if (p['sku'],p['product_id']) not in by_pair]
    state['ozon'].update({'certificate_id':cid,'record_status':status,'existing_bindings':attached,
                          'pending_offers':pending,'unbound_offers':missing})
    if status!='approved':
        state['ozon']['state']='existing_record_pending_or_declined_no_rebind'
    elif pending:
        state['ozon']['state']='existing_product_bindings_pending_or_declined_no_rebind'
    elif missing:
        # Bind only absent pairs on a globally approved record; never repeat pending pairs.
        state['ozon']['mutation_state']='bind_sent';state['ozon']['mutation_started_at']=now();save(state)
        response=client.call('ozon','/v1/product/certificate/bind',{
            'certificate_id':int(cid),'skus':sorted({products[o]['sku'] for o in missing})},mutation=True)
        state['ozon']['bind_response']=response;state['ozon']['mutation_state']='bind_accepted';save(state)
        readback=bindings(client,cid);after={(str(b.get('sku')),str(b.get('product_id'))):b for b in readback}
        wanted={(products[o]['sku'],products[o]['product_id']) for o in missing}
        state['ozon']['readback_bindings']=[after[k] for k in sorted(wanted) if k in after]
        state['ozon']['state']='existing_record_bound_readback_present' if wanted.issubset(after) else 'bind_readback_incomplete'
    else:
        state['ozon']['state']='already_bound'
    save(state)
else:
    issue=dt.date.fromisoformat(ISSUE);end=dt.date.fromisoformat(EXPIRY)
    params={'name':'Декларация о соответствии № '+NUMBER,'certificate_type':'DECLARATION',
            'certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,
            'issue_date':ISSUE+'T00:00:00Z',
            'expired_date':{'date':{'day':end.day,'month':end.month,'year':end.year}},
            'skus':sorted({p['sku'] for p in products.values()}),'product_type':'UNKNOWN',
            'files':[{'file_content':base64.b64encode(FILE.read_bytes()).decode('ascii'),'name':FILE.name}]}
    encoded=json.dumps({'params':params},ensure_ascii=False,separators=(',',':')).encode()
    if len(encoded)>15_000_000:raise RuntimeError('Ozon request exceeds verified payload ceiling')
    # One non-retried create; a timeout is uncertain and must not be repeated.
    state['ozon'].update({'mutation_state':'create_sent','mutation_started_at':now(),
                          'request_sha256':hashlib.sha256(encoded).hexdigest(),'request_bytes':len(encoded)})
    save(state)
    try:
        response=client.call('ozon','/v2/product/certificate/create',{'params':params},mutation=True)
    except Exception as exc:
        state['ozon'].update({'state':'uncertain_create_reconcile_before_retry','mutation_state':'uncertain',
                              'error_type':type(exc).__name__,'finished_at':now()});save(state)
        raise
    invalid=[x for x in (response.get('params') or []) if x.get('state')=='INVALID']
    cid=response.get('certificate_id')
    state['ozon'].update({'create_response':response,'certificate_id':cid,'create_status':response.get('status'),
                          'invalid_params':invalid,'mutation_state':'response_received','mutation_finished_at':now()})
    save(state)
    if not cid or response.get('status')!='COMPLETED' or invalid:
        state['ozon']['state']='create_incomplete_no_retry';save(state)
    else:
        # Read back exact live record and target bindings; do not infer from create response.
        live=exact_ozon_records(client)
        if len(live)!=1:
            state['ozon'].update({'state':'create_readback_record_missing_or_duplicate','matching_record_count':len(live)});save(state)
        else:
            cert=live[0];live_bindings=bindings(client,cert['certificate_id'])
            live_pairs={(str(b.get('sku')),str(b.get('product_id'))):b for b in live_bindings}
            wanted={(p['sku'],p['product_id']) for p in products.values()}
            if not wanted.issubset(live_pairs) and cert.get('status_code')=='approved':
                missing=[p for p in products.values() if (p['sku'],p['product_id']) not in live_pairs]
                state['ozon']['mutation_state']='bind_sent';state['ozon']['bind_started_at']=now();save(state)
                bind_response=client.call('ozon','/v1/product/certificate/bind',{
                    'certificate_id':int(cert['certificate_id']),'skus':sorted({p['sku'] for p in missing})},mutation=True)
                state['ozon']['bind_response']=bind_response;state['ozon']['bind_finished_at']=now();save(state)
                live_bindings=bindings(client,cert['certificate_id'])
                live_pairs={(str(b.get('sku')),str(b.get('product_id'))):b for b in live_bindings}
            state['ozon'].update({'live_record_status':cert.get('status_code'),
                                  'readback_bindings':[live_pairs[k] for k in sorted(wanted) if k in live_pairs],
                                  'all_target_pairs_present':wanted.issubset(live_pairs),
                                  'state':'created_and_bound_readback_present' if wanted.issubset(live_pairs) else 'created_but_target_links_unconfirmed'})
            save(state)

# Fresh WB card readback and append-only metadata update for exact current cards.
wb_before={};missing_wb=[]
for offer in OFFERS:
    rows=exact_wb_cards(client,offer)
    if len(rows)>1:
        state['wb'].update({'state':'blocked_duplicate_cards','offer':offer,'nmIDs':[x.get('nmID') for x in rows]});save(state)
        raise RuntimeError(f'Multiple exact WB cards for {offer}; no WB update sent')
    if not rows:
        missing_wb.append(offer);continue
    card=rows[0]
    if norm_brand(card) not in ('gauss',''):
        state['wb'].update({'state':'blocked_brand_mismatch','offer':offer,'brand':card.get('brand')});save(state)
        raise RuntimeError(f'WB brand mismatch for exact article {offer}; no WB update sent')
    wb_before[offer]=card

desired={'type':2,'number':NUMBER,'startDate':ISSUE+'T00:00:00Z','endDate':EXPIRY+'T00:00:00Z','isEndless':False}
prepared=[];already=[]
for offer,card in wb_before.items():
    row=prepare_card(card,[desired])
    if row['additions']:prepared.append(row)
    else:already.append(offer)
if any(((r['before'].get('documents') or {}).get('excludeDocuments') is True) for r in prepared):
    state['wb'].update({'state':'blocked_excluded_documents_flag','offers':[r['vendorCode'] for r in prepared]});save(state)
    raise RuntimeError('WB target currently excludes documents; no WB update sent')
payloads=[r['payload'] for r in prepared]
size=len(json.dumps(payloads,ensure_ascii=False,separators=(',',':')).encode())
if size>10_000_000:raise RuntimeError('WB payload too large')
state['wb'].update({'missing_exact_cards':missing_wb,'already_present':already,
                    'exact_cards_to_update':[{'offer':r['vendorCode'],'nmID':r['nmID']} for r in prepared],
                    'request_bytes':size,'state':'prepared'})
PAYLOAD_PATH.write_text(json.dumps(payloads,ensure_ascii=False,indent=2),encoding='utf-8')
save(state)
if payloads:
    state['wb'].update({'state':'mutation_sent','mutation_started_at':now()});save(state)
    try:
        response=client.call('wb','/content/v2/cards/update',payloads,mutation=True)
    except Exception as exc:
        state['wb'].update({'state':'uncertain_update_reconcile_before_retry','error_type':type(exc).__name__,'mutation_finished_at':now()});save(state)
        raise
    state['wb']['mutation_response']={k:response.get(k) for k in ('error','errorText','additionalErrors','data') if k in response}
    state['wb']['mutation_finished_at']=now()
    if response.get('error') is not False:
        state['wb']['state']='update_response_not_accepted_reconcile';save(state)
        raise RuntimeError('WB did not accept metadata update; do not retry before live reconciliation')
    state['wb']['state']='accepted_readback'
    save(state)

# Verify each exact card and all preexisting fields/documents. WB approval stays asynchronous.
readback={};all_visible=True;all_preserved=True
for offer,card in wb_before.items():
 rows=exact_wb_cards(client,offer)
 after=rows[0] if len(rows)==1 else None
 match=None
 if after:
  for d in ((after.get('documents') or {}).get('items') or []):
   if signature(d)==signature(desired) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY:
    match=d;break
 visible=match is not None
 preservation=compare_readback(card,after) if after else {'preserved':False,'fields':{},'differences':{'card_missing_or_duplicate':True}}
 all_visible &= visible
 all_preserved &= bool(preservation.get('preserved'))
 readback[offer]={'nmID':(after or {}).get('nmID'),'document_visible':visible,'document':match,
                  'verdict':(match or {}).get('verdict'),'unrelated_fields_preserved':preservation.get('preserved'),
                  'preservation':preservation}
 state['wb']['readback']=readback;save(state)
state['wb']['state']='readback_complete_pending_wb_review' if all_visible and all_preserved else 'readback_needs_review'
state['finished_at']=now();save(state)
print(json.dumps({'finished_at':state['finished_at'],'ozon':{k:v for k,v in state['ozon'].items() if k not in ('create_response','existing_bindings','readback_bindings','fresh_products')},'wb':{'state':state['wb']['state'],'cards_written':len(payloads),'cards_already_present':already,'missing_exact_cards':missing_wb,'readback':{k:{'nmID':v['nmID'],'document_visible':v['document_visible'],'verdict':v['verdict'],'unrelated_fields_preserved':v['unrelated_fields_preserved']} for k,v in readback.items()}},'local_file_delete_allowed':False},ensure_ascii=False,indent=2))
