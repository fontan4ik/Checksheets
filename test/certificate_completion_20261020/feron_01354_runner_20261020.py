#!/usr/bin/env python3
"""Run the source-verified Feron 01354/22 group through the proven Ozon runner.

WB attachments are read-only here: existing cards are checked, while offers
without a card remain skipped. No source file cleanup is performed.
"""
from __future__ import annotations
import argparse, collections, json, re, sys
from pathlib import Path

BASE=Path(__file__).resolve().parent
API=BASE.parent/'certificate_api_pilot_20261012'
FERON=Path('/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron')
BOOK=FERON/'Сопоставление_артикулов_и_файлов_документов.xlsx'
PDF=FERON/'00_Оригиналы_файлов'/'Сертификат__01354_Контроллеры_управления_осветительным_оборудованием,_тм_Feron,_серия_LD_1__d827db4ec0.pdf'
NUMBER='ЕАЭС RU C-CN.НВ85.В.01354/22'
FSA='https://pub.fsa.gov.ru/rss/certificate/view/3135385/product'
ISSUE='2022-08-29'; EXPIRY='2027-08-28'
MANIFEST=BASE/'feron_01354_manifest_20261020.json'
STATE=BASE/'feron_01354_execution_state_20261020.json'
DRY_STATE=BASE/'feron_01354_dry_run_state_20261020.json'
JOURNAL=BASE/'feron_01354_mutation_journal_20261020.jsonl'
READBACK=BASE/'feron_01354_live_readback_20261020.json'
sys.path.insert(0,'/opt/homebrew/lib/python3.14/site-packages');sys.path.insert(0,str(API))
import run_all_found_certificates_20261014 as runner_module
from api_client import Client,digest,now
from reconcile_approved_ozon_docs_to_wb import doc_key,wb_datetime

def atomic(path,value):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(path)
def suffix(v):
 m=re.search(r'(?<!\d)(\d{4,6})\s*/\s*(\d{2,4})(?!\d)',str(v or ''));return m.group(1)+'/'+m.group(2) if m else ''
def list_certs(c):
 out=[]
 for p in range(1,101):
  b=(c.call('ozon','/v1/product/certificate/list',{'page':p,'page_size':100}).get('result') or {}).get('certificates')
  if not isinstance(b,list):raise RuntimeError('Ozon certificate list incomplete')
  out+=b
  if len(b)<100:return out
 raise RuntimeError('Ozon certificate list exceeded pagination limit')
def bindings(c,cid):
 out=[];last=0;expected=None
 while True:
  r=(c.call('ozon','/v1/product/certificate/products/list',{'certificate_id':int(cid),'last_id':last,'limit':500}).get('result') or {})
  batch=r.get('items');count=r.get('count')
  if not isinstance(batch,list) or not isinstance(count,int):raise RuntimeError('Ozon binding readback invalid')
  if expected is None:expected=count
  elif expected!=count:raise RuntimeError('Ozon binding count changed')
  out+=batch
  if len(out)==expected:return out
  if not batch or len(out)>expected:raise RuntimeError('Ozon binding readback incomplete')
  nxt=int(batch[-1].get('product_id') or 0)
  if nxt<=last:raise RuntimeError('Ozon binding cursor repeated')
  last=nxt
