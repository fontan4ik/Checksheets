#!/usr/bin/env python3
"""Bind the source-confirmed, FSA-active Arlight declaration 13936/25 on Ozon and WB."""
from __future__ import annotations
import hashlib, json, sys, time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents
from run_all_found_certificates_20261014 import merge_wb, wb_scope_error
PREFLIGHT=HERE/'arlight_13936_crossplatform_live_preflight_20261023.json'
OUT=HERE/'arlight_13936_crossplatform_execution_20261023.json'
JOURNAL=HERE/'arlight_13936_crossplatform_mutation_journal_20261023.jsonl'
NUMBER='ЕАЭС N RU Д-HK.РА02.В.13936/25'; KEY=norm_number(NUMBER)
ISSUE='2025-02-20'; EXPIRY='2030-02-19'; CODE='8539519009'
CONFIRMED_FSA_URL='https://pub.fsa.gov.ru/rds/declaration/view/19916418/product'

def save(state):
    temp=OUT.with_suffix('.tmp'); temp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n'); temp.replace(OUT)
def journal(**row):
    with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps({'at':now(),**row},ensure_ascii=False)+'\n'); f.flush()
def norm_dates(doc):
    return (norm_number(doc.get('number')),int(doc.get('type') or 0),str(doc.get('startDate') or '')[:10],str(doc.get('endDate') or '')[:10])
def wb_codes(card):
    vals=[]
    for char in card.get('characteristics') or []:
        label=''.join(str(char.get('name') or '').casefold().split()).replace('ё','е')
        if 'тнвэд' in label or 'тнвед' in label:
            raw=char.get('value'); vals.extend(raw if isinstance(raw,list) else [raw])
    return {str(v or '').split(' - ',1)[0].strip() for v in vals if str(v or '').split(' - ',1)[0].strip()}
def lookup_cert(client):
    rows=[];page=1;seen=set()
    while True:
        result=client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100})['result']
        batch=result['certificates']
        for c in batch:
            cid=str(c.get('certificate_id'))
            if cid in seen: raise RuntimeError('certificate_page_duplicate')
            seen.add(cid);rows.append(c)
        if not batch or page>=result['page_count']:break
        page+=1
    exact=[c for c in rows if norm_number(c.get('certificate_number'))==KEY and c.get('type_code')=='declaration' and c.get('accordance_type_code')=='EAEU' and str(c.get('issue_date',''))[:10]==ISSUE and str(c.get('expire_date',''))[:10]==EXPIRY]
    if len(exact)!=1: raise RuntimeError(f'ozon_exact_record_changed:{len(exact)}')
    c=exact[0]
    if c.get('status_code')!='approved' or not (ISSUE<=date.today().isoformat()<=EXPIRY): raise RuntimeError('ozon_record_not_current_approved')
    return c

