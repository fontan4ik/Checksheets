#!/usr/bin/env python3
"""Execute one source-verified Feron group with safe Ozon and WB readback.

The shared runner validates current Ozon offer identities, brand and allowed
TN VED codes, uploads once, binds only eligible SKUs, and never mutates WB.
WB attachments are read back so existing valid/pending states are recorded.
"""
from __future__ import annotations
import argparse, collections, json, re, sys
from pathlib import Path

BASE=Path(__file__).resolve().parent
API=BASE.parent/'certificate_api_pilot_20261012'
sys.path.insert(0,'/opt/homebrew/lib/python3.14/site-packages');sys.path.insert(0,str(API))
import run_all_found_certificates_20261014 as runner_module
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import doc_key, wb_datetime

def atomic(path,value):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(path)
def suffix(value):
 m=re.search(r'(?<!\d)(\d{4,6})\s*/\s*(\d{2,4})(?!\d)',str(value or ''));return m.group(1)+'/'+m.group(2) if m else ''
def certificates(client):
 out=[]
 for page in range(1,101):
  batch=(client.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}).get('certificates')
  if not isinstance(batch,list):raise RuntimeError('Ozon certificate list incomplete')
  out+=batch
  if len(batch)<100:return out
 raise RuntimeError('Ozon certificate list exceeded pagination bound')
def bindings(client,cid):
 out=[];last=0;expected=None
 while True:
  data=(client.call('ozon','/v1/product/certificate/products/list',{'certificate_id':int(cid),'last_id':last,'limit':500}).get('result') or {})
  batch=data.get('items');count=data.get('count')
  if not isinstance(batch,list) or not isinstance(count,int):raise RuntimeError('Ozon binding readback invalid')
  if expected is None:expected=count
  elif expected!=count:raise RuntimeError('Ozon binding count changed')
  out+=batch
  if len(out)==expected:return out
  if not batch or len(out)>expected:raise RuntimeError('Ozon binding pagination incomplete')
  nxt=int(batch[-1].get('product_id') or 0)
  if nxt<=last:raise RuntimeError('Ozon binding cursor did not advance')
  last=nxt
def wb_status(card,number,doc_type,issue,expiry):
 wanted={'type':doc_type,'number':number,'startDate':wb_datetime(issue),'endDate':wb_datetime(expiry),'isEndless':False}
 docs=[x for x in ((card.get('documents') or {}).get('items') or []) if doc_key(x)==doc_key(wanted)]
 dates=any(str(x.get('startDate',''))[:10]==issue and str(x.get('endDate',''))[:10]==expiry for x in docs)
 valid=any((x.get('verdict') or {}).get('verified') is True and (x.get('verdict') or {}).get('status')==1 and (x.get('verdict') or {}).get('reason')=='valid' for x in docs)
 pending=bool(docs and dates and not valid and all((x.get('verdict') or {}).get('status') in (None,1) and (x.get('verdict') or {}).get('reason') in (None,'','valid') for x in docs))
 return {'document_visible':bool(docs),'dates_match':dates,'valid_verdict':valid,'status':'valid' if valid and dates else 'pending_review' if pending else 'missing_or_conflict','documents':docs}
