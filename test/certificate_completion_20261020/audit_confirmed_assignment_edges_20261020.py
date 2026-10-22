"""Read-only join of confirmed assignment edges with current Ozon/WB records."""
from __future__ import annotations
import csv, json, re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SNAP=HERE/'live_marketplaces_snapshot_final_20261020.json'
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
OUT=HERE/'all_confirmed_source_assignments_live_20261020.json'
CSV_OUT=HERE/'all_confirmed_source_assignments_live_20261020.csv'
TRANSLATE=str.maketrans({'А':'A','В':'B','Е':'E','К':'K','М':'H','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','Ё':'E','Э':'E','Д':'D','П':'P'})
def norm(v):
 s=str(v or '').strip().upper();s=re.sub(r'^(?:ЕАЭС|EAEU|EAEC|EAC)\s*','',s);s=re.sub(r'^(?:N|№)\s*','',s);return ''.join(c for c in s.translate(TRANSLATE) if c.isalnum())
def doc_type(row):
 raw=str(row.get('Тип документа') or '').casefold(); number=str(row.get('Номер/название документа') or '')
 if 'декларац' in raw or re.search(r'\b[ДD]-[A-ZА-Я]{2}',number,re.I):return 'declaration'
 if 'сертификат' in raw or re.search(r'\b[СC]-[A-ZА-Я]{2}',number,re.I):return 'certificate_of_conformity'
 return None
def current_dates(issue,expiry):
 try: return date.fromisoformat(str(issue)[:10])<=date.today()<=date.fromisoformat(str(expiry)[:10])
 except Exception:return False
def wb_status(cards,number,typ):
 if not cards:return 'no_exact_card'
 if len(cards)!=1:return 'ambiguous_card'
 card=cards[0]; rows=[x for x in ((card.get('documents') or {}).get('items') or []) if norm(x.get('number'))==number]
 if not rows:return 'missing_document'
 expected={'certificate_of_conformity':1,'declaration':2}.get(typ)
 if expected and not any(int(x.get('type') or 0)==expected for x in rows):return 'type_conflict'
 typed=[x for x in rows if not expected or int(x.get('type') or 0)==expected]
 active=[x for x in typed if current_dates(x.get('startDate'),x.get('endDate'))]
 if not active:return 'expired_or_future'
 valid=[x for x in active if (x.get('verdict') or {}).get('verified') is True and (x.get('verdict') or {}).get('status')==1 and (x.get('verdict') or {}).get('reason')=='valid']
 if valid:return 'valid'
 if any((x.get('verdict') or {}).get('status') not in (None,1) or (x.get('verdict') or {}).get('reason') not in (None,'','valid') for x in active):return 'rejected_or_invalid'
 return 'pending_or_no_verdict'
s=json.loads(SNAP.read_text())
if not all(s.get(k,{}).get('complete') is True for k in ('ozon_products','ozon_certificates','wb_catalog')):raise RuntimeError('Incomplete live marketplace snapshot')
products=s['ozon_products']['products'];certs=s['ozon_certificates']['certificates'];cards=s['wb_catalog']['cards']
prod_by_offer=defaultdict(list)
for p in products:
 if p.get('is_archived') is False:prod_by_offer[str(p.get('offer_id') or '')].append(p)
wb_by_offer=defaultdict(list)
for c in cards:wb_by_offer[str(c.get('vendorCode') or '')].append(c)
cert_by_num=defaultdict(list)
for c in certs:cert_by_num[norm(c.get('certificate_number'))].append(c)
# Merge duplicate source rows only for the same exact seller offer + normalized document number.
source={};confirmed_values=('Подтверждено статусом покрытия','Подтверждено источником')
with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
 for row in csv.DictReader(f):
  if row.get('Применимость') not in confirmed_values:continue
  offer=str(row.get('Артикул продавца') or '').strip(); number=str(row.get('Номер/название документа') or '').strip(); key=norm(number)
  if not offer or not key:continue
  edge=source.setdefault((offer,key),{'offer_id':offer,'number':number,'type_codes':set(),'brands':set(),'applicability':set(),'files':set(),'urls':set(),'basis':set(),'row_count':0})
  edge['row_count']+=1
  typ=doc_type(row)
  if typ:edge['type_codes'].add(typ)
  for name,col in [('brands','Бренд подтвержденный'),('applicability','Применимость'),('files','Локальный файл'),('urls','URL документа'),('basis','Основание сопоставления')]:
   val=str(row.get(col) or '').strip()
   if val:edge[name].add(val)

