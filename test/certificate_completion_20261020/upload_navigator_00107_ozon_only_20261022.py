from __future__ import annotations
import base64, collections, datetime, hashlib, json, pathlib, sys, time
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number,wb_datetime

NUMBER='ЕАЭС RU С-RU.НВ28.В.00107/24'
TYPE='certificate_of_conformity'
ISSUE='2024-12-24'
EXPIRY='2029-12-23'
REGISTRY='https://pub.fsa.gov.ru/rss/certificate/view/3544212/baseInfo'
SOURCE=ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf'
SOURCE_SHA='f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e'
UPLOAD=HERE/'navigator_00107_certificate_ozon_upload_q75_20261022.pdf'
UPLOAD_SHA='1ae8fd5c65cc34c4ccdeaaa423f3d49a1a57c159cd803b3ddf07d90fe8acd416'
MANIFEST=HERE/'navigator_00107_certificate_ozon_upload_q75_20261022.json'
STATE=HERE/'navigator_00107_ozon_certificate_retry_20261022.json'
OFFERS=['14147-1','14148-1','14149-1','14150-1','80671-1','80672-1','80673-1','80674-1','80675-1','80677-1','80678-1']

def save(x):
 t=STATE.with_suffix('.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');t.replace(STATE)
def list_certs(c):
 out=[]
 for page in range(1,101):
  r=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {}
  rows=r.get('certificates')
  if not isinstance(rows,list):raise RuntimeError('ozon_certificate_list_invalid')
  out.extend(rows)
  if page>=int(r.get('page_count') or 0):return out
 raise RuntimeError('ozon_certificate_page_limit')
def tnved_values(items):
 vals=[]
 for a in items or []:
  if str(a.get('id'))=='22232':
   vals.extend(str(v.get('value') or '').split(' - ',1)[0].strip() for v in a.get('values') or [])
 return sorted({x for x in vals if x})