def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--journal',type=Path,required=True);p.add_argument('--readback',type=Path,required=True);p.add_argument('--execute',action='store_true');a=p.parse_args()
 manifest=json.loads(a.manifest.read_text());group=manifest['groups'][0]
 prior_execute=a.state.exists() and json.loads(a.state.read_text()).get('execute') is True
 if a.execute and (prior_execute or a.journal.exists() or a.readback.exists()):raise RuntimeError('Prior execution marker exists; reconcile before retry')
 client=Client();runner=runner_module.Runner(client,manifest,execute=a.execute,journal=a.journal,state=a.state)
 runner.state['manifest_file']=str(a.manifest);runner.process_groups();state=json.loads(a.state.read_text())
 eligible=runner.validated_source_groups[0]['targets'] if runner.validated_source_groups else []
 summary={'mode':'execute' if a.execute else 'dry_run','number':group['number'],'candidate_targets':len(group['targets']),'eligible_targets':len(eligible),'eligible_offers':[x['offer_id'] for x in eligible],'group_results':state.get('groups'),'skips':state.get('skips'),'mutations':len(state.get('mutations') or []),'state_file':str(a.state)}
 if not a.execute:print(json.dumps(summary,ensure_ascii=False,indent=2));return
 matches=[x for x in certificates(client) if x.get('type_code')==group['type_code'] and suffix(x.get('certificate_number'))==suffix(group['number'])]
 if len(matches)!=1:raise RuntimeError(f'Expected one live Ozon record; found {len(matches)}')
 cert=matches[0];cid=int(cert['certificate_id']);number=str(cert.get('certificate_number') or '')
 info=(client.call('ozon','/v1/product/certificate/info',{'certificate_number':number}).get('result') or {})
 live=bindings(client,cid);byid={str(x.get('product_id')):x for x in live}
 ozon_rows=[]
 for t in eligible:
  b=byid.get(str(t['product_id']));ozon_rows.append({'offer_id':t['offer_id'],'product_id':str(t['product_id']),'sku':str(t['sku']),'visible':bool(b),'identity_matches':bool(b and str(b.get('sku'))==str(t['sku'])),'status':b.get('product_status_code') if b else None})
 if len(ozon_rows)!=len(eligible) or any(not x['visible'] or not x['identity_matches'] for x in ozon_rows):raise RuntimeError('Ozon binding readback is incomplete')
 type_for_wb={'certificate_of_conformity':1,'declaration':2}[group['type_code']]
 wb_rows=[]
 for t in group['targets']:
  cards=client.wb_cards(t['offer_id'])
  if not cards:wb_rows.append({'offer_id':t['offer_id'],'status':'no_exact_card'});continue
  if len(cards)!=1 or cards[0].get('vendorCode')!=t['offer_id'] or str(cards[0].get('brand') or '').casefold()!=str(t.get('brand') or '').casefold():raise RuntimeError(f'WB exact card identity/brand mismatch: {t["offer_id"]}')
  wb_rows.append({'offer_id':t['offer_id'],'nmID':cards[0].get('nmID'),**wb_status(cards[0],group['number'],type_for_wb,group['issue_date'][:10],group['expire_date'][:10])})
 result={'checked_at':now(),'number':group['number'],'ozon_certificate_id':cid,'ozon_certificate_status':info.get('status_code'),'ozon_targets_expected':len(eligible),'ozon_targets_visible':len(ozon_rows),'ozon_binding_status_counts':dict(collections.Counter(x['status'] for x in ozon_rows)),'ozon_bindings':ozon_rows,'source_targets_skipped':state.get('skips'),'wb_targets_checked':len(wb_rows),'wb_valid':sum(x['status']=='valid' for x in wb_rows),'wb_pending_review':sum(x['status']=='pending_review' for x in wb_rows),'wb_missing_or_conflict':[x['offer_id'] for x in wb_rows if x['status'] in ('no_exact_card','missing_or_conflict')],'wb_readback':wb_rows,'local_source_file_deleted':False,'local_source_file_retained_reason':'At least one target lacks a confirmed exact WB card and cross-platform link.'}
 atomic(a.readback,result);state.update(completion_phase='live_readback_complete',finished_at=now(),readback_file=str(a.readback));atomic(a.state,state)
 print(json.dumps(summary|{'readback_file':str(a.readback),'ozon_certificate_status':result['ozon_certificate_status'],'ozon_binding_status_counts':result['ozon_binding_status_counts'],'wb_valid':result['wb_valid'],'wb_pending_review':result['wb_pending_review'],'wb_missing_or_conflict':result['wb_missing_or_conflict']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
