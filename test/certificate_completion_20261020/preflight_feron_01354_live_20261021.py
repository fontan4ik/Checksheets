#!/usr/bin/env python3
"""Fresh read-only cross-platform preflight for Feron controller cert 01354/22."""
from __future__ import annotations
import collections,json,pathlib,sys
HERE=pathlib.Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client,now,digest
from reconcile_approved_ozon_docs_to_wb import norm_number
MAN=HERE/'feron_01354_manifest_20261020.json';OUT=HERE/'feron_01354_live_recheck_20261021.json'
NUMBER='ЕАЭС RU C-CN.НВ85.В.01354/22';ISSUE='2022-08-29';EXPIRY='2027-08-28';ALLOWED={'8537109800','8537109100'}
def vals(attrs,aid):
 m={str(x.get('id')):x for x in attrs.get('attributes') or []}
 return [str(v.get('value') or '').strip() for v in (m.get(str(aid)) or {}).get('values') or [] if str(v.get('value') or '').strip()]
def codes(v):return sorted({str(x).split(' - ',1)[0].strip() for x in v if str(x).strip()})
def main():
 if OUT.exists():raise RuntimeError('output_exists_inspect_first')
 manifest=json.loads(MAN.read_text());g=manifest['groups'][0];targets=g['targets'];offers=[x['offer_id'] for x in targets]
 c=Client(); products=c.call('ozon','/v3/product/info/list',{'offer_id':offers}).get('items') or []
 attrs=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':len(offers)}).get('result') or []
 if len(products)!=len(offers) or len(attrs)!=len(offers):raise RuntimeError('ozon_response_incomplete')
 pmap={str(x.get('offer_id')):x for x in products}; amap={str(x.get('offer_id')):x for x in attrs}
 certs=[]
 for page in range(1,101):
  result=c.call('ozon','/v1/product/certificate/list',{'page':page,'page_size':100}).get('result') or {};batch=result.get('certificates')
  if not isinstance(batch,list):raise RuntimeError('certificate_list_incomplete')
  certs.extend(batch)
  if len(batch)<100:break
 else:raise RuntimeError('certificate_list_page_limit')
 exact=[x for x in certs if norm_number(x.get('certificate_number'))==norm_number(NUMBER)]
 if len(exact)!=1:raise RuntimeError(f'exact_ozon_record_count_{len(exact)}')
 record=exact[0];cid=int(record['certificate_id']);bindings=c.ozon_bindings(cid)
 by_product={str(x.get('product_id')):x for x in bindings}
 oz=[]
 for t in targets:
  offer=t['offer_id'];p=pmap[offer];a=amap[offer];brand=vals(a,85);tv=vals(a,22232);cs=codes(tv);pid=str(p.get('product_id') or p.get('id') or '');sku=str(p.get('sku') or '')
  b=by_product.get(pid)
  row={'offer_id':offer,'source_article':t['source_article'],'source_title':t['source_title'],'product_id':pid,'expected_product_id':t['product_id'],'sku':sku,'expected_sku':t['sku'],'live_name':p.get('name'),'is_archived':p.get('is_archived'),'brand_values':brand,'tnved_values':tv,'tnved_codes':cs,'identity_exact':pid==t['product_id'] and sku==t['sku'],'in_fsa_tnved_scope':bool(cs) and set(cs)<=ALLOWED,'ozon_binding_visible':b is not None,'ozon_binding_sku':str(b.get('sku')) if b else None,'ozon_binding_status':b.get('product_status_code') if b else None,'ozon_binding_identity_exact':bool(b and str(b.get('sku'))==sku)}
  oz.append(row)
 wb=[]
 for t in targets:
  offer=t['offer_id'];cards=c.wb_cards(offer)
  if len(cards)>1:raise RuntimeError(f'WB_card_ambiguous_{offer}')
  if not cards:wb.append({'offer_id':offer,'card_found':False});continue
  card=cards[0];docs=(card.get('documents') or {}).get('items') or []
  exact_docs=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
  wb.append({'offer_id':offer,'card_found':True,'nmID':str(card.get('nmID')),'vendorCode':card.get('vendorCode'),'brand':card.get('brand'),'title':card.get('title'),'exact_document_count':len(exact_docs),'documents':[{'type':d.get('type'),'number':d.get('number'),'startDate':d.get('startDate'),'endDate':d.get('endDate'),'isEndless':d.get('isEndless'),'verdict':d.get('verdict')} for d in exact_docs]})
 pdf=pathlib.Path(g['source_evidence_files'][0])
 result={'checked_at_utc':now(),'read_only':True,'number':NUMBER,'fsa_record_id':3135385,'fsa_status':'active per current official registry at last check','issue_date':ISSUE,'expiry_date':EXPIRY,'allowed_tnved':sorted(ALLOWED),'ozon':{'target_count':len(targets),'products_returned':len(products),'attributes_returned':len(attrs),'certificate_record':{k:record.get(k) for k in ('certificate_id','certificate_number','type_code','status_code','issue_date','expire_date','products_count')},'binding_count':len(bindings),'binding_status_counts':dict(collections.Counter(x.get('product_status_code') for x in bindings)),'rows':oz},'wb':{'target_count':len(targets),'exact_cards_found':sum(x.get('card_found') is True for x in wb),'valid_docs':sum(any((d.get('verdict') or {}).get('verified') is True and (d.get('verdict') or {}).get('reason')=='valid' for d in x.get('documents',[])) for x in wb),'rows':wb},'source_pdf':{'path':str(pdf),'exists':pdf.is_file(),'sha256':digest(pdf) if pdf.is_file() else None}}
 tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
 print(json.dumps({'preflight':str(OUT),'checked_at_utc':result['checked_at_utc'],'ozon_record':result['ozon']['certificate_record'],'ozon_binding_status_counts':result['ozon']['binding_status_counts'],'eligible_by_current_tnved':[x['offer_id'] for x in oz if x['in_fsa_tnved_scope'] and x['identity_exact'] and x['is_archived'] is False and x['brand_values']==['Feron']],'missing_eligible_bindings':[x['offer_id'] for x in oz if x['in_fsa_tnved_scope'] and x['identity_exact'] and x['is_archived'] is False and x['brand_values']==['Feron'] and not x['ozon_binding_visible']],'wb_cards_found':result['wb']['exact_cards_found'],'wb_valid':result['wb']['valid_docs']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
