"""Unattended all-brand reconciliation. Dry-run unless --execute. Never deletes files.
Each mutation has a durable prepared journal entry; a restart never repeats it.
"""
from __future__ import annotations
import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from collections import Counter
from api_client import Client, now, digest
from reconcile_approved_ozon_docs_to_wb import (norm_number, doc_key, wb_datetime,
    copy_documents, UPDATE_CARD_FIELDS, OZON_TO_WB_TYPE, comparable_card)

BASE = Path(__file__).resolve().parent
STATE = BASE / 'all_found_certificates_bulk_state_20261014.json'
JOURNAL = BASE / 'all_found_certificates_bulk_journal_20261014.jsonl'


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush(); os.fsync(out.fileno())
    temporary.replace(path)


def valid_dates(issue, expiry):
    try:
        start = dt.date.fromisoformat(str(issue)[:10])
        end = dt.date.fromisoformat(str(expiry)[:10])
        return start <= dt.datetime.now(dt.timezone.utc).date() <= end and start <= end
    except (ValueError, TypeError):
        return False


def brand_key(value):
    return ''.join(str(value or '').casefold().split())


def wb_scope_error(card, group, target):
    if brand_key(card.get('brand'))!=brand_key(target.get('brand')): return 'wb_source_brand_mismatch'
    allowed=group.get('allowed_tnved')
    if allowed:
        codes=[]
        for char in card.get('characteristics') or []:
            name=''.join(str(char.get('name') or '').casefold().split()).replace('ё','е')
            if 'тнвэд' in name or 'тнвед' in name:
                raw=char.get('value'); values=raw if isinstance(raw,list) else [raw]
                codes.extend(str(x or '').split(' - ',1)[0].strip() for x in values)
        if not codes or '' in codes or not set(codes)<=set(map(str,allowed)): return 'wb_source_tnved_unconfirmed'
    return None


def group_error(group):
    if group.get('type_code') not in OZON_TO_WB_TYPE: return 'unknown_type'
    if group.get('accordance_type') != 'EAEU': return 'unsupported_accordance'
    if not norm_number(group.get('number')): return 'missing_number'
    if not valid_dates(group.get('issue_date'), group.get('expire_date')): return 'invalid_dates'
    file = group.get('upload_file') or {}
    path = Path(file.get('path') or '')
    if not path.is_file(): return 'missing_file'
    if not file.get('sha256') or digest(path) != file['sha256']: return 'file_hash_mismatch'
    if not group.get('targets'): return 'empty_targets'
    return None


def merge_wb(card, desired):
    """Preserve all writable fields and prior docs; refuse type/date conflicts."""
    items = copy_documents(card)
    legal={}
    for wanted in desired:
        key=norm_number(wanted.get('number'))
        signature=(wanted.get('type'),str(wanted.get('startDate',''))[:10],str(wanted.get('endDate',''))[:10])
        if key in legal and legal[key]!=signature: raise ValueError('conflicting_desired_type_or_dates')
        legal[key]=signature
    additions = []
    for wanted in desired:
        same = [x for x in items if norm_number(x.get('number')) == norm_number(wanted['number'])]
        if same:
            if any(doc_key(x) != doc_key(wanted) or
                (str(x.get('startDate',''))[:10], str(x.get('endDate',''))[:10]) !=
                (wanted['startDate'][:10], wanted['endDate'][:10]) for x in same):
                raise ValueError('existing_type_or_date_conflict')
        elif doc_key(wanted) not in {doc_key(x) for x in additions}:
            additions.append(wanted)
    if not additions: return None
    payload = {k: card[k] for k in UPDATE_CARD_FIELDS if k in card}
    payload['documents'] = {'items': items + additions, 'excludeDocuments': False}
    return payload


def deduplicate_equivalent_wb_rows(cards):
    """Collapse cursor overlaps only when every value is equivalent.

    Characteristic array order can differ during WB pagination. Different
    documents (including validation verdicts) or any other field stay ambiguous.
    """
    buckets={}; result=[]; duplicates=0
    for card in cards:
        identity=(card.get('nmID'),card.get('vendorCode'))
        rest={k:v for k,v in card.items() if k!='characteristics'}
        signature=(json.dumps(rest,sort_keys=True,ensure_ascii=False),
                   tuple(sorted(Counter(json.dumps(c,sort_keys=True,ensure_ascii=False)
                         for c in card.get('characteristics') or []).items())))
        if None not in identity and signature in buckets.setdefault(identity,set()):
            duplicates+=1
            continue
        buckets.setdefault(identity,set()).add(signature); result.append(card)
    return result,duplicates