edges=[];oz=Counter();wb=Counter();brand_totals=defaultdict(lambda:{'edges':0,'ozon':Counter(),'wb':Counter()});per_doc=defaultdict(lambda:{'brand':Counter(),'ozon':Counter(),'wb':Counter(),'offers':set(),'file_paths':set(),'urls':set(),'types':set(),'rows':0})
for (offer,key),raw in source.items():
 types=raw['type_codes'];typ=next(iter(types)) if len(types)==1 else None
 prows=prod_by_offer.get(offer,[]);p=prows[0] if len(prows)==1 else None
 records=cert_by_num.get(key,[])
 if not p:oz_state='missing_or_ambiguous_product'
 elif len(types)>1:oz_state='source_type_conflict'
 elif not records:oz_state='missing_record'
 else:
  matching=[c for c in records if not typ or c.get('type_code')==typ]
  if not matching:oz_state='record_type_conflict'
  else:
   bindings=[]
   for c in matching:
    b=next((b for b in (c.get('live_bindings') or []) if str(b.get('product_id'))==str(p.get('product_id'))),None)
    if b and str(b.get('sku'))!=str(p.get('sku')):bindings.append(('binding_identity_conflict',c,b))
    elif not current_dates(c.get('issue_date'),c.get('expire_date')):bindings.append(('expired_or_future',c,b))
    elif c.get('status_code')=='approved' and b and b.get('product_status_code')=='approved':bindings.append(('approved_link',c,b))
    elif c.get('status_code')=='approved' and not b:bindings.append(('missing_binding',c,b))
    elif c.get('status_code') in ('pending','checking','in_review','awaiting_verification') or (b and b.get('product_status_code') in ('background_check','pending','awaiting_verification')):bindings.append(('pending_review',c,b))
    elif c.get('status_code')=='declined' or (b and b.get('product_status_code')=='declined'):bindings.append(('declined',c,b))
    else:bindings.append(('record_unusable_or_unknown',c,b))
   states=[x[0] for x in bindings]
   if 'approved_link' in states:oz_state='approved_link'
   elif 'pending_review' in states:oz_state='pending_review'
   elif 'missing_binding' in states:oz_state='missing_binding'
   elif 'binding_identity_conflict' in states:oz_state='binding_identity_conflict'
   elif 'declined' in states:oz_state='declined'
   elif all(x=='expired_or_future' for x in states):oz_state='expired_or_future'
   else:oz_state='record_unusable_or_unknown'
 wb_state=wb_status(wb_by_offer.get(offer,[]),key,typ)
 brand=next(iter(raw['brands']),p.get('brand_values',['Unknown'])[0] if p and p.get('brand_values') else 'Unknown')
 row={'brand':brand,'offer_id':offer,'number':raw['number'],'normalized_number':key,'type':typ,'source_type_conflict':len(types)>1,
      'ozon_state':oz_state,'wb_state':wb_state,'ozon_product_id':p.get('product_id') if p else '',
      'ozon_sku':p.get('sku') if p else '', 'wb_nmID':wb_by_offer[offer][0].get('nmID') if len(wb_by_offer.get(offer,[]))==1 else '',
      'source_file_exists':any(Path(x).is_file() for x in raw['files']),'source_files':' ; '.join(sorted(raw['files'])),
      'source_urls':' ; '.join(sorted(raw['urls'])),'row_count':raw['row_count']}
 edges.append(row);oz[oz_state]+=1;wb[wb_state]+=1
 bt=brand_totals[brand];bt['edges']+=1;bt['ozon'][oz_state]+=1;bt['wb'][wb_state]+=1
 dg=per_doc[(key,typ)];dg['offers'].add(offer);dg['brand'][brand]+=1;dg['ozon'][oz_state]+=1;dg['wb'][wb_state]+=1;dg['file_paths'].update(raw['files']);dg['urls'].update(raw['urls']);dg['types'].update(types);dg['rows']+=raw['row_count']

with CSV_OUT.open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(edges[0]) if edges else []);writer.writeheader();writer.writerows(edges)
# Potential follow-up groups: source-confirmed, a live exact Ozon offer exists, and Ozon has no usable record.
missing=[]
for (key,typ),g in per_doc.items():
 state_counts=g['ozon'];eligible=sum(state_counts[x] for x in ('missing_record','missing_binding'))
 if eligible:
  existing_files=[x for x in sorted(g['file_paths']) if Path(x).is_file()]
  missing.append({'number_key':key,'type':typ,'brands':dict(g['brand']),'offers':len(g['offers']),'ozon_states':dict(state_counts),'wb_states':dict(g['wb']),
                  'local_files_existing':existing_files[:3],'source_urls':sorted(g['urls'])[:3]})
missing.sort(key=lambda x:(-x['offers'],x['number_key']))
report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'snapshot':str(SNAP),
 'assignment_rows_scanned':46310,'confirmed_unique_offer_document_edges':len(edges),
 'ozon_edge_states':dict(oz),'wb_edge_states':dict(wb),
 'brands':{k:{'edges':v['edges'],'ozon':dict(v['ozon']),'wb':dict(v['wb'])} for k,v in sorted(brand_totals.items())},
 'groups_with_ozon_missing_record_or_binding':missing,
 'edge_csv':str(CSV_OUT),
 'limitations':'Assignment rows are source-confirmed status rows, but a number can have date/type revisions or be only supporting to current product. Missing-record groups require source PDF, current official status, exact product scope/TN VED, and fresh preflight before upload.'}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'report':str(OUT),'edge_csv':str(CSV_OUT),'edges':len(edges),'ozon_edge_states':dict(oz),'wb_edge_states':dict(wb),'missing_group_count':len(missing),'top_missing_groups':missing[:20]},ensure_ascii=False,indent=2))
