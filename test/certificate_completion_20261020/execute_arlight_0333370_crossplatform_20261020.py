"""Upload the source-verified Arlight voluntary fire-safety certificate to Ozon/WB.
Dry-run by default. It applies only to live exact model/TN VED matches, leaves WB
review to the platform, records every write, and never deletes local source files.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012'
sys.path.insert(0,str(API))
import run_all_found_certificates_20261014 as runner_module
from api_client import Client, now, digest
from reconcile_approved_ozon_docs_to_wb import norm_number, doc_key, wb_datetime, copy_documents, comparable_card

MANIFEST=HERE/'arlight_0333370_exact_scope_manifest_20261020.json'
DRY_STATE=HERE/'arlight_0333370_dry_run_20261020.json'
STATE=HERE/'arlight_0333370_execution_state_20261020.json'
JOURNAL=HERE/'arlight_0333370_mutation_journal_20261020.jsonl'
NUMBER='РОСС RU.32001.04ИБФ1.ОСП32.90090'
ISSUE='2025-12-01'; EXPIRY='2028-11-30'
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/B93165BC4283E449AF1E139B53863098.pdf'
ALLOWED={'9405110033','9405110039','9405420039','9405420012','9405420022','9405420032'}
SERIES={'IM','DL','LT','BR','AR','ALT','MS','LTD','MD','LGD','CL','SP','MAG','CLIP','KT','BAR','LTM','ART','SPACE','SNAP','FLEX','STINGRAY'}

def save(path:Path,data:dict):
 tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)); tmp.replace(path)
def logline(row):
 with JOURNAL.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n'); f.flush()
def series_in(name):
 up=str(name or '').upper(); return sorted({s for s in SERIES if re.search(r'(?<![A-Z0-9])'+re.escape(s)+r'(?![A-Z0-9])',up)})
def attr_values(row, attr_id):
 attrs={str(a.get('id')):a for a in row.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (attrs.get(str(attr_id)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def tnved_codes(values): return sorted({str(v).split(' - ',1)[0].strip() for v in values if str(v).strip()})
def card_tnved(card):
 out=[]
 for item in card.get('characteristics') or []:
  name=str(item.get('name') or '').casefold().replace('ё','е')
  if 'тнвэд' in name or 'тнвед' in name:
   vals=item.get('value'); vals=vals if isinstance(vals,list) else [vals]
   out.extend(str(v).split(' - ',1)[0].strip() for v in vals if v)
 return sorted(set(out))
def wb_doc(number): return {'type':1,'number':number,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
def info_exact(client):
 payload={'certificate_number':NUMBER}
 response=client.http.post('https://api-seller.ozon.ru/v1/product/certificate/info',
     data=json.dumps(payload,ensure_ascii=False).encode(),headers=client.ozon_headers,timeout=(15,60))
 try: body=response.json()
 except ValueError: body={'non_json':True}
 return {'http_status':response.status_code,'body':body}
def load_exact_metadata(client):
 helper=runner_module.Runner(client,{'groups':[]},execute=False,journal=HERE/'metadata_verify_only.jsonl',state=HERE/'metadata_verify_only_state.json')
 return helper.list_certificate_metadata()
def fresh_ozon_targets(client,targets):
 infos={}; attrs={}; failures=[]
 offers=[x['offer_id'] for x in targets]
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]
  data=client.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []
  by=defaultdict(list)
  for x in data: by[str(x.get('offer_id') or '')].append(x)
  for offer in batch:
   if len(by.get(offer,[]))==1: infos[offer]=by[offer][0]
   else: failures.append({'offer_id':offer,'reason':'product_info_missing_or_duplicate'})
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]
  data=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':100}).get('result') or []
  by=defaultdict(list)
  for x in data: by[str(x.get('offer_id') or '')].append(x)
  for offer in batch:
   if len(by.get(offer,[]))==1: attrs[offer]=by[offer][0]
   else: failures.append({'offer_id':offer,'reason':'attributes_missing_or_duplicate'})
 live=[]
 for t in targets:
  offer=t['offer_id']; p=infos.get(offer); a=attrs.get(offer)
  if not p or not a: continue
  live_id=str(p.get('id') or p.get('product_id') or '')
  live_sku=str(p.get('sku') or '')
  brands=attr_values(a,85); codes=tnved_codes(attr_values(a,22232))
  why=None
  if live_id!=str(t['product_id']) or live_sku!=str(t['sku']) or p.get('is_archived') is not False: why='identity_or_archive_changed'
  elif brands!=['Arlight']: why='ozon_brand_changed'
  elif not codes or not set(codes)<=ALLOWED: why='ozon_tnved_out_of_scope'
  elif not series_in(p.get('name')): why='live_model_series_not_in_scope'
  if why: failures.append({'offer_id':offer,'reason':why,'live_id':live_id,'live_sku':live_sku,'brand':brands,'tnved':codes,'name':p.get('name')}); continue
  live.append({**t,'name':p.get('name'),'tnved':codes[0],'model_series':series_in(p.get('name'))})
 return live,failures

def main():
 parser=argparse.ArgumentParser(); parser.add_argument('--execute',action='store_true'); args=parser.parse_args()
 manifest=json.loads(MANIFEST.read_text()); targets=manifest['targets']
 if manifest.get('source_document',{}).get('official_number')!=NUMBER or len(targets)!=591: raise RuntimeError('Manifest is unexpected or changed')
 if digest(SOURCE)!=manifest['source_document']['sha256']: raise RuntimeError('Source hash changed')
 if args.execute and (STATE.exists() or JOURNAL.exists()): raise RuntimeError('Execution journal already exists; reconcile live state before another write')
 client=Client(); live,failures=fresh_ozon_targets(client,targets)
 if not live: raise RuntimeError('No live exact-scope Ozon products remain')
 metadata=load_exact_metadata(client)
 matches=[c for c in metadata if norm_number(c.get('certificate_number'))==norm_number(NUMBER)]
 direct=info_exact(client)
 if matches: raise RuntimeError(f'Exact Ozon certificate record already exists: {[x.get("certificate_id") for x in matches]}')
 if direct['http_status']!=404 or not isinstance(direct.get('body'),dict) or direct['body'].get('code')!=5:
  raise RuntimeError(f'Ozon direct exact-number absence was not confirmed: {direct}')
 plan={'checked_at':now(),'execute':args.execute,'number':NUMBER,'type_code':'certificate_of_conformity','accordance_type':'NATIONAL','issue_date':ISSUE,'expire_date':EXPIRY,'source_sha256':digest(SOURCE),'official_record_count':len(matches),'exact_info_absence':direct,'manifest_target_count':len(targets),'fresh_live_ozon_target_count':len(live),'live_preflight_failures':failures,'live_targets':live,'wb_plan_source_snapshot':manifest['snapshot'],'wb_snapshot_unique_cards_and_exact_tnved':True,'wb_review_left_pending':True,'local_files_deleted':False}
 if not args.execute:
  save(DRY_STATE,plan); print(json.dumps({k:plan[k] for k in ('execute','number','type_code','accordance_type','manifest_target_count','fresh_live_ozon_target_count','official_record_count','exact_info_absence','live_preflight_failures','wb_review_left_pending','local_files_deleted')},ensure_ascii=False,indent=2)); return
 state={**plan,'phase':'ozon_create_prepared','started_at':now(),'ozon_batches':[],'wb_batches':[],'wb_results':[],'cleanup_performed':False}
 save(STATE,state)
 end=datetime.strptime(EXPIRY,'%Y-%m-%d').date()
 params={'name':'Сертификат соответствия (добровольная пожарная безопасность) № '+NUMBER,
  'certificate_type':'CERTIFICATE_OF_CONFORMITY','certificate_country':'RU','accordance_type':'NATIONAL','number':NUMBER,
  'issue_date':ISSUE+'T00:00:00Z','expired_date':{'date':{'day':end.day,'month':end.month,'year':end.year}},
  'skus':[str(live[0]['sku'])],'product_type':'UNKNOWN',
  'files':[{'file_content':base64.b64encode(SOURCE.read_bytes()).decode('ascii'),'name':SOURCE.name}]}
 req={'params':params}; size=len(json.dumps(req,ensure_ascii=False,separators=(',',':')).encode())
 if size>9_500_000: raise RuntimeError('Ozon create request too large')
 create_key='ozon:create:'+norm_number(NUMBER)
 logline({'key':create_key,'phase':'prepared','at':now(),'endpoint':'/v2/product/certificate/create','sha256':hashlib.sha256(json.dumps(req,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'bytes':size})
 state.update({'phase':'ozon_create_sent','create_request_bytes':size,'seed_offer_id':live[0]['offer_id'],'seed_sku':live[0]['sku']}); save(STATE,state)
 try: created=client.call('ozon','/v2/product/certificate/create',req,mutation=True)
 except Exception as exc:
  state.update({'phase':'ozon_create_uncertain','error_type':type(exc).__name__,'updated_at':now()}); save(STATE,state); raise RuntimeError('Ozon create is uncertain; reconcile by exact number before any retry') from None
 logline({'key':create_key,'phase':'response','at':now(),'response':created})
 states=[x.get('state') for x in created.get('params',[]) if isinstance(x,dict)]
 if not created.get('certificate_id') or created.get('status')!='COMPLETED' or not states or set(states)!={'VALID'}:
  state.update({'phase':'ozon_create_response_invalid','create_response':created,'updated_at':now()}); save(STATE,state); raise RuntimeError('Ozon did not validate all certificate fields')
 cert_id=int(created['certificate_id']); state.update({'certificate_id':cert_id,'phase':'ozon_created_response_valid','create_response':created,'updated_at':now()}); save(STATE,state)
 records=load_exact_metadata(client); exact=[c for c in records if norm_number(c.get('certificate_number'))==norm_number(NUMBER)]
 info=info_exact(client)
 if len(exact)!=1 or int(exact[0].get('certificate_id',-1))!=cert_id or info.get('http_status')!=200:
  state.update({'phase':'ozon_record_not_uniquely_visible','matching_records':exact,'info':info,'updated_at':now()}); save(STATE,state); raise RuntimeError('Created Ozon certificate is not uniquely visible')
 doc=info['body'].get('result') or {}
 if (int(doc.get('certificate_id',-1))!=cert_id or norm_number(doc.get('certificate_number'))!=norm_number(NUMBER)
  or doc.get('type_code')!='certificate_of_conformity' or str(doc.get('accordance_type_code','')).casefold() not in {'national','gost'}
  or str(doc.get('issue_date',''))[:10]!=ISSUE or str(doc.get('expire_date',''))[:10]!=EXPIRY
  or doc.get('status_code') not in {'approved','pending','checking','in_review','awaiting_verification'}):
  state.update({'phase':'ozon_document_metadata_conflict','info':info,'updated_at':now()}); save(STATE,state); raise RuntimeError('Created Ozon metadata conflicts with the verified source')
 state.update({'certificate_info':doc,'phase':'ozon_record_verified','updated_at':now()}); save(STATE,state)
 bindings=client.ozon_bindings(cert_id); bypid=defaultdict(list)
 for b in bindings:bypid[str(b.get('product_id'))].append(b)
 candidates=[]
 for t in live:
  existing=bypid.get(str(t['product_id']),[])
  if len(existing)>1 or (existing and str(existing[0].get('sku'))!=str(t['sku'])):
   state.update({'phase':'ozon_binding_identity_conflict','offer_id':t['offer_id'],'existing':existing,'updated_at':now()});save(STATE,state);raise RuntimeError('Ozon binding identity conflict; stop')
  if existing and existing[0].get('product_status_code')=='declined':
   state.setdefault('ozon_skipped_declined',[]).append(t['offer_id']); continue
  if not existing:candidates.append(t)
 for i in range(0,len(candidates),500):
  batch=candidates[i:i+500]; skus=sorted(str(x['sku']) for x in batch)
  key='ozon:bind:'+str(cert_id)+':'+hashlib.sha256(','.join(skus).encode()).hexdigest()
  logline({'key':key,'phase':'prepared','at':now(),'endpoint':'/v1/product/certificate/bind','sku_count':len(skus)})
  state.update({'phase':'ozon_bind_sent','updated_at':now(),'ozon_batches':state['ozon_batches']+[{'key':key,'sku_count':len(skus),'first_sku':skus[0],'last_sku':skus[-1]}]});save(STATE,state)
  try: response=client.call('ozon','/v1/product/certificate/bind',{'certificate_id':cert_id,'skus':skus},mutation=True)
  except Exception as exc:
   state.update({'phase':'ozon_bind_uncertain','error_type':type(exc).__name__,'updated_at':now()});save(STATE,state);raise RuntimeError('Ozon bind is uncertain; reconcile before any retry') from None
  logline({'key':key,'phase':'response','at':now(),'response':response})
  if response.get('result') is not True:
   state.update({'phase':'ozon_bind_rejected','response':response,'updated_at':now()});save(STATE,state);raise RuntimeError('Ozon rejected certificate bindings')
 bindings=client.ozon_bindings(cert_id); bypid=defaultdict(list)
 for b in bindings:bypid[str(b.get('product_id'))].append(b)
 verified=[]; missed=[]; conflicts=[]; statuses=Counter()
 for t in live:
  bs=bypid.get(str(t['product_id']),[])
  if len(bs)!=1 or str(bs[0].get('sku'))!=str(t['sku']):missed.append(t['offer_id']);continue
  statuses[str(bs[0].get('product_status_code'))]+=1
  verified.append(t)
 if conflicts or not verified:
  state.update({'phase':'ozon_binding_readback_failed','missing_offers':missed,'product_status_counts':dict(statuses),'updated_at':now()});save(STATE,state);raise RuntimeError('Ozon exact bindings did not read back')
 state.update({'phase':'ozon_bindings_verified','ozon_binding_count':len(bindings),'verified_target_pairs':len(verified),'missing_after_bind':missed,'ozon_binding_status_counts':dict(statuses),'updated_at':now()});save(STATE,state)
 # Apply only target cards with a visible exact Ozon binding. Each WB batch gets exact pre-write reads and readbacks.
 desired=wb_doc(NUMBER); all_wb=Counter(); confirmed=[]
 for bstart in range(0,len(verified),100):
  batch_targets=verified[bstart:bstart+100]; prepared=[]
  for idx,t in enumerate(batch_targets,1):
   try: cards=client.wb_cards(t['offer_id'])
   except Exception as exc:
    all_wb['live_read_error']+=1; state.setdefault('wb_skips',[]).append({'offer_id':t['offer_id'],'reason':'live_read_'+type(exc).__name__}); continue
   exact_cards=[c for c in cards if c.get('vendorCode')==t['offer_id']]
   if len(exact_cards)!=1 or str(exact_cards[0].get('nmID'))!=str(t['wb_nmID']):
    all_wb['identity_changed_or_duplicate']+=1;state.setdefault('wb_skips',[]).append({'offer_id':t['offer_id'],'reason':'identity_changed_or_duplicate'});continue
   card=exact_cards[0]
   if card.get('brand')!='Arlight' or not card_tnved(card) or not set(card_tnved(card))<=ALLOWED:
    all_wb['brand_or_tnved_changed']+=1;state.setdefault('wb_skips',[]).append({'offer_id':t['offer_id'],'reason':'brand_or_tnved_changed'});continue
   same=[d for d in copy_documents(card) if norm_number(d.get('number'))==norm_number(NUMBER)]
   if same:
    if all(doc_key(d)==doc_key(desired) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY for d in same):
     all_wb['already_exact']+=1;confirmed.append(t);continue
    all_wb['existing_type_or_date_conflict']+=1;state.setdefault('wb_skips',[]).append({'offer_id':t['offer_id'],'reason':'existing_type_or_date_conflict'});continue
   try: payload=runner_module.merge_wb(card,[desired])
   except Exception:
    all_wb['merge_conflict']+=1;state.setdefault('wb_skips',[]).append({'offer_id':t['offer_id'],'reason':'merge_conflict'});continue
   if payload is None:
    all_wb['already_exact']+=1;confirmed.append(t);continue
   key='wb:'+str(card['nmID'])+':'+str(doc_key(desired))
   prepared.append({'target':t,'before':card,'payload':payload,'key':key})
  if not prepared:
   state.update({'phase':'wb_batch_no_mutations','wb_preflight_counts':dict(all_wb),'updated_at':now()});save(STATE,state);print(f'WB group {bstart//100+1}: no writes; counts={dict(all_wb)}',flush=True);continue
  payload=[x['payload'] for x in prepared]
  marker=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  if JOURNAL.exists():
   used={json.loads(line).get('key') for line in JOURNAL.read_text().splitlines() if line.strip()}
   if any(x['key'] in used for x in prepared): raise RuntimeError('WB prior mutation marker exists; reconcile before repeat')
  for x in prepared:logline({'key':x['key'],'phase':'prepared','at':now(),'endpoint':'/content/v2/cards/update','batch_marker':marker})
  state.update({'phase':'wb_batch_sent','updated_at':now(),'current_wb_batch':bstart//100+1,'wb_preflight_counts':dict(all_wb),'wb_batch_cards':len(prepared)});save(STATE,state)
  try: response=client.call('wb','/content/v2/cards/update',payload,mutation=True)
  except Exception as exc:
   # Outcome is uncertain; read every target in this batch and never replay automatically.
   state.update({'phase':'wb_batch_uncertain','error_type':type(exc).__name__,'updated_at':now()});save(STATE,state)
   response=None
  if response is not None and response.get('error') is not False:
   state.update({'phase':'wb_batch_rejected','response':response,'updated_at':now()});save(STATE,state);raise RuntimeError('WB rejected the certificate batch')
  readback=[]
  for x in prepared:
   t=x['target']
   try:
    fresh=client.wb_cards(t['offer_id']); found=[c for c in fresh if c.get('vendorCode')==t['offer_id'] and str(c.get('nmID'))==str(t['wb_nmID'])]
    visible=len(found)==1 and any(doc_key(d)==doc_key(desired) and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY for d in copy_documents(found[0]))
    preserved=len(found)==1 and comparable_card(found[0])==comparable_card(x['before'])
    verdict='visible_review_pending' if visible and preserved else 'readback_failed_or_changed'
    all_wb[verdict]+=1
    if visible and preserved:confirmed.append(t)
    readback.append({'offer_id':t['offer_id'],'nmID':t['wb_nmID'],'document_visible':visible,'unrelated_card_fields_preserved':preserved,'verdict':verdict,
      'document_verdict':next((d.get('verdict') for d in copy_documents(found[0]) if norm_number(d.get('number'))==norm_number(NUMBER)),None) if len(found)==1 else None})
   except Exception as exc:
    all_wb['readback_error']+=1;readback.append({'offer_id':t['offer_id'],'readback_error':type(exc).__name__})
  state['wb_batches'].append({'index':bstart//100+1,'accepted':response is not None and response.get('error') is False,'marker':marker,'sent_cards':len(prepared),'readback':readback,'readback_counts':dict(Counter(x['verdict'] for x in readback))})
  state.update({'phase':'wb_batch_readback_complete','wb_confirmed_count':len(confirmed),'wb_readback_counts':dict(all_wb),'updated_at':now()});save(STATE,state)
  print(f'WB batch {bstart//100+1}: sent={len(prepared)} confirmed_total={len(confirmed)} readback={dict(Counter(x["verdict"] for x in readback))}',flush=True)
 state.update({'phase':'complete_with_pending_review','finished_at':now(),'ozon_certificate_status':doc.get('status_code'),'ozon_binding_status_counts':dict(statuses),'ozon_confirmed_pairs':len(verified),'wb_confirmed_cards':len(confirmed),'wb_readback_counts':dict(all_wb),'wb_review_left_pending':True,'local_files_deleted':False,'local_cleanup_allowed':False})
 save(STATE,state)
 print(json.dumps({k:state[k] for k in ('phase','number','certificate_id','ozon_certificate_status','ozon_confirmed_pairs','ozon_binding_status_counts','wb_confirmed_cards','wb_readback_counts','wb_review_left_pending','local_files_deleted')},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