def refresh_ozon_products(client,targets):
    offers=[x['offer_id'] for x in targets]
    products=[];attrs=[]
    for start in range(0,len(offers),100):
        batch=offers[start:start+100]
        products.extend(client.call('ozon','/v3/product/info/list',{'offer_id':batch})['items'])
        attrs.extend(client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':100}).get('result') or [])
    bp=defaultdict(list);ba=defaultdict(list)
    for p in products:bp[str(p.get('offer_id') or '')].append(p)
    for a in attrs:ba[str(a.get('offer_id') or '')].append(a)
    refreshed=[]
    for t in targets:
        offer=t['offer_id'];ps=bp.get(offer,[]);ars=ba.get(offer,[])
        if len(ps)!=1 or len(ars)!=1: raise RuntimeError(f'ozon_product_missing_or_duplicate:{offer}')
        p=ps[0]; aa={str(x.get('id')):x for x in ars[0].get('attributes') or []}
        brands=[str(v.get('value') or '').strip() for v in (aa.get('85') or {}).get('values') or []]
        vals=[v.get('value') for v in (aa.get('22232') or {}).get('values') or []]
        codes={str(v or '').split(' - ',1)[0].strip() for v in vals if str(v or '').split(' - ',1)[0].strip()}
        if p.get('is_archived') is not False or str(p.get('product_id') or p.get('id'))!=t['product_id'] or str(p.get('sku') or '')!=t['sku']:
            raise RuntimeError(f'ozon_identity_changed:{offer}')
        if brands!=['Arlight'] or codes!={CODE}: raise RuntimeError(f'ozon_scope_changed:{offer}:{brands}:{sorted(codes)}')
        refreshed.append(p)
    return refreshed

def read_wb_card(client,offer):
    cards=client.wb_cards(offer)
    if len(cards)!=1 or str(cards[0].get('vendorCode') or '')!=offer: raise RuntimeError(f'wb_card_identity_changed:{offer}')
    card=cards[0]
    err=wb_scope_error(card,{'allowed_tnved':[CODE]},{'brand':'Arlight'})
    if err or wb_codes(card)!={CODE}: raise RuntimeError(f'wb_scope_changed:{offer}:{err}:{sorted(wb_codes(card))}')
    return card

def main():
    pf=json.loads(PREFLIGHT.read_text())
    if pf.get('read_only') is not True or pf.get('target_count')!=192 or pf.get('fsa_status')!='Действует' or pf.get('fsa_registry_url')!=CONFIRMED_FSA_URL:
        raise RuntimeError('preflight_not_authorized_or_complete')
    checked=datetime.fromisoformat(str(pf['checked_at_utc']).replace('Z','+00:00'))
    if (datetime.now(timezone.utc)-checked).total_seconds()>1800: raise RuntimeError('preflight_too_old')
    targets=pf['targets']; offers={x['offer_id'] for x in targets}
    if len(targets)!=192 or len(offers)!=192: raise RuntimeError('target_identity_duplicates')
    state={'started_at':now(),'document_number':NUMBER,'fsa_registry_url':CONFIRMED_FSA_URL,'fsa_status':'Действует',
      'source_pdf_sha256':pf['source_pdf_sha256'],'ozon':{},'wb':{'expected_cards':192,'mutation_batches':[],'initial_readback':[],'delayed_readbacks':[]},
      'no_local_files_deleted':True}
    save(state)
    client=Client()
    # Ozon: refresh exact record, all target product identities, and binding state immediately before mutation.
    cert=lookup_cert(client);bindings=client.ozon_bindings(cert['certificate_id'])
    products=refresh_ozon_products(client,targets)
    binding_by_pid={str(x.get('product_id')):x for x in bindings}
    missing=[];existing=[]
    for t in targets:
        b=binding_by_pid.get(t['product_id'])
        if b:
            if str(b.get('sku'))!=t['sku']: raise RuntimeError(f'ozon_binding_identity_conflict:{t["offer_id"]}')
            if b.get('product_status_code')!='approved': existing.append({'offer_id':t['offer_id'],'status':b.get('product_status_code')})
        else: missing.append(t)
    state['ozon']={'certificate_id':cert['certificate_id'],'record_status':cert['status_code'],'record_products_count':cert.get('products_count'),
      'before_binding_count':len(bindings),'target_count':192,'existing_target_bindings':len(targets)-len(missing),'existing_nonapproved':existing,
      'missing_before_write':len(missing),'mutation_sent':False}
    save(state)
    if missing:
        skus=sorted(x['sku'] for x in missing)
        if len(set(skus))!=len(skus): raise RuntimeError('duplicate_ozon_sku_in_batch')
        marker=hashlib.sha256(','.join(skus).encode()).hexdigest()
        for x in missing: journal(platform='ozon',phase='prepared',key=f'ozon:bind_sku:{cert["certificate_id"]}:{x["sku"]}',offer_id=x['offer_id'],sku=x['sku'],product_id=x['product_id'])
        journal(platform='ozon',phase='sending',key=f'ozon:bind:{cert["certificate_id"]}:{marker}',items=len(skus))
        try:
            response=client.call('ozon','/v1/product/certificate/bind',{'certificate_id':int(cert['certificate_id']),'skus':skus},mutation=True)
            state['ozon']['mutation_sent']=True;state['ozon']['mutation_response']=response
            journal(platform='ozon',phase='response',key=f'ozon:bind:{cert["certificate_id"]}:{marker}',response=response)
        except Exception as exc:
            state['ozon']['mutation_uncertain']=type(exc).__name__;journal(platform='ozon',phase='uncertain',error_type=type(exc).__name__);save(state)
    live=client.ozon_bindings(cert['certificate_id'])
    live_by_pid={str(x.get('product_id')):x for x in live}
    oz_read=[]
    for t in targets:
        b=live_by_pid.get(t['product_id'])
        oz_read.append({'offer_id':t['offer_id'],'product_id':t['product_id'],'sku':t['sku'],'binding_present':bool(b),
          'binding_status':b.get('product_status_code') if b else None,'sku_matches':bool(b and str(b.get('sku'))==t['sku'])})
    state['ozon'].update(after_binding_count=len(live),target_readback=oz_read,
      target_present=sum(1 for x in oz_read if x['binding_present'] and x['sku_matches']),
      target_approved=sum(1 for x in oz_read if x['binding_status']=='approved' and x['sku_matches']))
    save(state)
    # WB: live pre-write card check, exact merge preserving existing card fields/documents, 100-card batches.
    desired={'type':2,'number':NUMBER,'startDate':ISSUE+'T00:00:00Z','endDate':EXPIRY+'T00:00:00Z','isEndless':False}
    updates=[];already=[]
    for i,t in enumerate(targets,1):
        card=read_wb_card(client,t['offer_id'])
        matches=[d for d in copy_documents(card) if norm_number(d.get('number'))==KEY]
        if matches:
            exact=[d for d in matches if norm_dates(d)==(KEY,2,ISSUE,EXPIRY)]
            if len(exact)!=len(matches): raise RuntimeError(f'wb_existing_document_conflict:{t["offer_id"]}')
            already.append({'offer_id':t['offer_id'],'nmID':str(card.get('nmID')),'existing':len(exact)})
            continue
        payload=merge_wb(card,[desired])
        if payload is None: raise RuntimeError(f'wb_merge_empty:{t["offer_id"]}')
        updates.append({'offer_id':t['offer_id'],'nmID':str(card.get('nmID')),'payload':payload,'before':card})
        if i%25==0: print(json.dumps({'wb_live_prewrite_checked':i,'cards_to_submit':len(updates)},ensure_ascii=False),flush=True)
    state['wb'].update(already_present=len(already),prewrite_missing=len(updates),prewrite_exact_card_checks=len(targets))
    save(state)
    for start in range(0,len(updates),100):
        batch=updates[start:start+100]
        # Build a fresh full-card payload immediately before each mutation; do not retry an uncertain batch.
        refreshed=[]
        for x in batch:
            card=read_wb_card(client,x['offer_id'])
            if str(card.get('nmID'))!=x['nmID']: raise RuntimeError(f'wb_nmID_changed_before_write:{x["offer_id"]}')
            matches=[d for d in copy_documents(card) if norm_number(d.get('number'))==KEY]
            if matches:
                if any(norm_dates(d)!=(KEY,2,ISSUE,EXPIRY) for d in matches): raise RuntimeError(f'wb_conflict_before_write:{x["offer_id"]}')
                already.append({'offer_id':x['offer_id'],'nmID':x['nmID'],'appeared_before_write':True})
                continue
            payload=merge_wb(card,[desired])
            if payload is not None: refreshed.append({**x,'payload':payload,'before':card})
        if not refreshed: continue
        payload=[x['payload'] for x in refreshed]
        marker=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        for x in refreshed: journal(platform='wb',phase='prepared',key=f'wb:{x["nmID"]}:{KEY}',offer_id=x['offer_id'],nmID=x['nmID'])
        journal(platform='wb',phase='sending',key=f'wb:batch:{marker}',items=len(payload))
        batch_state={'marker':marker,'offers':[x['offer_id'] for x in refreshed],'items':len(refreshed),'response':None,'uncertain':False}
        state['wb']['mutation_batches'].append(batch_state);save(state)
        try:
            response=client.call('wb','/content/v2/cards/update',payload,mutation=True)
            batch_state['response']=response;batch_state['accepted']=isinstance(response,dict) and response.get('error') is False
            journal(platform='wb',phase='response',key=f'wb:batch:{marker}',response=response)
        except Exception as exc:
            batch_state['uncertain']=True;batch_state['error_type']=type(exc).__name__
            journal(platform='wb',phase='uncertain',key=f'wb:batch:{marker}',error_type=type(exc).__name__)
        save(state)
        # First readback is a verification only; never repeat the mutation on delayed visibility.
        for x in refreshed:
            try:
                fresh=read_wb_card(client,x['offer_id'])
                exact=[d for d in copy_documents(fresh) if norm_dates(d)==(KEY,2,ISSUE,EXPIRY)]
                prior={(norm_number(d.get('number')),int(d.get('type') or 0),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10]) for d in copy_documents(x['before'])}
                after={(norm_number(d.get('number')),int(d.get('type') or 0),str(d.get('startDate') or '')[:10],str(d.get('endDate') or '')[:10]) for d in copy_documents(fresh)}
                verdicts=[d.get('verdict') or {} for d in exact]
                wb_valid=any(v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' for v in verdicts)
                status='valid' if wb_valid else 'pending_review_or_verdict_absent'
                if any(v.get('status') not in (None,1) or v.get('reason') not in (None,'','valid') for v in verdicts):status='rejected_or_invalid'
                state['wb']['initial_readback'].append({'offer_id':x['offer_id'],'nmID':x['nmID'],'document_visible':bool(exact),'verdict':status,'all_exact_matches':len(exact),'prior_documents_preserved':prior<=after})
            except Exception as exc: state['wb']['initial_readback'].append({'offer_id':x['offer_id'],'nmID':x['nmID'],'error_type':type(exc).__name__})
        save(state)
    # Delayed state reconciliation only. Never re-send WB writes.
    unresolved=[x for x in state['wb']['initial_readback'] if x.get('document_visible') is not True]
    for wait_seconds in (60,120):
        if not unresolved: break
        print(json.dumps({'wb_delayed_recheck_wait_seconds':wait_seconds,'remaining':len(unresolved),'no_resend':True},ensure_ascii=False),flush=True)
        time.sleep(wait_seconds)
        next_unresolved=[]
        for x in unresolved:
            try:
                card=read_wb_card(client,x['offer_id'])
                exact=[d for d in copy_documents(card) if norm_dates(d)==(KEY,2,ISSUE,EXPIRY)]
                verdicts=[d.get('verdict') or {} for d in exact]
                valid=any(v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid' for v in verdicts)
                rejected=any(v.get('status') not in (None,1) or v.get('reason') not in (None,'','valid') for v in verdicts)
                entry={'offer_id':x['offer_id'],'nmID':x['nmID'],'document_visible':bool(exact),
                  'verdict':'valid' if valid else ('rejected_or_invalid' if rejected else 'pending_review_or_verdict_absent')}
                state['wb']['delayed_readbacks'].append(entry)
                if not exact:next_unresolved.append(x)
            except Exception as exc:
                state['wb']['delayed_readbacks'].append({'offer_id':x['offer_id'],'nmID':x['nmID'],'error_type':type(exc).__name__});next_unresolved.append(x)
        unresolved=next_unresolved;save(state)
    state['wb']['still_not_visible_after_delayed_recheck']=len(unresolved)
    state['wb']['valid_count']=sum(1 for x in state['wb']['initial_readback'] if x.get('verdict')=='valid')+sum(1 for x in state['wb']['delayed_readbacks'] if x.get('verdict')=='valid')
    state['wb']['pending_or_unverified_count']=sum(1 for x in state['wb']['initial_readback'] if x.get('verdict')=='pending_review_or_verdict_absent')+sum(1 for x in state['wb']['delayed_readbacks'] if x.get('verdict')=='pending_review_or_verdict_absent')
    state['finished_at']=now();save(state)
    print(json.dumps({'execution_file':str(OUT),'ozon':{'certificate_id':state['ozon']['certificate_id'],'missing_before_write':state['ozon']['missing_before_write'],'target_present':state['ozon']['target_present'],'target_approved':state['ozon']['target_approved']},
      'wb':{'submitted_cards':sum(x['items'] for x in state['wb']['mutation_batches']),'initial_visible':sum(1 for x in state['wb']['initial_readback'] if x.get('document_visible')),
        'valid':state['wb']['valid_count'],'pending_or_unverified':state['wb']['pending_or_unverified_count'],'still_not_visible_after_delayed_recheck':state['wb']['still_not_visible_after_delayed_recheck']},
      'no_local_files_deleted':True},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
