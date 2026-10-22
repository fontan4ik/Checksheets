"""Build exact-scope manifest for the current Arlight voluntary fire-safety certificate.
Read-only. The certificate is supplementary and does not replace mandatory EAEU docs.
"""
from __future__ import annotations
import csv, hashlib, json, re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SNAP=HERE/'live_marketplaces_snapshot_final_20261020.json'
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
MASTER=ROOT/'output_to_user/certificates/document_catalog_master.csv'
OCR=HERE/'arlight_0123651_0333370_ocr_20261020.txt'
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/B93165BC4283E449AF1E139B53863098.pdf'
OUT=HERE/'arlight_0333370_exact_scope_manifest_20261020.json'
NUMBER='РОСС RU.32001.04ИБФ1.ОСП32.90090'
ISSUE='2025-12-01'; EXPIRY='2028-11-30'
ALLOWED={'9405110033','9405110039','9405420039','9405420012','9405420022','9405420032'}
SERIES={'IM','DL','LT','BR','AR','ALT','MS','LTD','MD','LGD','CL','SP','MAG','CLIP','KT','BAR','LTM','ART','SPACE','SNAP','FLEX','STINGRAY'}
TRANSLATE=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(x):
 s=re.sub(r'^(?:ЕАЭС|EAEU|EAEC|EAC)\s*','',str(x or '').strip().upper())
 s=re.sub(r'^(?:N|№)\s*','',s)
 return ''.join(c for c in s.translate(TRANSLATE) if c.isalnum())
