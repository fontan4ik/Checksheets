import copy
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import run_all_found_certificates_20261014 as runner_module
from pathlib import Path
from run_all_found_certificates_20261014 import Runner, group_error, merge_wb, valid_dates


class FakeClient:
    def __init__(self): self.mutations=0
    def call(self,*args,**kwargs):
        self.mutations+=1
        raise RuntimeError('lost reply')


class BulkTests(unittest.TestCase):
    def test_invalid_dates_are_not_lexically_accepted(self):
        self.assertFalse(valid_dates('2025-02-30','2030-01-01'))
        self.assertFalse(valid_dates('2028-01-01','2030-01-01'))
        self.assertFalse(valid_dates('2020-01-01','2021-01-01'))
        self.assertTrue(valid_dates('2020-01-01T00:00:00Z','2030-01-01'))

    def test_document_type_dates_and_hash_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'document.pdf'; file.write_bytes(b'real source')
            group={'number':'RU TEST','type_code':'declaration','accordance_type':'EAEU','issue_date':'2020-01-01','expire_date':'2030-01-01','targets':[{'offer_id':'x'}],'upload_file':{'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}}
            self.assertIsNone(group_error(group))
            group['type_code']='unknown'; self.assertEqual(group_error(group),'unknown_type')
            group['type_code']='declaration'; group['upload_file']['sha256']='bad'
            self.assertEqual(group_error(group),'file_hash_mismatch')

    def test_merge_preserves_card_and_prior_documents(self):
        prior={'id':12,'type':1,'number':'OTHER','startDate':'2020-01-01','endDate':'2030-01-01','isEndless':False}
        card={'nmID':1,'vendorCode':'exact','brand':'Brand','dimensions':{'length':5},'sizes':[{'skus':['a'],'techSize':'0'}],'characteristics':[{'id':1,'value':['old']}],'documents':{'items':[prior],'excludeDocuments':True},'readOnlyField':9}
        before=copy.deepcopy(card)
        doc={'type':2,'number':'NEW','startDate':'2020-01-01T00:00:00Z','endDate':'2030-01-01T00:00:00Z','isEndless':False}
        output=merge_wb(card,[doc])
        with self.assertRaises(ValueError): merge_wb(card,[doc,{**doc,'endDate':'2031-01-01T00:00:00Z'}])
        self.assertEqual(card,before)
        for key in ('brand','dimensions','sizes','characteristics'): self.assertEqual(output[key],card[key])
        self.assertEqual(output['documents']['items'][0],prior)
        self.assertNotIn('readOnlyField',output)
        self.assertIsNone(merge_wb({**card,'documents':output['documents']},[doc]))
        with self.assertRaises(ValueError): merge_wb(card,[{**doc,'number':'OTHER'}])
        with self.assertRaises(ValueError): merge_wb(card,[{**prior,'endDate':'2031-01-01'}])

    def test_uncertain_write_never_repeats_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            journal=Path(temp)/'journal.jsonl'; state=Path(temp)/'state.json'
            client=FakeClient()
            runner=Runner(client,{},True,journal,state)
            self.assertIsNone(runner.mutation('stable-key','ozon','/write',{'x':1}))
            self.assertEqual(client.mutations,1)
            restarted=Runner(client,{},True,journal,state)
            self.assertIsNone(restarted.mutation('stable-key','ozon','/write',{'x':1}))
            self.assertEqual(client.mutations,1)
            self.assertEqual(restarted.state['skips'][0]['reason'],'previous_mutation_do_not_repeat')

    def test_full_all_brand_run_binds_missing_pair_and_updates_only_gap(self):
        number='ЕАЭС N RU Д-CN.TEST.12345/26'
        desired={'type':2,'number':number,'startDate':'2020-01-01T00:00:00Z','endDate':'2030-01-01T00:00:00Z','isEndless':False}
        products=[{'id':n,'offer_id':f'p{n}','sku':str(100+n),'is_archived':False} for n in (1,2)]
        cert={'certificate_id':7,'certificate_number':number,'type_code':'declaration','accordance_type_code':'EAEU','issue_date':'2020-01-01','expire_date':'2030-01-01','status_code':'approved'}
        cardbase={'brand':'BrandA','dimensions':{'length':5},'sizes':[{'techSize':'0','skus':['barcode']}],'characteristics':[{'id':5,'value':['original']}],'title':'Exact title','description':'Exact description'}
        cards={f'p{n}':{**copy.deepcopy(cardbase),'nmID':n,'vendorCode':f'p{n}','documents':{'items':[copy.deepcopy(desired)] if n==1 else [],'excludeDocuments':False}} for n in (1,2)}
        before=copy.deepcopy(cards)
        class IntegrationClient:
            def __init__(self):
                self.bindings=[{'product_id':1,'sku':'101','product_status_code':'approved'}]
                self.mutations=[]
            def ozon_bindings(self,cid):
                self_outer.assertEqual(str(cid),'7')
                return copy.deepcopy(self.bindings)
            def wb_cards(self,offer): return [copy.deepcopy(cards[offer])]
            def call(self,platform,path,payload,mutation=False):
                if mutation: self.mutations.append((platform,path,copy.deepcopy(payload)))
                if path=='/v3/product/list': return {'result':{'items':copy.deepcopy(products),'last_id':''}}
                if path=='/v3/product/info/list':
                    offers=set(payload.get('offer_id') or ['p1','p2'])
                    return {'items':copy.deepcopy([p for p in products if p['offer_id'] in offers])}
                if path=='/v4/product/info/attributes':
                    return {'result':[{'offer_id':offer,'attributes':[{'id':85,'values':[{'value':'BrandA'}]},{'id':22232,'values':[{'value':'1234567890 - scope'}]}]} for offer in payload['filter']['offer_id']]}
                if path=='/v1/product/certificate/list': return {'result':{'certificates':[copy.deepcopy(cert)],'page_count':1}}
                if path=='/v1/product/certificate/bind':
                    self_outer.assertEqual(payload,{'certificate_id':7,'skus':['102']})
                    self.bindings.append({'product_id':2,'sku':'102','product_status_code':'approved'})
                    return {'result':True}
                if path=='/content/v2/get/cards/list': return {'cards':copy.deepcopy(list(cards.values())),'cursor':{'total':2}}
                if path=='/content/v2/cards/error/list': return {'data':{'items':[],'cursor':{'next':False}}}
                if path=='/content/v2/cards/update':
                    self_outer.assertEqual(len(payload),1)
                    self_outer.assertEqual(payload[0]['vendorCode'],'p2')
                    cards['p2'].update(copy.deepcopy(payload[0]))
                    return {'error':False}
                raise AssertionError('Unexpected API '+path)
        self_outer=self
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); file=base/'source.pdf'; file.write_bytes(b'known exact certificate')
            manifest={'groups':[{'number':number,'type_code':'declaration','accordance_type':'EAEU','country':'RU','issue_date':'2020-01-01','expire_date':'2030-01-01','allowed_tnved':['1234567890'],'upload_file':{'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()},'targets':[{'offer_id':f'p{n}','product_id':str(n),'sku':str(100+n),'brand':'BrandA'} for n in (1,2)]}],'coverage':{'brands':['BrandA']}}
            client=IntegrationClient(); runner=Runner(client,manifest,True,base/'journal.jsonl',base/'state.json')
            with patch.object(runner_module,'BASE',base): runner.run(poll_hours=0)
            self.assertEqual([path for _,path,_ in client.mutations],['/v1/product/certificate/bind','/content/v2/cards/update'])
            self.assertEqual(len(client.bindings),2)
            self.assertEqual(cards['p1'],before['p1'])
            for key,value in before['p2'].items():
                if key!='documents': self.assertEqual(cards['p2'][key],value)
            self.assertEqual(cards['p2']['documents']['items'],[desired])
            self.assertEqual(runner.state['wb_accepted_cards'],1)
            self.assertEqual(runner.state['wb_readback_counts']['visible_review_left_pending'],1)
            self.assertEqual(runner.state['groups'][0]['status'],'processed')

    def test_verified_source_updates_wb_independently_while_ozon_pending(self):
        number='ЕАЭС N RU Д-CN.TEST.12345/26'
        desired={'type':2,'number':number,'startDate':'2020-01-01T00:00:00Z','endDate':'2030-01-01T00:00:00Z','isEndless':False}
        products=[{'id':n,'offer_id':f'p{n}','sku':str(100+n),'is_archived':False} for n in (1,2)]
        cert={'certificate_id':7,'certificate_number':number,'type_code':'declaration','accordance_type_code':'EAEU','issue_date':'2020-01-01','expire_date':'2030-01-01','status_code':'awaiting_verification'}
        cardbase={'brand':'BrandA','dimensions':{'length':5},'sizes':[{'techSize':'0','skus':['barcode']}],'characteristics':[{'id':5,'value':['original']},{'id':22232,'name':'ТНВЭД','value':['1234567890']}],'title':'Exact title','description':'Exact description'}
        cards={f'p{n}':{**copy.deepcopy(cardbase),'nmID':n,'vendorCode':f'p{n}','documents':{'items':[copy.deepcopy(desired)] if n==1 else [],'excludeDocuments':False}} for n in (1,2)}
        before=copy.deepcopy(cards)
        class IntegrationClient:
            def __init__(self):
                self.bindings=[]; self.created=False
                self.mutations=[]
            def ozon_bindings(self,cid):
                self_outer.assertEqual(str(cid),'7')
                return copy.deepcopy(self.bindings)
            def wb_cards(self,offer): return [copy.deepcopy(cards[offer])]
            def call(self,platform,path,payload,mutation=False):
                if mutation: self.mutations.append((platform,path,copy.deepcopy(payload)))
                if path=='/v3/product/list': return {'result':{'items':copy.deepcopy(products),'last_id':''}}
                if path=='/v3/product/info/list':
                    offers=set(payload.get('offer_id') or ['p1','p2'])
                    return {'items':copy.deepcopy([p for p in products if p['offer_id'] in offers])}
                if path=='/v4/product/info/attributes':
                    return {'result':[{'offer_id':offer,'attributes':[{'id':85,'values':[{'value':'BrandA'}]},{'id':22232,'values':[{'value':'1234567890 - scope'}]}]} for offer in payload['filter']['offer_id']]}
                if path=='/v1/product/certificate/list': return {'result':{'certificates':[copy.deepcopy(cert)] if self.created else [],'page_count':1}}
                if path=='/v2/product/certificate/create':
                    self.created=True
                    self.bindings.append({'product_id':1,'sku':'101','product_status_code':'awaiting_verification'})
                    return {'certificate_id':7,'status':'COMPLETED','params':[{'state':'VALID'}]}
                if path=='/v1/product/certificate/bind':
                    self_outer.assertEqual(payload,{'certificate_id':7,'skus':['102']})
                    self.bindings.append({'product_id':2,'sku':'102','product_status_code':'awaiting_verification'})
                    return {'result':True}
                if path=='/content/v2/get/cards/list': return {'cards':copy.deepcopy(list(cards.values())),'cursor':{'total':2}}
                if path=='/content/v2/cards/error/list': return {'data':{'items':[],'cursor':{'next':False}}}
                if path=='/content/v2/cards/update':
                    self_outer.assertEqual(len(payload),1)
                    self_outer.assertEqual(payload[0]['vendorCode'],'p2')
                    cards['p2'].update(copy.deepcopy(payload[0]))
                    return {'error':False}
                raise AssertionError('Unexpected API '+path)
        self_outer=self
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); file=base/'source.pdf'; file.write_bytes(b'known exact certificate')
            manifest={'groups':[{'number':number,'type_code':'declaration','accordance_type':'EAEU','country':'RU','issue_date':'2020-01-01','expire_date':'2030-01-01','allowed_tnved':['1234567890'],'source_evidence_verified':True,'upload_file':{'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()},'targets':[{'offer_id':f'p{n}','product_id':str(n),'sku':str(100+n),'brand':'BrandA'} for n in (1,2)]}],'coverage':{'brands':['BrandA']}}
            client=IntegrationClient(); runner=Runner(client,manifest,True,base/'journal.jsonl',base/'state.json')
            with patch.object(runner_module,'BASE',base): runner.run(poll_hours=0)
            self.assertEqual([path for _,path,_ in client.mutations],['/v2/product/certificate/create','/v1/product/certificate/bind','/content/v2/cards/update'])
            self.assertEqual(len(client.bindings),2)
            self.assertEqual(cards['p1'],before['p1'])
            for key,value in before['p2'].items():
                if key!='documents': self.assertEqual(cards['p2'][key],value)
            self.assertEqual(cards['p2']['documents']['items'],[desired])
            self.assertEqual(runner.state['wb_accepted_cards'],1)
            self.assertEqual(runner.state['wb_readback_counts']['visible_review_left_pending'],1)
            self.assertEqual(runner.state['groups'][0]['status'],'processed')
            self.assertEqual(runner.state['validated_independent_source_groups'],1)
            self.assertEqual(runner.state['pending_ozon_records'],1)
            self.assertEqual(runner.state['pending_ozon_bindings'],2)

    def test_resume_loads_fresh_snapshots_preserves_state_and_never_replays_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); state=base/'state.json'
            original={'started_at':'original-start','groups':[{'number':'old','status':'processed'}], 'mutations':[{'key':'original-write','phase':'response'}],'skips':[{'reason':'same'},{'reason':'same'}], 'no_cleanup':True,'phase':'waiting','coverage':{'brands':['BrandA']}}
            state.write_text(__import__('json').dumps(original))
            for name,field in [('all_found_ozon_products_snapshot_20261014.json','products'),('all_found_ozon_certificates_snapshot_20261014.json','certificates'),('all_found_wb_cards_snapshot_20261014.json','cards')]:
                (base/name).write_text(__import__('json').dumps({'complete':True,'checked_at':runner_module.now(),field:[]}))
            runner=Runner(FakeClient(),{},True,base/'journal',state)
            with patch.object(runner_module,'BASE',base), patch.object(runner,'wb_reconcile') as reconcile, patch.object(runner,'process_groups',side_effect=AssertionError('groups replayed')), patch.object(runner,'read_products',side_effect=AssertionError('catalog replayed')):
                runner.run(poll_hours=0,resume_from_snapshots=True)
            reconcile.assert_called_once()
            self.assertEqual(runner.state['started_at'],'original-start')
            self.assertEqual(runner.state['groups'],original['groups'])
            self.assertEqual(runner.state['mutations'],original['mutations'])
            self.assertIn('resumed_at',runner.state); self.assertIn('finished_at',runner.state)
            self.assertEqual(runner.state['pending_ozon_records'],0)
            runner.skip('same'); runner.skip('same')
            self.assertEqual(len(runner.state['skips']),1)
            snapshot=base/'all_found_wb_cards_snapshot_20261014.json'
            snapshot.write_text(__import__('json').dumps({'complete':True,'checked_at':'2020-01-01T00:00:00Z','cards':[]}))
            with patch.object(runner_module,'BASE',base),self.assertRaises(ValueError): runner.load_resume_snapshots()

    def test_pending_filter_only_valid_active_exact_in_scope_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            runner=Runner(FakeClient(),{'blocked_document_keys':['BLOCKED'],'blocked_binding_brands':{'BRANDBLOCK':['Feron']}},False,Path(temp)/'j',Path(temp)/'s')
            runner.products=[{'product_id':'1','sku':'101','offer_id':'current','is_archived':False},{'product_id':'2','sku':'102','offer_id':'archived','is_archived':True}]
            runner.cards=[{'vendorCode':'current','brand':'Feron'}]
            base={'certificate_id':1,'certificate_number':'VALID','status_code':'approved','type_code':'declaration','accordance_type_code':'EAEU','issue_date':'2020-01-01','expire_date':'2030-01-01','live_bindings':[{'product_id':1,'sku':101,'product_status_code':'awaiting_verification'},{'product_id':2,'sku':102,'product_status_code':'awaiting_verification'},{'product_id':1,'sku':999,'product_status_code':'awaiting_verification'}]}
            runner.certs=[base,{**base,'certificate_id':2,'status_code':'declined'},{**base,'certificate_id':3,'expire_date':'2021-01-01'},{**base,'certificate_id':4,'accordance_type_code':'GOST'},{**base,'certificate_id':5,'type_code':'support'},{**base,'certificate_id':6,'certificate_number':'BLOCKED'},{**base,'certificate_id':7,'certificate_number':'BRANDBLOCK'},{**base,'certificate_id':8,'live_bindings':[{'product_id':1,'sku':999,'product_status_code':'awaiting_verification'}]}]
            pending=runner.pending_records()
            self.assertEqual([c['certificate_id'] for c in pending],[1])
            self.assertEqual(pending[0]['_eligible_pending_binding_count'],1)
            runner.skip('duplicate',offer_id='a'); runner.skip('duplicate',offer_id='a')
            self.assertEqual(len(runner.state['skips']),1)

    def test_wb_cursor_overlap_ignores_characteristic_order_but_not_document_verdict(self):
        first={'nmID':1,'vendorCode':'x','brand':'BrandA','characteristics':[{'id':2,'value':['b']},{'id':1,'value':['a']}],'documents':{'items':[{'type':2,'number':'EXACT','validation':{'status':1,'verified':True}}]}}
        shuffled=copy.deepcopy(first); shuffled['characteristics'].reverse()
        conflict=copy.deepcopy(shuffled); conflict['documents']['items'][0]['validation']['status']=2
        rows,duplicates=runner_module.deduplicate_equivalent_wb_rows([first,shuffled,conflict])
        self.assertEqual(duplicates,1)
        self.assertEqual(rows,[first,conflict])
        repeated_char=copy.deepcopy(first); repeated_char['characteristics'].append(copy.deepcopy(first['characteristics'][0]))
        rows,duplicates=runner_module.deduplicate_equivalent_wb_rows([first,repeated_char])
        self.assertEqual(duplicates,0); self.assertEqual(len(rows),2)

    def test_brand_spacing_case_only_and_wb_scope_fail_closed(self):
        self.assertEqual(runner_module.brand_key(' IN HOME '),runner_module.brand_key('InHome'))
        self.assertEqual(runner_module.brand_key('IEK'),runner_module.brand_key('Iek'))
        target={'brand':'Gauss'}; group={'allowed_tnved':['1234567890']}
        card={'brand':'gauss','characteristics':[{'name':'ТН ВЭД','value':['1234567890 - text']}]}
        self.assertIsNone(runner_module.wb_scope_error(card,group,target))
        self.assertEqual(runner_module.wb_scope_error({**card,'characteristics':[]},group,target),'wb_source_tnved_unconfirmed')
        self.assertEqual(runner_module.wb_scope_error({**card,'brand':'Other'},group,target),'wb_source_brand_mismatch')

    def test_dry_run_does_not_send_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            client=FakeClient(); runner=Runner(client,{},False,Path(temp)/'j',Path(temp)/'s')
            runner.mutation('k','ozon','/write',{})
            self.assertEqual(client.mutations,0)

if __name__=='__main__': unittest.main()