def build_manifest():
 import openpyxl
 if not BOOK.is_file() or not PDF.is_file():raise RuntimeError('Feron workbook/PDF missing')
 wb=openpyxl.load_workbook(BOOK,read_only=True,data_only=True);targets=[]
 for r in wb['Артикул-файл'].iter_rows(min_row=6,values_only=True):
  if suffix(r[6])!='01354/22':continue
  if '2027-08-28' not in str(r[12] or ''):raise RuntimeError(f'Feron workbook date mismatch for {r[0]}')
  if 'LD' not in str(r[2] or '').upper():raise RuntimeError(f'No LD model in workbook target {r[0]}')
  targets.append({'offer_id':str(r[0]),'product_id':str(r[3]),'sku':str(r[4]),'brand':'Feron','source_article':str(r[1]),'source_title':str(r[2]),'source_tnved':'8537109800/8537109100'})
 if len(targets)!=10 or len({x['offer_id'] for x in targets})!=10:raise RuntimeError(f'Expected ten 01354/22 targets; got {len(targets)}')
 if not PDF.read_bytes().startswith(b'%PDF-') or PDF.stat().st_size>9_500_000:raise RuntimeError('Source PDF invalid or too large')
 manifest={'created_at':now(),'source':'Live FSA certificate 3135385, product tab; current status valid through 2027-08-28','fsa_url':FSA,'groups':[{'number':NUMBER,'type_code':'certificate_of_conformity','accordance_type':'EAEU','country':'RU','issue_date':ISSUE,'expire_date':EXPIRY,'allowed_tnved':['8537109800','8537109100'],'source_evidence_verified':True,'source_evidence_files':[str(PDF)],'source_url':FSA,'link_to_registry':FSA.replace('/product',''),'upload_file':{'path':str(PDF),'sha256':digest(PDF)},'targets':targets,'wb_mutation':False}],'candidate_count':len(targets),'local_file_cleanup':False}
 atomic(MANIFEST,manifest);return manifest
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
 prior_execute=(STATE.exists() and json.loads(STATE.read_text()).get('execute') is True)
 if a.execute and (prior_execute or JOURNAL.exists() or READBACK.exists()):raise RuntimeError('Prior execution marker exists; reconcile before retry')
 manifest=build_manifest();c=Client();state_path=STATE if a.execute else DRY_STATE
 runner=runner_module.Runner(c,manifest,execute=a.execute,journal=JOURNAL,state=state_path)
 runner.state['manifest_file']=str(MANIFEST);runner.process_groups();state=json.loads(state_path.read_text())
 eligible=(runner.validated_source_groups[0]['targets'] if runner.validated_source_groups else [])
 summary={'mode':'execute' if a.execute else 'dry_run','candidate_targets':len(manifest['groups'][0]['targets']),'ozon_eligible_targets':len(eligible),'eligible_offers':[x['offer_id'] for x in eligible],'group_results':state.get('groups'),'skips':state.get('skips'),'mutations':len(state.get('mutations') or []),'state_file':str(state_path)}
 if not a.execute:print(json.dumps(summary,ensure_ascii=False,indent=2));return
 recs=[x for x in list_certs(c) if x.get('type_code')=='certificate_of_conformity' and suffix(x.get('certificate_number'))=='01354/22']
 if len(recs)!=1:raise RuntimeError(f'Expected one Ozon 01354/22 record after run; found {len(recs)}')
 cert=recs[0];cid=int(cert['certificate_id']);lookup=str(cert.get('certificate_number') or '')
 info=(c.call('ozon','/v1/product/certificate/info',{'certificate_number':lookup}).get('result') or {})
 live=bindings(c,cid);byid={str(x.get('product_id')):x for x in live}
 target_rows=[]
 for t in eligible:
  b=byid.get(t['product_id']);target_rows.append({'offer_id':t['offer_id'],'product_id':t['product_id'],'sku':t['sku'],'visible':bool(b),'identity_matches':bool(b and str(b.get('sku'))==t['sku']),'status':b.get('product_status_code') if b else None})
 wb_rows=[]
 for t in manifest['groups'][0]['targets']:
  cards=c.wb_cards(t['offer_id'])
  if not cards:wb_rows.append({'offer_id':t['offer_id'],'status':'no_exact_card'});continue
  if len(cards)!=1 or cards[0].get('vendorCode')!=t['offer_id'] or str(cards[0].get('brand') or '').casefold()!='feron':raise RuntimeError(f'WB target identity/brand conflict for {t["offer_id"]}')
  wanted={'type':1,'number':NUMBER,'startDate':wb_datetime(ISSUE),'endDate':wb_datetime(EXPIRY),'isEndless':False}
  docs=[x for x in (cards[0].get('documents') or {}).get('items',[]) if doc_key(x)==doc_key(wanted)]
  dates=any(str(x.get('startDate',''))[:10]==ISSUE and str(x.get('endDate',''))[:10]==EXPIRY for x in docs)
  valid=any((x.get('verdict') or {}).get('verified') is True and (x.get('verdict') or {}).get('reason')=='valid' for x in docs)
  wb_rows.append({'offer_id':t['offer_id'],'nmID':cards[0].get('nmID'),'document_visible':bool(docs),'dates_match':dates,'valid_verdict':valid,'status':'valid' if valid and dates else 'pending_review' if docs and dates else 'missing'})
 result={'checked_at':now(),'number':NUMBER,'ozon_certificate_id':cid,'ozon_certificate_status':info.get('status_code'),'ozon_targets_expected':len(target_rows),'ozon_targets_visible':sum(x['visible'] for x in target_rows),'ozon_binding_status_counts':dict(collections.Counter(x['status'] for x in target_rows)),'ozon_bindings':target_rows,'wb_cards_checked':len(wb_rows),'wb_valid':sum(x['status']=='valid' for x in wb_rows),'wb_pending_review':sum(x['status']=='pending_review' for x in wb_rows),'wb_missing_or_no_card':[x['offer_id'] for x in wb_rows if x['status'] in ('missing','no_exact_card')],'wb_card_readback':wb_rows,'source_pdf_deleted':False,'source_pdf_retained_reason':'Three target offers do not have exact WB cards; do not delete local source.'}
 if result['ozon_targets_visible']!=len(target_rows) or any(not x['identity_matches'] for x in target_rows):raise RuntimeError('Ozon target readback incomplete')
 atomic(READBACK,result);state.update(completion_phase='ozon_and_wb_readback_complete',finished_at=now(),readback_file=str(READBACK));atomic(STATE,state)
 print(json.dumps(summary|{'readback':READBACK.name,'ozon_targets_visible':result['ozon_targets_visible'],'ozon_status_counts':result['ozon_binding_status_counts'],'wb_valid':result['wb_valid'],'wb_pending_review':result['wb_pending_review'],'wb_no_card_or_missing':result['wb_missing_or_no_card']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