class Runner:
    def __init__(self, client, manifest, execute=False, journal=JOURNAL, state=STATE):
        self.client, self.manifest, self.execute = client, manifest, execute
        self.journal, self.state_path = journal, state
        self.used = set()
        if journal.exists():
            for line in journal.read_text().splitlines():
                try: self.used.add(json.loads(line)['key'])
                except (ValueError, KeyError): raise RuntimeError('Corrupt mutation journal; stop')
        self.state = {'started_at': now(), 'pid':os.getpid(),'phase': 'initializing', 'execute': execute,
            'ready_group_count':len(manifest.get('groups') or []),'target_edge_count':sum(len(g.get('targets') or []) for g in manifest.get('groups') or []),
            'coverage': manifest.get('coverage', {}), 'source_skips': manifest.get('skips', []),
            'groups': [], 'skips': [], 'mutations': [], 'brand_results': {}, 'no_cleanup': True}
        self.products, self.cards, self.certs = [], [], []
        self.touched_certificate_ids = set()
        self.validated_source_groups = []
        self.skip_keys = set()

    def checkpoint(self, phase=None):
        if phase: self.state['phase'] = phase
        self.state['updated_at'] = now()
        atomic(self.state_path, self.state)
        print(json.dumps({'at': now(), 'phase': self.state['phase'],
            'groups_processed': len(self.state['groups']), 'skips': len(self.state['skips']),
            'mutations': len(self.state['mutations'])}, ensure_ascii=False), flush=True)

    def skip(self, reason, **data):
        row={'reason': reason, **data}
        key=json.dumps(row,sort_keys=True,ensure_ascii=False)
        if key not in self.skip_keys:
            self.skip_keys.add(key); self.state['skips'].append(row)

    def mutation(self, key, platform, endpoint, payload):
        if key in self.used:
            self.skip('previous_mutation_do_not_repeat', key=key)
            return None
        if not self.execute:
            self.state['mutations'].append({'key': key, 'phase': 'dry_run', 'platform': platform})
            return None
        row = {'key': key, 'phase': 'prepared', 'at': now(), 'platform': platform,
            'endpoint': endpoint, 'request_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
        self.used.add(key)
        with self.journal.open('a') as out:
            out.write(json.dumps(row, ensure_ascii=False)+'\n'); out.flush(); os.fsync(out.fileno())
        self.state['mutations'].append(row)
        self.checkpoint()
        try:
            body = self.client.call(platform, endpoint, payload, mutation=True)
            row.update(phase='response', response=body, finished_at=now())
        except Exception as exc:
            row.update(phase='uncertain', error_type=type(exc).__name__, finished_at=now())
            self.skip('uncertain_mutation_do_not_repeat', key=key)
            body = None
        with self.journal.open('a') as out:
            out.write(json.dumps(row, ensure_ascii=False)+'\n'); out.flush(); os.fsync(out.fileno())
        self.checkpoint()
        return body

    def read_products(self):
        self.checkpoint('all_brands_ozon_catalog')
        listed, cursor, seen = {}, '', set()
        while True:
            data = self.client.call('ozon', '/v3/product/list', {'filter': {'visibility':'ALL'}, 'last_id':cursor, 'limit':1000})['result']
            batch = data['items']
            for p in batch:
                pid = str(p.get('product_id') or p.get('id'))
                if pid in listed: raise RuntimeError('Duplicate Ozon product id')
                listed[pid] = p
            nxt = str(data.get('last_id') or '')
            if not batch or not nxt: break
            if nxt in seen: raise RuntimeError('Repeated Ozon catalog cursor')
            seen.add(nxt); cursor = nxt
        details = {}
        ids = list(listed)
        for start in range(0, len(ids), 100):
            rows = self.client.call('ozon', '/v3/product/info/list', {'product_id':[int(x) for x in ids[start:start+100]]})['items']
            for p in rows:
                pid = str(p.get('product_id') or p.get('id'))
                details[pid] = {**p, 'product_id':pid, 'sku':str(p.get('sku') or '')}
            if start % 5000 == 0:
                self.state['catalog_products_read'] = len(details); self.checkpoint()
        if set(details) != set(listed): raise RuntimeError('Incomplete Ozon catalog')
        self.products = [p for p in details.values() if p.get('is_archived') is False and p.get('offer_id') and p.get('sku')]
        atomic(BASE/'all_found_ozon_products_snapshot_20261014.json', {'checked_at':now(),'complete':True,'products':self.products})

    def list_certificate_metadata(self):
        records, page, seen = [], 1, set()
        while True:
            data=self.client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100})['result']
            batch=data['certificates']
            for c in batch:
                key=str(c.get('certificate_id'))
                if key in seen: raise RuntimeError('Repeated Ozon certificate page')
                seen.add(key)
            records.extend(batch)
            if not batch or page>=data['page_count']: return records
            page+=1

    def read_certificates(self):
        self.checkpoint('all_brands_ozon_certificates_and_bindings')
        records=self.list_certificate_metadata()
        for i, cert in enumerate(records):
            try: cert['live_bindings'] = self.client.ozon_bindings(cert['certificate_id'])
            except Exception as exc:
                cert['live_bindings'] = []; cert['bindings_failed'] = True
                self.skip('certificate_bindings_read_failed', certificate_id=cert['certificate_id'],error_type=type(exc).__name__)
            if i % 50 == 0:
                self.state['certificates_read'] = i+1; self.checkpoint()
        self.certs = records
        atomic(BASE/'all_found_ozon_certificates_snapshot_20261014.json', {'checked_at':now(),'complete':True,'certificates':records})

    def read_wb(self):
        self.checkpoint('all_brands_wb_catalog')
        cards, cursor, seen = [], {'limit':100}, set()
        while True:
            data = self.client.call('wb','/content/v2/get/cards/list',{'settings':{'sort':{'ascending':True},'cursor':cursor,'filter':{'withPhoto':-1}}})
            if data.get('error') or not isinstance(data.get('cards'),list): raise RuntimeError('Invalid WB catalog')
            batch=data['cards']; cards.extend(batch)
            if len(batch)<100: break
            returned=data['cursor']; signature=(returned.get('updatedAt'),returned.get('nmID'))
            if None in signature or signature in seen: raise RuntimeError('Repeated WB cursor')
            seen.add(signature); cursor={'limit':100,'updatedAt':signature[0],'nmID':signature[1]}
            if len(cards)%5000==0:
                self.state['wb_cards_read']=len(cards); self.checkpoint()
        raw_count=len(cards)
        cards,duplicates=deduplicate_equivalent_wb_rows(cards)
        self.cards=cards
        self.state['wb_catalog_raw_rows']=raw_count
        self.state['wb_catalog_equivalent_duplicates_removed']=duplicates
        atomic(BASE/'all_found_wb_cards_snapshot_20261014.json', {'checked_at':now(),'complete':True,'raw_rows':raw_count,'equivalent_duplicates_removed':duplicates,'cards':cards})

    def error_offers(self):
        errors={'020128-1':'known_brand_Arlight_missing'}
        cursor={'limit':100}; seen=set()
        for _ in range(1000):
            body=self.client.call('wb','/content/v2/cards/error/list',{'cursor':cursor,'order':{'ascending':True}})
            if body.get('error'): raise RuntimeError('WB error list failed')
            data=body.get('data') or {}
            for row in data.get('items') or []: errors.update(row.get('errors') or {})
            c=data.get('cursor') or {}
            if c.get('next') is not True: return errors
            sig=(c.get('updatedAt'),c.get('batchUUID'))
            if None in sig or sig in seen: raise RuntimeError('WB errors repeated cursor')
            seen.add(sig); cursor={'limit':100,'updatedAt':sig[0],'batchUUID':sig[1]}
        raise RuntimeError('WB errors exceeded pagination bound')

    def process_groups(self):
        self.checkpoint('all_found_manifest_groups')
        blocked=set(self.manifest.get('blocked_document_keys') or [])
        for group in self.manifest.get('groups') or []:
            number=group.get('number'); key=norm_number(number)
            result={'number':number,'brands':sorted({x.get('brand','') for x in group.get('targets',[])})}
            self.state['groups'].append(result)
            try:
                error=group_error(group)
                if error or key in blocked: raise ValueError(error or 'blocked_document_scope')
                targets=group['targets']; fresh=[]
                for start in range(0,len(targets),100):
                    fresh.extend(self.client.call('ozon','/v3/product/info/list',{'offer_id':[x['offer_id'] for x in targets[start:start+100]]})['items'])
                attr_by_offer={}
                for start in range(0,len(targets),100):
                    rows=self.client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':[x['offer_id'] for x in targets[start:start+100]]},'limit':100}).get('result') or []
                    for row in rows: attr_by_offer.setdefault(str(row.get('offer_id')),[]).append(row)
                by_offer={}
                for p in fresh: by_offer.setdefault(str(p.get('offer_id')),[]).append(p)
                eligible=[]
                for t in targets:
                    rows=by_offer.get(t['offer_id'],[])
                    if len(rows)!=1 or rows[0].get('is_archived') is not False or str(rows[0].get('product_id') or rows[0].get('id'))!=str(t['product_id']) or str(rows[0].get('sku'))!=str(t['sku']):
                        self.skip('target_identity_changed',number=number,offer_id=t['offer_id']); continue
                    attrrows=attr_by_offer.get(t['offer_id'],[])
                    if len(attrrows)!=1:
                        self.skip('live_attributes_missing_or_duplicate',number=number,offer_id=t['offer_id']); continue
                    attrs={str(x.get('id')):x for x in attrrows[0].get('attributes') or []}
                    brands=[str(x.get('value') or '').strip() for x in (attrs.get('85') or {}).get('values') or []]
                    if t.get('brand') and (len(brands)!=1 or brand_key(brands[0])!=brand_key(t['brand'])):
                        self.skip('live_brand_changed',number=number,offer_id=t['offer_id']); continue
                    allowed=group.get('allowed_tnved')
                    if allowed:
                        codes=[str(x.get('value') or '').split(' - ',1)[0].strip() for x in (attrs.get('22232') or {}).get('values') or []]
                        if not set(codes)<=set(map(str,allowed)) or not codes or '' in codes:
                            self.skip('live_tnved_unconfirmed',number=number,offer_id=t['offer_id']); continue
                    eligible.append(t)
                if not eligible: raise ValueError('no_live_eligible_targets')
                if group.get('source_evidence_verified') is True:
                    self.validated_source_groups.append({**group,'targets':eligible})
                records=[c for c in self.list_certificate_metadata() if norm_number(c.get('certificate_number'))==key]
                if len(records)>1: raise ValueError('duplicate_ozon_document_records')
                if records:
                    cert=records[0]
                    if cert.get('type_code')!=group['type_code'] or cert.get('accordance_type_code')!='EAEU' or str(cert.get('issue_date',''))[:10]!=group['issue_date'][:10] or str(cert.get('expire_date',''))[:10]!=group['expire_date'][:10]: raise ValueError('live_document_type_or_date_conflict')
                    if cert.get('status_code') not in ('approved','pending','checking','in_review','awaiting_verification'): raise ValueError('live_document_not_usable')
                else:
                    end=dt.date.fromisoformat(group['expire_date'][:10]); source=Path(group['upload_file']['path'])
                    if digest(source)!=group['upload_file']['sha256']: raise ValueError('file_hash_changed')
                    params={'name':'Документ '+number,'certificate_type':group['type_code'].upper(),'certificate_country':group['country'],'accordance_type':'EAEU','number':number,'issue_date':wb_datetime(group['issue_date']), 'expired_date':{'date':{'day':end.day,'month':end.month,'year':end.year}},'skus':[str(eligible[0]['sku'])],'product_type':'UNKNOWN','files':[{'file_content':base64.b64encode(source.read_bytes()).decode(),'name':source.name}]}
                    if group.get('link_to_registry'): params['link_to_registry']=group['link_to_registry']
                    if len(json.dumps(params).encode())>9_500_000: raise ValueError('create_request_too_large')
                    response=self.mutation('ozon:create:'+key,'ozon','/v2/product/certificate/create',{'params':params})
                    if not response: result['status']='dry_run_or_uncertain_create'; continue
                    states=[x.get('state') for x in response.get('params',[]) if isinstance(x,dict)]
                    if not response.get('certificate_id') or response.get('status')!='COMPLETED' or not states or set(states)!={'VALID'}: raise ValueError('create_response_not_validated')
                    cert={'certificate_id':response['certificate_id'],'certificate_number':number,'type_code':group['type_code'],'accordance_type_code':'EAEU','issue_date':group['issue_date'],'expire_date':group['expire_date'],'status_code':'pending','live_bindings':[]}
                    self.certs.append(cert)
                self.touched_certificate_ids.add(str(cert['certificate_id']))
                bindings=self.client.ozon_bindings(cert['certificate_id'])
                existing={str(x['product_id']):x for x in bindings}
                missing=[]
                for t in eligible:
                    prior=existing.get(str(t['product_id']))
                    if prior and str(prior.get('sku'))!=str(t['sku']): self.skip('binding_identity_conflict',number=number,offer_id=t['offer_id'])
                    elif prior and prior.get('product_status_code')=='declined': self.skip('existing_binding_declined',number=number,offer_id=t['offer_id'])
                    elif not prior:
                        single_key='ozon:bind_sku:'+str(cert['certificate_id'])+':'+str(t['sku'])
                        if single_key in self.used: self.skip('previous_bind_outcome_do_not_repeat',number=number,offer_id=t['offer_id'])
                        else: missing.append(t)
                for start in range(0,len(missing),500):
                    batch=missing[start:start+500]; skus=sorted(str(x['sku']) for x in batch)
                    marker=hashlib.sha256(','.join(skus).encode()).hexdigest()
                    if self.execute:
                        with self.journal.open('a') as out:
                            for sku in skus:
                                single_key='ozon:bind_sku:'+str(cert['certificate_id'])+':'+sku
                                self.used.add(single_key); out.write(json.dumps({'key':single_key,'phase':'prepared','at':now()})+'\n')
                            out.flush(); os.fsync(out.fileno())
                    response=self.mutation('ozon:bind:'+str(cert['certificate_id'])+':'+marker,'ozon','/v1/product/certificate/bind',{'certificate_id':int(cert['certificate_id']),'skus':skus})
                    if response is not None and response.get('result') is not True: self.skip('bind_response_rejected',number=number)
                cert['live_bindings']=self.client.ozon_bindings(cert['certificate_id'])
                existing_index=next((i for i,c in enumerate(self.certs) if str(c['certificate_id'])==str(cert['certificate_id'])),None)
                if existing_index is None: self.certs.append(cert)
                else: self.certs[existing_index]=cert
                result.update(status='processed',eligible=len(eligible),missing_bindings=len(missing),certificate_id=cert['certificate_id'])
            except Exception as exc:
                result.update(status='skipped',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
                self.skip('group_problem',number=number,detail=result['reason'])
            finally: self.checkpoint()

    def wb_reconcile(self):
        self.checkpoint('all_brands_wb_approved_documents_reconcile')
        blocked=set(self.manifest.get('blocked_document_keys') or [])
        by_sku={}; conflicts=set()
        for p in self.products:
            sku=str(p['sku'])
            if sku in by_sku: conflicts.add(sku)
            by_sku[sku]=p
        desired={}
        cardbrands={}
        for card in self.cards: cardbrands.setdefault(card.get('vendorCode'),set()).add(str(card.get('brand') or ''))
        brandblocks=self.manifest.get('blocked_binding_brands') or {}
        for cert in self.certs:
            number=cert.get('certificate_number'); typ=OZON_TO_WB_TYPE.get(cert.get('type_code'))
            if norm_number(number) in blocked or not typ or cert.get('accordance_type_code')!='EAEU' or cert.get('status_code')!='approved' or not valid_dates(cert.get('issue_date'),cert.get('expire_date')): continue
            for b in cert.get('live_bindings') or []:
                sku=str(b.get('sku')); p=by_sku.get(sku)
                if sku in conflicts or not p or str(p['product_id'])!=str(b.get('product_id')) or b.get('product_status_code')!='approved': continue
                if cardbrands.get(p['offer_id'],set()) & set(brandblocks.get(norm_number(number),[])):
                    self.skip('blocked_document_brand_scope',offer_id=p['offer_id'],number=number); continue
                wanted={'type':typ,'number':number,'startDate':wb_datetime(cert['issue_date']),'endDate':wb_datetime(cert['expire_date']),'isEndless':False}
                desired.setdefault(p['offer_id'],[]).append(wanted)
        by_offer={}
        for card in self.cards: by_offer.setdefault(card.get('vendorCode'),[]).append(card)
        direct_scopes={}
        for group in self.validated_source_groups:
            if group_error(group) or norm_number(group.get('number')) in blocked: continue
            for target in group['targets']:
                offer=target['offer_id']; exact=by_offer.get(offer,[])
                if len(exact)!=1:
                    self.skip('wb_source_card_missing_or_duplicate',offer_id=offer,number=group['number']); continue
                error=wb_scope_error(exact[0],group,target)
                if error:
                    self.skip(error,offer_id=offer,number=group['number']); continue
                wanted={'type':OZON_TO_WB_TYPE[group['type_code']],'number':group['number'],'startDate':wb_datetime(group['issue_date']),'endDate':wb_datetime(group['expire_date']),'isEndless':False}
                desired.setdefault(offer,[]).append(wanted)
                direct_scopes.setdefault(offer,[]).append((group,target))
        self.state['validated_independent_source_groups']=len(self.validated_source_groups)

        errors=self.error_offers(); updates=[]
        counts=Counter(); brands={}
        for index,(offer,docs) in enumerate(desired.items()):
            cards=by_offer.get(offer,[])
            brand=cards[0].get('brand','unknown') if len(cards)==1 else 'unknown'
            brands.setdefault(brand,Counter())['offers_scanned']+=1
            try:
                if offer in errors: raise ValueError('wb_error_list_requires_separate_fix')
                if len(cards)!=1: raise ValueError('wb_card_missing_or_duplicate')
                initial=merge_wb(cards[0],docs)
                if initial is None: counts['already_present']+=1; brands[brand]['already_present']+=1; continue
                exact=self.client.wb_cards(offer)
                if len(exact)!=1 or exact[0].get('nmID')!=cards[0].get('nmID'): raise ValueError('wb_live_identity_changed')
                for group,target in direct_scopes.get(offer,[]):
                    error=wb_scope_error(exact[0],group,target)
                    if group_error(group) or error: raise ValueError(error or 'source_hash_or_date_changed')
                payload=merge_wb(exact[0],docs)
                if payload is None: counts['already_present']+=1; continue
                # Stable per-card journal marker survives a restart and changed batch membership.
                keys=['wb:'+str(payload['nmID'])+':'+str(doc_key(d)) for d in docs]
                if any(k in self.used for k in keys): raise ValueError('previous_wb_mutation_do_not_repeat')
                updates.append({'offer':offer,'brand':brand,'payload':payload,'docs':docs,'keys':keys,'direct_scopes':direct_scopes.get(offer,[])})
                brands[brand]['cards_to_submit']+=1
            except ValueError as exc:
                counts['skipped']+=1; brands[brand]['skipped']+=1; self.skip(str(exc),offer_id=offer,brand=brand)
            if index%50==0: self.state['wb_scanned_offers']=index+1; self.checkpoint()
        self.state['brand_results']=brands
        self.state['wb_counts']=dict(counts)
        self.state['wb_planned_cards']=len(updates)
        self.checkpoint()
        batch=[]; size=0
        def submit(rows):
            if not rows: return
            refreshed=[]
            for x in rows:
                try:
                    live=self.client.wb_cards(x['offer'])
                    if len(live)!=1 or live[0].get('nmID')!=x['payload'].get('nmID'): raise ValueError('wb_identity_changed_before_submit')
                    for group,target in x.get('direct_scopes',[]):
                        error=wb_scope_error(live[0],group,target)
                        if group_error(group) or error: raise ValueError(error or 'source_hash_or_date_changed_before_submit')
                    payload=merge_wb(live[0],x['docs'])
                    if payload is not None: refreshed.append({**x,'payload':payload,'before':live[0]})
                except Exception as exc:
                    self.skip('wb_prewrite_recheck_failed',offer_id=x['offer'],error_type=type(exc).__name__)
            rows=refreshed
            if not rows: return
            payload=[x['payload'] for x in rows]
            marker=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
            # Each individual card is journaled before the batch could be sent.
            if self.execute:
                with self.journal.open('a') as out:
                    for x in rows:
                        for k in x['keys']:
                            self.used.add(k); out.write(json.dumps({'key':k,'phase':'prepared','at':now()})+'\n')
                    out.flush(); os.fsync(out.fileno())
            response=self.mutation('wb:batch:'+marker,'wb','/content/v2/cards/update',payload)
            if response is not None and response.get('error') is not False:
                self.skip('wb_batch_response_rejected',offers=[x['offer'] for x in rows]); return
            if response is not None: self.state['wb_accepted_cards']=self.state.get('wb_accepted_cards',0)+len(rows)
            readbacks=[]
            for x in rows:
                try:
                    fresh=self.client.wb_cards(x['offer'])
                    visible=len(fresh)==1 and merge_wb(fresh[0],x['docs']) is None
                    preserved=len(fresh)==1 and comparable_card(fresh[0])==comparable_card(x['before'])
                    prior={(doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10]) for d in copy_documents(x['before'])}
                    after={(doc_key(d),str(d.get('startDate',''))[:10],str(d.get('endDate',''))[:10]) for d in copy_documents(fresh[0])} if len(fresh)==1 else set()
                    prior_preserved=prior<=after
                    verdict='visible_review_left_pending' if visible and preserved and prior_preserved else 'accepted_awaiting_sync_or_preservation_check'
                    self.state.setdefault('wb_readback_counts',{})[verdict]=self.state.setdefault('wb_readback_counts',{}).get(verdict,0)+1
                    readbacks.append({'offer_id':x['offer'],'brand':x['brand'],'submitted':bool(response is not None),'expected_docs_visible':visible,'unrelated_fields_preserved':preserved,'prior_docs_preserved':prior_preserved,'verdict':verdict,'cards':fresh})
                except Exception as exc: readbacks.append({'offer_id':x['offer'],'error_type':type(exc).__name__})
            atomic(BASE/('all_found_wb_readback_'+marker[:16]+'.json'),{'checked_at':now(),'results':readbacks,'wb_review_left_pending':True})
            self.state.setdefault('wb_batches',[]).append({'marker':marker,'cards':len(rows),'response_received':response is not None})
            self.checkpoint()
        for row in updates:
            row_size=len(json.dumps(row['payload'],ensure_ascii=False).encode())
            if row_size>9_500_000: self.skip('wb_card_payload_too_large',offer_id=row['offer']); continue
            if batch and (len(batch)>=100 or size+row_size>9_500_000): submit(batch); batch=[]; size=0
            batch.append(row); size+=row_size
        submit(batch)

    def load_resume_snapshots(self):
        prior=json.loads(self.state_path.read_text())
        if prior.get('no_cleanup') is not True or not isinstance(prior.get('groups'),list) or not isinstance(prior.get('mutations'),list):
            raise ValueError('Resume state missing original execution evidence')
        # Keep the original evidence even when a snapshot validation fails.
        self.state=prior
        snapshots={}
        for name,field in [('all_found_ozon_products_snapshot_20261014.json','products'),
                           ('all_found_ozon_certificates_snapshot_20261014.json','certificates'),
                           ('all_found_wb_cards_snapshot_20261014.json','cards')]:
            snapshot=json.loads((BASE/name).read_text())
            if snapshot.get('complete') is not True or not isinstance(snapshot.get(field),list):
                raise ValueError('Resume snapshot incomplete: '+name)
            checked=dt.datetime.fromisoformat(str(snapshot.get('checked_at') or '').replace('Z','+00:00'))
            if checked.tzinfo is None: raise ValueError('Resume snapshot timestamp timezone missing: '+name)
            age=(dt.datetime.now(dt.timezone.utc)-checked).total_seconds()
            if age< -60 or age>7200: raise ValueError('Resume snapshot is not fresh: '+name)
            snapshots[field]=snapshot[field]
        prior.update(pid=os.getpid(),resumed_at=now(),execute=self.execute,phase='resuming_from_fresh_snapshots')
        prior.pop('finished_at',None); prior.pop('fatal_error_type',None)
        self.state=prior
        unique={json.dumps(row,sort_keys=True,ensure_ascii=False):row for row in self.state.get('skips',[])}
        self.skip_keys=set(unique); self.state['skips']=list(unique.values())
        self.products=snapshots['products']; self.certs=snapshots['certificates']; self.cards=snapshots['cards']
        self.touched_certificate_ids={str(g['certificate_id']) for g in self.state['groups'] if g.get('certificate_id')}
        self.checkpoint()

    def pending_records(self):
        active={}
        duplicate=set()
        for p in self.products:
            if p.get('is_archived') is not False: continue
            key=(str(p.get('product_id') or p.get('id')),str(p.get('sku')))
            if key in active: duplicate.add(key)
            active[key]=p
        blocked=set(self.manifest.get('blocked_document_keys') or [])
        brandblocks=self.manifest.get('blocked_binding_brands') or {}
        cardbrands={}
        for card in self.cards: cardbrands.setdefault(card.get('vendorCode'),set()).add(str(card.get('brand') or ''))
        pending=[]
        for cert in self.certs:
            key=norm_number(cert.get('certificate_number'))
            if cert.get('bindings_failed') or key in blocked or cert.get('status_code') not in ('approved','awaiting_verification') or cert.get('accordance_type_code')!='EAEU' or cert.get('type_code') not in OZON_TO_WB_TYPE or not valid_dates(cert.get('issue_date'),cert.get('expire_date')): continue
            eligible=[]
            for binding in cert.get('live_bindings') or []:
                pair=(str(binding.get('product_id')),str(binding.get('sku')))
                p=active.get(pair)
                if pair in duplicate or not p or not p.get('offer_id') or binding.get('product_status_code')=='declined': continue
                if cardbrands.get(p['offer_id'],set()) & set(brandblocks.get(key,[])): continue
                eligible.append(binding)
            if eligible and (cert.get('status_code')=='awaiting_verification' or any(b.get('product_status_code') not in ('approved','declined') for b in eligible)):
                cert['_eligible_pending_binding_count']=sum(b.get('product_status_code') not in ('approved','declined') for b in eligible)
                pending.append(cert)
        return pending

    def run(self, poll_hours=3, resume_from_snapshots=False):
        deadline=time.monotonic()+max(0,poll_hours)*3600
        if resume_from_snapshots:
            self.load_resume_snapshots()
            self.wb_reconcile()
        else:
            self.checkpoint('initializing_all_brand_coverage')
            self.read_products(); self.read_certificates()
            self.process_groups()
            metadata={str(c['certificate_id']):c for c in self.list_certificate_metadata()}
            for cert in self.certs:
                live=metadata.get(str(cert['certificate_id']))
                if live: cert.update(live)
            self.read_wb(); self.wb_reconcile()
            # Original initial scan does not consume the moderation polling allowance.
            deadline=time.monotonic()+max(0,poll_hours)*3600
        while self.execute and time.monotonic()<deadline:
            pending=self.pending_records()
            if not pending: break
            self.state['pending_ozon_records']=len(pending); self.checkpoint('waiting_ozon_moderation')
            time.sleep(min(600,max(0,deadline-time.monotonic())))
            if time.monotonic()>=deadline: break
            metadata={str(c['certificate_id']):c for c in self.list_certificate_metadata()}
            for previous in pending:
                cid=str(previous['certificate_id']); current=metadata.get(cid)
                if current is None:
                    previous['bindings_failed']=True
                    self.skip('pending_record_disappeared',certificate_id=cid); continue
                try:
                    bindings=self.client.ozon_bindings(cid)
                    previous.update(current); previous['live_bindings']=bindings
                except Exception as exc: self.skip('pending_bindings_read_failed',certificate_id=cid,error_type=type(exc).__name__)
            self.wb_reconcile()
        pending=self.pending_records()
        self.state.update(finished_at=now(),pending_ozon_records=len(pending),
            pending_ozon_certificate_ids=[c['certificate_id'] for c in pending],
            pending_ozon_bindings=sum(c.get('_eligible_pending_binding_count',0) for c in pending))
        self.checkpoint('finished_review_pending_and_problems_skipped')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--execute',action='store_true'); parser.add_argument('--poll-hours',type=float,default=3); parser.add_argument('--resume-from-snapshots',action='store_true'); parser.add_argument('--wait-for-lock',action='store_true'); parser.add_argument('--fail-fast-if-locked',action='store_true')
    parser.add_argument('--manifest-file',type=Path); parser.add_argument('--state-file',type=Path,default=STATE); parser.add_argument('--journal-file',type=Path,default=JOURNAL); parser.add_argument('--lock-file',type=Path,default=BASE/'all_found_certificates_bulk_20261014.lock')
    args=parser.parse_args()
    for arg in ('manifest_file','state_file','journal_file','lock_file'):
        path=getattr(args,arg)
        if path is not None and not path.is_absolute(): parser.error('--'+arg.replace('_','-')+' must be an absolute path')
    with args.lock_file.open('w') as lock:
        if args.fail_fast_if_locked and not args.wait_for_lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise SystemExit('Another all-brand runner is active')
        else:
            fcntl.flock(lock,fcntl.LOCK_EX)
        from bulk_found_manifest_20261014 import build_manifest
        manifest_path=BASE/'all_found_certificates_bulk_manifest_20261014.json'
        if args.manifest_file: manifest=json.loads(args.manifest_file.read_text())
        elif args.resume_from_snapshots: manifest=json.loads(manifest_path.read_text())
        else:
            manifest=build_manifest(); atomic(manifest_path,manifest)
        runner=Runner(Client(),manifest,args.execute,args.journal_file,args.state_file)
        runner.state['manifest_file']=str(args.manifest_file or manifest_path)
        try: runner.run(args.poll_hours,args.resume_from_snapshots)
        except Exception as exc:
            runner.state['fatal_error_type']=type(exc).__name__; runner.checkpoint('stopped_read_failure_no_repeated_mutations'); raise

if __name__=='__main__': main()