def hashfile(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def tnv_values(card):
 out=[]
 for c in card.get('characteristics') or []:
  if 'тнвэд' in str(c.get('name') or '').casefold().replace('ё','е') or 'тнвед' in str(c.get('name') or '').casefold():
   vals=c.get('value'); vals=vals if isinstance(vals,list) else [vals]
   out.extend(str(x or '').split(' - ',1)[0].strip() for x in vals)
 return sorted(set(x for x in out if x))
def live_tnv_values(prod):
 return sorted(set(str(x).split(' - ',1)[0].strip() for x in (prod.get('tnved_values') or []) if x))
def series_in(name):
 up=str(name or '').upper()
 return sorted({s for s in SERIES if re.search(r'(?<![A-Z0-9])'+re.escape(s)+r'(?![A-Z0-9])',up)})

s=json.loads(SNAP.read_text())
if not s.get('complete') or not all(s.get(k,{}).get('complete') is True for k in ('ozon_products','ozon_certificates','wb_catalog')):
 raise RuntimeError('Incomplete live snapshot')
ocr=OCR.read_text(errors='replace')
for term in ['РОСС RU.32001.04ИБФ1.ОСП32.90090','СИСТЕМА ДОБРОВОЛЬНОЙ СЕРТИФИКАЦИИ','Серийный выпуск','30.11.2028','9405110033','9405110039','9405420039','9405420012','9405420022','9405420032','Сертификат не применяется при обязательной сертификации']:
 if term.casefold() not in ocr.casefold(): raise RuntimeError(f'PDF evidence missing: {term}')
sha=hashfile(SOURCE)
if sha!='ed5bc2b1eebb904f5a3e50c8fd70cb2ef5c6dc096c9aa0cfcdaa2134348eea95': raise RuntimeError('Local source hash differs from official catalog hash')
with ASSIGN.open(encoding='utf-8-sig',newline='') as f: rows=[r for r in csv.DictReader(f) if r.get('Номер/название документа','').strip()=='0333370']
if len(rows)!=1136 or len({r['Артикул продавца'] for r in rows})!=1136: raise RuntimeError(f'Unexpected assignment row/offer count: {len(rows)}')
with MASTER.open(encoding='utf-8-sig',newline='') as f: master=[r for r in csv.DictReader(f) if 'B93165BC4283E449AF1E139B53863098.pdf' in str(r)]
if len(master)!=1 or master[0].get('SHA256')!=sha or NUMBER not in master[0].get('Номера/названия документов',''):
 raise RuntimeError('Official manufacturer catalog/hash cross-check failed')
products=defaultdict(list)
for p in s['ozon_products']['products']:
 if p.get('is_archived') is False: products[str(p.get('offer_id') or '')].append(p)
wb=defaultdict(list)
for c in s['wb_catalog']['cards']: wb[str(c.get('vendorCode') or '')].append(c)
cert_matches=[c for c in s['ozon_certificates']['certificates'] if norm(c.get('certificate_number'))==norm(NUMBER)]
checks=Counter(); targets=[]; excluded=[]; seen=[]
for row in rows:
 offer=row['Артикул продавца']; po=products.get(offer,[]); cw=wb.get(offer,[])
 reason=None; p=po[0] if len(po)==1 else None; c=cw[0] if len(cw)==1 else None
 if row.get('Применимость')!='Подтверждено статусом покрытия': reason='source_not_confirmed'
 elif row.get('Бренд подтвержденный')!='Arlight': reason='source_brand_mismatch'
 elif len(po)!=1 or not p: reason='ozon_card_missing_or_duplicate'
 elif not str(p.get('sku') or ''): reason='ozon_sku_missing'
 elif p.get('brand_values')!=['Arlight']: reason='ozon_brand_mismatch'
 elif len(live_tnv_values(p))!=1 or not set(live_tnv_values(p))<=ALLOWED: reason='ozon_tnved_out_of_scope'
 elif not series_in(p.get('name')): reason='model_series_not_in_certificate'
 elif len(cw)!=1 or not c: reason='wb_card_missing_or_duplicate'
 elif c.get('brand')!='Arlight': reason='wb_brand_mismatch'
 elif len(tnv_values(c))!=1 or not set(tnv_values(c))<=ALLOWED: reason='wb_tnved_out_of_scope'
 if reason:
  checks[reason]+=1; excluded.append({'offer_id':offer,'reason':reason,'ozon_tnved':live_tnv_values(p) if p else [],'wb_tnved':tnv_values(c) if c else [],'series':series_in(p.get('name')) if p else []}); continue
 wb_docs=[d for d in ((c.get('documents') or {}).get('items') or []) if norm(d.get('number'))==norm(NUMBER)]
 ozon_has=[b for cert in cert_matches for b in cert.get('live_bindings') or [] if str(b.get('product_id'))==str(p.get('product_id'))]
 if wb_docs:
  checks['wb_document_already_present']+=1; seen.append({'offer_id':offer,'platform':'wb','docs':wb_docs}); continue
 if ozon_has:
  checks['ozon_document_already_present']+=1; seen.append({'offer_id':offer,'platform':'ozon','bindings':ozon_has}); continue
 targets.append({'offer_id':offer,'product_id':str(p['product_id']),'sku':str(p['sku']),'wb_nmID':str(c['nmID']),'brand':'Arlight','name':p.get('name'),'tnved':live_tnv_values(p)[0],'model_series':series_in(p.get('name')),'manufacturer_source_url':row.get('URL карточки/основания')})
 checks['ready']+=1
if cert_matches:
 raise RuntimeError(f'Existing exact Ozon records for official number {NUMBER}; reconcile instead of create: {[c.get("certificate_id") for c in cert_matches]}')
result={'checked_at':datetime.now(timezone.utc).isoformat(),'source_document':{'official_number':NUMBER,'type':'certificate_of_conformity','accordance':'NATIONAL','voluntary':True,'mandatory_compliance_substitute':False,'issue_date':ISSUE,'expire_date':EXPIRY,'serial_production':True,'source_url':'https://arlight.ru/upload/certificates/B93165BC4283E449AF1E139B53863098.pdf','local_file':str(SOURCE),'sha256':sha,'bytes':SOURCE.stat().st_size,'official_catalog_crosscheck':True},'snapshot':str(SNAP),'source_assignment_rows':len(rows),'ready_target_count':len(targets),'exclusion_counts':dict(checks),'targets':targets,'excluded':excluded,'existing_exact_ozon_records':len(cert_matches),'local_cleanup_allowed':False,'wb_review_left_pending':True,'notes':'Certificate is voluntary fire-safety certification. It covers the listed Arlight lamp series and codes only; it is supplemental and does not replace mandatory EAEU documents. Exact TN VED and series intersections only.'}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:result[k] for k in ('checked_at','source_document','source_assignment_rows','ready_target_count','exclusion_counts','existing_exact_ozon_records','local_cleanup_allowed')},ensure_ascii=False,indent=2))
for x in targets[:15]:print(x['offer_id'],x['tnved'],','.join(x['model_series']),x['wb_nmID'])
