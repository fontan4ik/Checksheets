#!/usr/bin/env python3
"""Fresh Ozon and latest complete-WB-snapshot reconciliation for 41382/26."""
from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number
PRE=ROOT/'test/certificate_api_pilot_20261012/arlight_41382_ozon_preflight_scoped_v2_20261012.json'
WB=HERE/'live_marketplaces_snapshot_complete_20261021.json'
PDF=ROOT/'output_to_user/certificates/group_1/documents/arlight/F1AD317FA132F2448DFFCC8233E3D0C0.pdf'
OUT=HERE/'arlight_41382_crossplatform_readback_live_20261021.json'
NUMBER='ЕАЭС N RU Д-RU.РА08.В.41382/26';ISSUE='2026-09-16';EXPIRY='2031-09-15';CID='5625289';ALLOWED={'9405110013','9405110033','9405110039','9405420039'}
def vals(a,aid):
 m={str(x.get('id')):x for x in a.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (m.get(str(aid)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def code_set(v):return sorted({x.split(' - ',1)[0].strip() for x in v if x.strip()})
def main():
 if OUT.exists():raise RuntimeError('output_exists_inspect_before_retry')
 pre=json.loads(PRE.read_text());targets=[x for x in pre.get('targets',[]) if x.get('tnved_in_scope') is True]
 if len(targets)!=339:raise RuntimeError(f'expected_339_scope_targets_got_{len(targets)}')
 c=Client();offers=sorted(str(x['offer_id']) for x in targets);products=[];attrs=[]
 for start in range(0,len(offers),100):
  batch=offers[start:start+100]
  ps=c.call('ozon','/v3/product/info/list',{'offer_id':batch}).get('items') or []
  ats=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':batch},'limit':len(batch)}).get('result') or []
  products.extend(ps);attrs.extend(ats)
 if len(products)!=len(offers) or len(attrs)!=len(offers):raise RuntimeError('Ozon current products/attributes incomplete')
 pmap={str(x.get('offer_id')):x for x in products};amap={str(x.get('offer_id')):x for x in attrs}
 if set(pmap)!=set(offers) or set(amap)!=set(offers):raise RuntimeError('Ozon offer identity set changed')
 certs=[]
 for page in range(1,101):
  res=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {};batch=res.get('certificates')
  if not isinstance(batch,list):raise RuntimeError('Ozon certificate pagination incomplete')
  certs.extend(batch)
  if len(batch)<100:break
 else:raise RuntimeError('Ozon certificate page limit')
 exact=[x for x in certs if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 if len(exact)!=1 or str(exact[0].get('certificate_id'))!=CID:raise RuntimeError('exact Ozon certificate missing, duplicated, or ID changed')
 rec=exact[0];info=c.call('ozon','/v1/product/certificate/info',{'certificate_number':rec['certificate_number']}).get('result') or {}
 bindings=c.ozon_bindings(int(CID));byid={str(x.get('product_id')):x for x in bindings}
 oz=[]
 for t in targets:
  offer=str(t['offer_id']);p=pmap[offer];a=amap[offer];pid=str(p.get('product_id') or p.get('id') or '');sku=str(p.get('sku') or '')
  brand=vals(a,85);tn=vals(a,22232);codes=code_set(tn);b=byid.get(pid)
  row={'offer_id':offer,'product_id':pid,'expected_product_id':str(t['product_id']),'sku':sku,'expected_sku':str(t['sku']),'identity_exact':pid==str(t['product_id']) and sku==str(t['sku']),'active':p.get('is_archived') is False,'brand_values':brand,'brand_exact':brand==['Arlight'],'tnved_codes':codes,'tnved_in_fsa_scope':bool(codes) and set(codes)<=ALLOWED,'binding_visible':b is not None,'binding_sku':str(b.get('sku')) if b else None,'binding_identity_exact':bool(b and str(b.get('sku'))==sku),'binding_status':b.get('product_status_code') if b else None}
  oz.append(row)
 wbdata=json.loads(WB.read_text());catalog=wbdata.get('wb_catalog') or {}
 if wbdata.get('complete') is not True or catalog.get('complete') is not True:raise RuntimeError('WB latest full snapshot incomplete')
 byoffer=collections.defaultdict(list)
 for card in catalog.get('cards') or []:
  if str(card.get('vendorCode') or '') in set(offers):byoffer[str(card.get('vendorCode'))].append(card)
 wr=[]
 for t in targets:
  offer=str(t['offer_id']);matches=byoffer.get(offer,[])
  if len(matches)>1:raise RuntimeError(f'WB duplicate exact card for {offer}')
  if not matches:wr.append({'offer_id':offer,'card_found':False});continue
  card=matches[0];docs=((card.get('documents') or {}).get('items') or [])
  exactdocs=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
  exactmeta=[d for d in exactdocs if d.get('type')==2 and str(d.get('startDate',''))[:10]==ISSUE and str(d.get('endDate',''))[:10]==EXPIRY]
  verdicts=[d.get('verdict') or {} for d in exactmeta]
  wr.append({'offer_id':offer,'card_found':True,'nmID':str(card.get('nmID')),'brand':card.get('brand'),'title':card.get('title'),'exact_number_rows':len(exactdocs),'exact_metadata_rows':len(exactmeta),'valid_verdict':any(v.get('verified') is True and v.get('reason')=='valid' for v in verdicts),'pending_verdict':bool(exactmeta) and not any(v.get('verified') is True and v.get('reason')=='valid' for v in verdicts),'verdicts':verdicts})
 pdfhash=digest(PDF) if PDF.is_file() else None
 result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'fsa_registry_url':'https://pub.fsa.gov.ru/rds/declaration/view/21895502/product','fsa_record_id':21895502,'fsa_status':'current FSA UI verified separately during this turn','issue_date':ISSUE,'expiry_date':EXPIRY,'allowed_tnved':sorted(ALLOWED),'source_pdf':{'path':str(PDF),'exists':PDF.is_file(),'expected_sha256':'f21eee1e430f86bbef6f7570767243bf27dfe3fe7b7648e58ff7a1b87b04e193','actual_sha256':pdfhash,'hash_exact':pdfhash=='f21eee1e430f86bbef6f7570767243bf27dfe3fe7b7648e58ff7a1b87b04e193'},'ozon':{'certificate_id':int(CID),'certificate_status':info.get('status_code'),'certificate_info':info,'target_count':len(targets),'binding_count':len(bindings),'binding_status_counts':dict(collections.Counter(x.get('product_status_code') for x in bindings)),'exact_target_binding_count':sum(x['binding_visible'] and x['binding_identity_exact'] for x in oz),'identity_mismatch_count':sum(not x['identity_exact'] or not x['binding_identity_exact'] for x in oz),'scope_mismatch_count':sum(not x['tnved_in_fsa_scope'] for x in oz),'rows':oz},'wildberries':{'source_snapshot_checked_at':catalog.get('checked_at'),'target_count':len(targets),'exact_cards_found':sum(x.get('card_found') is True for x in wr),'exact_document_cards':sum(x.get('exact_metadata_rows',0)==1 for x in wr),'valid_document_cards':sum(x.get('valid_verdict') is True for x in wr),'pending_or_no_verdict_cards':sum(x.get('pending_verdict') is True for x in wr),'rows':wr},'source_pdf_deleted':False}
 tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
 print(json.dumps({'readback':str(OUT),'checked_at_utc':result['checked_at_utc'],'ozon_status':info.get('status_code'),'ozon_binding_count':len(bindings),'ozon_binding_status_counts':result['ozon']['binding_status_counts'],'ozon_exact_target_bindings':result['ozon']['exact_target_binding_count'],'ozon_scope_mismatches':result['ozon']['scope_mismatch_count'],'wb_source_snapshot_at':catalog.get('checked_at'),'wb_target_cards':result['wildberries']['exact_cards_found'],'wb_exact_document_cards':result['wildberries']['exact_document_cards'],'wb_valid':result['wildberries']['valid_document_cards'],'wb_pending':result['wildberries']['pending_or_no_verdict_cards'],'source_pdf_hash_exact':result['source_pdf']['hash_exact']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
