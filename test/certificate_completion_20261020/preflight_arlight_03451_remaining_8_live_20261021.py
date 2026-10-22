from __future__ import annotations
import collections,csv,json,pathlib,re,sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
API=ROOT/'test/certificate_api_pilot_20261012';sys.path.insert(0,str(API))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number,copy_documents
SOURCE=ROOT/'output_to_user/certificates/group_1/documents/arlight/772DD20BAEF0AD4FA297663655BFAC3A.pdf'
INITIAL=HERE/'arlight_03451_preflight_live_20261021.json'
BLANK=HERE/'arlight_03451_wb_blank_tnved_preflight_20261021.json'
ASSIGN=HERE/'all_confirmed_source_assignments_live_20261021.csv'
OUT=HERE/'arlight_03451_remaining_8_live_preflight_20261021.json'
NUMBER='ЕАЭС RU С-HK.НА46.В.03451/22';CERT_ID='5925989';TNVED='8504408300';EXPECTED_SHA='22f5bd0657cf8c55754b3bd0d73d102de1b9520d6c167242555ae63349398add'
MODEL_RE=re.compile(r'\bAR(?:PJ|PV|J|V)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b',re.I)
def attrs(row,i):
 d={str(x.get('id')):x for x in row.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (d.get(str(i)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def wb_tnved(card):
 out=[]
 for c in card.get('characteristics') or []:
  name=''.join(str(c.get('name') or '').casefold().split()).replace('ё','е')
  if 'тнвэд' not in name and 'тнвед' not in name:continue
  raw=c.get('value');raw=raw if isinstance(raw,list) else [raw]
  out.extend(str(v or '').split(' - ',1)[0].strip() for v in raw if v)
 return sorted(set(out))
def bars_ozon(p):
 x=p.get('barcodes') or p.get('barcode') or []
 return sorted({str(v) for v in (x if isinstance(x,list) else [x]) if v})
def bars_wb(c):
 return sorted({str(s) for size in c.get('sizes') or [] for s in size.get('skus') or [] if s})
def main():
 if OUT.exists():raise RuntimeError('preflight_output_exists')
 if digest(SOURCE)!=EXPECTED_SHA:raise RuntimeError('source_pdf_hash_changed')
 b=json.loads(BLANK.read_text()); init=json.loads(INITIAL.read_text())
 remaining=[x for x in b['cards'] if x.get('reason') in {'ozon_wb_model_not_exactly_matched','live_card_missing_or_ambiguous'}]
 if len(remaining)!=8:raise RuntimeError('unexpected_remaining_count')
 with ASSIGN.open(encoding='utf-8-sig',newline='') as f: allrows=list(csv.DictReader(f))
 assigned={r['offer_id']:r for r in allrows if SOURCE.name in str(r.get('source_files') or '')}
 if len(assigned)!=462:raise RuntimeError('source_assignment_set_changed')
 targets=[]
 for r in remaining:
  a=assigned.get(r['offer_id'])
  if not a:raise RuntimeError('missing_source_assignment:'+r['offer_id'])
  targets.append({'offer_id':r['offer_id'],'product_id':str(a['ozon_product_id']),'sku':str(a['ozon_sku']),'assigned_nmID':str(a['wb_nmID']),'prior_reason':r['reason'],'prior_row':r})
 client=Client(); ids=sorted({t['product_id'] for t in targets}); details={}
 for start in range(0,len(ids),100):
  batch=ids[start:start+100]; rows=client.call('ozon','/v3/product/info/list',{'product_id':[int(x) for x in batch]}).get('items')
  if not isinstance(rows,list):raise RuntimeError('ozon_live_products_missing')
  for p in rows:
   pid=str(p.get('product_id') or p.get('id') or '')
   if pid in details or pid not in batch:raise RuntimeError('ozon_product_identity_duplicate')
   details[pid]=p
 attrs_map={}
 offers=[t['offer_id'] for t in targets]
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]; rows=client.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result')
  if not isinstance(rows,list):raise RuntimeError('ozon_attributes_missing')
  for a in rows:attrs_map[str(a.get('offer_id'))]=a
 bindings=client.ozon_bindings(int(CERT_ID)); byprod={str(x.get('product_id')):x for x in bindings}
 info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
 if str(info.get('certificate_id'))!=CERT_ID or info.get('status_code')!='approved':raise RuntimeError('ozon_certificate_not_approved')
 result=[]
 for t in targets:
  p=details[t['product_id']]; a=attrs_map[t['offer_id']]; brand=attrs(a,85); codes=sorted({v.split(' - ',1)[0].strip() for v in attrs(a,22232)})
  ob=byprod.get(t['product_id']);binding=bool(ob and str(ob.get('sku'))==t['sku'] and str(ob.get('product_status_code'))=='approved')
  name=str(p.get('name') or ''); ozmodels=sorted(set(x.upper() for x in MODEL_RE.findall(name)))
  cards=client.wb_cards(t['offer_id']); exact=[c for c in cards if str(c.get('nmID'))==t['assigned_nmID'] and str(c.get('vendorCode'))==t['offer_id']]
  if len(exact)!=1:
   result.append({**t,'ozon_name':name,'ozon_brand':brand,'ozon_tnved':codes,'ozon_model_codes':ozmodels,'ozon_barcodes':bars_ozon(p),'ozon_binding_approved':binding,'wb_returned_card_count':len(cards),'wb_assigned_nmID_matches':len(exact),'eligible':False,'reason':'assigned_nmID_missing_or_ambiguous'});continue
  c=exact[0];wbmodels=sorted(set(x.upper() for x in MODEL_RE.findall(str(c.get('title') or '')))); oset=set(ozmodels); wset=set(wbmodels)
  normalized_oz={x.replace('-MAG-ORIENT-','-MAG-') for x in ozmodels}
  model_ok=bool(oset & wset or normalized_oz & wset)
  wbbar=bars_wb(c);ozbar=bars_ozon(p);barcode_match=bool(set(wbbar)&set(ozbar))
  docs=copy_documents(c); same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
  identity=str(c.get('vendorCode'))==t['offer_id'] and str(c.get('nmID'))==t['assigned_nmID']
  tn=wb_tnved(c);tn_ok=tn==[]
  brandok=str(c.get('brand') or '').strip().casefold()=='arlight'
  eligible=bool(binding and p.get('is_archived') is False and brand==['Arlight'] and codes==[TNVED] and identity and brandok and tn_ok and not same and (model_ok or barcode_match))
  reason='eligible_by_barcode_model_and_exact_source_identity' if eligible else ('no_matching_model_or_barcode' if not(model_ok or barcode_match) else 'scope_or_identity_changed')
  result.append({**t,'ozon_name':name,'ozon_brand':brand,'ozon_tnved':codes,'ozon_model_codes':ozmodels,'ozon_barcodes':ozbar,'ozon_binding_approved':binding,'wb_returned_card_count':len(cards),'wb_assigned_nmID_matches':len(exact),'wb_nmID':str(c.get('nmID')),'wb_brand':c.get('brand'),'wb_title':c.get('title'),'wb_tnved':tn,'wb_model_codes':wbmodels,'wb_barcodes':wbbar,'model_code_match':model_ok,'barcode_match':barcode_match,'matching_document_count':len(same),'current_documents':[{'type':d.get('type'),'number':d.get('number'),'startDate':d.get('startDate'),'endDate':d.get('endDate')} for d in docs],'eligible':eligible,'reason':reason})
 out={'checked_at':now(),'read_only':True,'number':NUMBER,'certificate_id':CERT_ID,'fsa_record_id':3008102,'source_pdf_sha256':digest(SOURCE),'target_count':len(targets),'eligible_count':sum(r['eligible'] for r in result),'reason_counts':dict(collections.Counter(r['reason'] for r in result)),'targets':result,'write_performed':False,'local_file_deleted':False}
 tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2));tmp.replace(OUT)
 print(json.dumps({k:out[k] for k in ('checked_at','target_count','eligible_count','reason_counts')},ensure_ascii=False,indent=2))
 for x in result:print(json.dumps({k:x.get(k) for k in ('offer_id','assigned_nmID','wb_nmID','wb_title','ozon_name','wb_model_codes','ozon_model_codes','model_code_match','barcode_match','eligible','reason','wb_returned_card_count','wb_assigned_nmID_matches')},ensure_ascii=False))
if __name__=='__main__':main()