def verify_wb(c):
 wanted={'declaration':{'number':'ЕАЭС N RU Д-RU.РА11.В.90815/24','type':2,'start':'2024-12-27','end':'2029-12-25'},'certificate':{'number':NUMBER,'type':1,'start':ISSUE,'end':EXPIRY}}
 rows=[];bad=[]
 for offer in OFFERS:
  cards=c.wb_cards(offer)
  if len(cards)!=1:raise RuntimeError('wb_card_count:'+offer)
  card=cards[0]
  if str(card.get('vendorCode'))!=offer or str(card.get('brand') or '').strip().casefold() not in {'navigator','navigator group'}:
   raise RuntimeError('wb_card_identity_changed:'+offer)
  tn=[]
  for a in card.get('characteristics') or []:
   label=''.join(str(a.get('name') or '').casefold().split()).replace('ё','е')
   if 'тнвэд' in label or 'тнвед' in label:
    v=a.get('value');tn.extend(v if isinstance(v,list) else [v])
  tn=sorted({str(v).split(' - ',1)[0].strip() for v in tn if str(v).strip()})
  if tn!=['9405420012']:raise RuntimeError('wb_tnved_changed:'+offer)
  items=((card.get('documents') or {}).get('items') or []);docs={}
  for key,w in wanted.items():
   matches=[d for d in items if norm_number(d.get('number'))==norm_number(w['number']) and int(d.get('type') or 0)==w['type'] and str(d.get('startDate',''))[:10]==w['start'] and str(d.get('endDate',''))[:10]==w['end'] and d.get('isEndless') is False]
   if len(matches)!=1:raise RuntimeError('wb_doc_not_exactly_once:'+offer+':'+key)
   v=matches[0].get('verdict') or {}
   if not(v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid'):
    raise RuntimeError('wb_doc_not_valid:'+offer+':'+key)
   docs[key]=matches[0].get('verdict')
  rows.append({'offer_id':offer,'nmID':str(card.get('nmID')),'brand':card.get('brand'),'tnved':tn,'documents_valid':docs})
 return rows
def fetch_targets(c):
 products=[];attrs=[]
 for i in range(0,len(OFFERS),100):
  batch=OFFERS[i:i+100]
  products.extend(c.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or [])
  attrs.extend(c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or [])
 pmap=collections.defaultdict(list);amap=collections.defaultdict(list)
 for p in products:pmap[str(p.get('offer_id'))].append(p)
 for a in attrs:amap[str(a.get('offer_id'))].append(a)
 fresh=[]
 for offer in OFFERS:
  if len(pmap[offer])!=1 or len(amap[offer])!=1:raise RuntimeError('ozon_product_or_attrs_missing:'+offer)
  p,a=pmap[offer][0],amap[offer][0]
  t=tnved_values(a.get('attributes'))
  brands=[]
  for x in a.get('attributes') or []:
   if str(x.get('id'))=='85':brands=[str(v.get('value') or '') for v in x.get('values') or []]
  if p.get('is_archived') is not False or not t or set(t)!={'9405420012'} or 'navigator' not in str(p.get('name') or '').casefold() or any('navigator' not in b.casefold() for b in brands):
   raise RuntimeError('ozon_target_scope_changed:'+offer)
  fresh.append({'offer_id':offer,'product_id':str(p.get('product_id') or p.get('id')),'sku':str(p.get('sku')),'name':p.get('name'),'brand_values':brands,'tnved':t})
 return fresh
def main():
 if STATE.exists():raise RuntimeError('retry_state_exists_inspect_first')
 if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=SOURCE_SHA:raise RuntimeError('original_source_hash_mismatch')
 if not UPLOAD.is_file() or UPLOAD.stat().st_size>=10_000_000 or hashlib.sha256(UPLOAD.read_bytes()).hexdigest()!=UPLOAD_SHA:raise RuntimeError('upload_pdf_not_under_10mb_or_hash_mismatch')
 m=json.loads(MANIFEST.read_text())
 if m.get('source_sha256')!=SOURCE_SHA or m.get('upload_sha256')!=UPLOAD_SHA or m.get('upload_pages')!=11 or m.get('under_ozon_file_limit') is not True:raise RuntimeError('upload_manifest_mismatch')
 c=Client()
 wb=verify_wb(c)
 products=fetch_targets(c)
 matches=[x for x in list_certs(c) if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 if len(matches)>1:raise RuntimeError('ozon_duplicate_record_no_write')
 state={'started_at_utc':now(),'phase':'prewrite_complete','target_count':len(products),'wb_verified_valid_cards':len(wb),'ozon_targets':products,'wb_readback':wb,'local_source_files_deleted':False,'original_pdf_sha256':SOURCE_SHA,'upload_pdf_sha256':UPLOAD_SHA,'upload_file_bytes':UPLOAD.stat().st_size,'ozon_raw_file_limit_bytes':10_000_000,'existing_ozon_record_matches':[{k:x.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date')} for x in matches]}
 if matches:
  record=matches[0]
  if (record.get('type_code')!=TYPE or str(record.get('issue_date',''))[:10]!=ISSUE or str(record.get('expire_date',''))[:10]!=EXPIRY):raise RuntimeError('existing_ozon_record_metadata_conflict')
  state['record_reused']=True
 else:
  state['record_reused']=False
 save(state)
 if not matches:
  expiry=datetime.date.fromisoformat(EXPIRY)
  params={'name':'Сертификат соответствия № '+NUMBER,'certificate_type':TYPE.upper(),'certificate_country':'RU','accordance_type':'EAEU','number':NUMBER,'issue_date':wb_datetime(ISSUE),'expired_date':{'date':{'day':expiry.day,'month':expiry.month,'year':expiry.year}},'skus':[products[0]['sku']],'product_type':'UNKNOWN','link_to_registry':REGISTRY,'files':[{'file_content':base64.b64encode(UPLOAD.read_bytes()).decode('ascii'),'name':UPLOAD.name}]}
  body=json.dumps({'params':params},ensure_ascii=False,separators=(',',':')).encode()
  state.update({'phase':'ozon_create_started','ozon_create_request_bytes':len(body),'ozon_create_payload_sha256':hashlib.sha256(body).hexdigest()});save(state)
  try:
   response=c.call('ozon','/v2/product/certificate/create',{'params':params},mutation=True)
   state['create_response']=response;state['phase']='ozon_create_response_received'
  except Exception as e:
   state.update({'create_error_type':type(e).__name__,'create_error':str(e)[:300],'phase':'ozon_create_response_uncertain'})
  save(state)
  record=None
  for attempt in range(6):
   current=[x for x in list_certs(c) if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
   if current:break
   if attempt<5:time.sleep(2)
  if len(current)!=1:
   state.update({'phase':'no_unique_ozon_record_visible_after_create','record_count':len(current),'no_create_retry':True});save(state);print(json.dumps(state,ensure_ascii=False,indent=2));return
  record=current[0]
  if record.get('type_code')!=TYPE or str(record.get('issue_date',''))[:10]!=ISSUE or str(record.get('expire_date',''))[:10]!=EXPIRY:
   state.update({'phase':'ozon_created_record_metadata_conflict','record':record});save(state);print(json.dumps(state,ensure_ascii=False,indent=2));return
 state['record']={k:record.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date','products_count')}
 if str(record.get('status_code') or '') in {'declined','rejected','cancelled','invalid'}:
  state.update({'phase':'ozon_record_rejected_no_bind','record':record});save(state);print(json.dumps(state,ensure_ascii=False,indent=2));return
 cid=int(record['certificate_id']);expected={(x['product_id'],x['sku']) for x in products}
 bindings=c.ozon_bindings(cid);by_pair={(str(x.get('product_id')),str(x.get('sku'))):x for x in bindings}
 outside=[x for x in bindings if (str(x.get('product_id')),str(x.get('sku'))) not in expected]
 if outside:raise RuntimeError('ozon_record_has_outside_binding')
 missing=[x for x in products if (x['product_id'],x['sku']) not in by_pair]
 if missing:
  c.call('ozon','/v1/product/certificate/bind',{'certificate_id':cid,'skus':[x['sku'] for x in missing]},mutation=True)
 final=[]
 for attempt in range(6):
  final=c.ozon_bindings(cid)
  visible={(str(x.get('product_id')),str(x.get('sku'))):x for x in final}
  if expected<=set(visible):break
  if attempt<5:time.sleep(2)
 missing_pairs=sorted(expected-set(visible));statuses=collections.Counter(str(x.get('product_status_code') or 'unknown') for x in visible.values() if (str(x.get('product_id')),str(x.get('sku'))) in expected)
 state.update({'phase':'ozon_bindings_readback_complete' if not missing_pairs else 'ozon_bindings_readback_incomplete','binding_expected':len(expected),'binding_visible':len(expected)-len(missing_pairs),'binding_missing':missing_pairs,'outside_binding_count':len(outside),'binding_status_counts':dict(statuses),'binding_request_count':len(missing),'record_status':record.get('status_code'),'finished_at_utc':now(),'local_source_files_deleted':False})
 save(state)
 print(json.dumps({k:v for k,v in state.items() if k not in ('ozon_targets','wb_readback','create_response')},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
