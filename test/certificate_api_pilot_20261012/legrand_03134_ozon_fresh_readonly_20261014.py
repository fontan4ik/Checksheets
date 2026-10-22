"""Fresh read-only Ozon binding check for Legrand EAC-FR.02.03134."""
from __future__ import annotations
import collections,json
from pathlib import Path
from api_client import BASE,Client,now,save
ROOT=BASE.parents[1]
PREFLIGHT=json.loads((BASE/'legrand_remaining_preflight_20261013.json').read_text())['documents']['EAC-FR.02.03134']
NUMBER=PREFLIGHT['number']; CERT_ID=int(PREFLIGHT['certificate_id']); EXPECTED={x['offer']:x for x in PREFLIGHT['targets']}

def main():
 c=Client(); offers=sorted(EXPECTED)
 body=c.call('ozon','/v3/product/info/list',{'offer_id':offers})
 products=body.get('items') or body.get('result',{}).get('items')
 if not isinstance(products,list) or len(products)!=10: raise RuntimeError('Ozon current product list incomplete')
 by_offer={str(x.get('offer_id') or ''):x for x in products}
 if set(by_offer)!=set(offers) or len(by_offer)!=10: raise RuntimeError('Ozon offers missing/duplicated')
 ab=c.call('ozon','/v4/product/info/attributes',{'filter':{'offer_id':offers},'limit':100})
 ar=ab.get('result') or ab.get('items')
 if not isinstance(ar,list) or {str(x.get('offer_id')) for x in ar}!=set(offers): raise RuntimeError('Ozon attributes incomplete')
 attrs={str(x['offer_id']):{str(a.get('id')):a for a in x.get('attributes') or []} for x in ar}
 info=c.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER})
 rec=info.get('result') or info
 recs=rec if isinstance(rec,list) else [rec]
 matches=[x for x in recs if str(x.get('certificate_id') or x.get('id') or '')==str(CERT_ID)]
 if len(matches)!=1: raise RuntimeError(f'exact Ozon cert info not unique: {len(matches)}')
 record=matches[0]
 bindings=c.ozon_bindings(CERT_ID)
 targets=[]
 for offer in offers:
  expected=EXPECTED[offer]; p=by_offer[offer]
  pid=str(p.get('id') or p.get('product_id') or ''); sku=str(p.get('sku') or '')
  av=attrs[offer]
  brand=[str(x.get('value') or '') for x in (av.get('85') or {}).get('values') or []]
  tv=[str(x.get('value') or '') for x in (av.get('22232') or {}).get('values') or []]
  codes=sorted({x.split(' - ',1)[0].strip() for x in tv if x.strip()})
  exact=[b for b in bindings if str(b.get('product_id') or '')==pid and str(b.get('sku') or '')==sku]
  targets.append({'offer_id':offer,'product_id':pid,'expected_product_id':str(expected['product_id']),'sku':sku,'expected_sku':str(expected['sku']),'is_archived':p.get('is_archived'),'name':p.get('name'),'brand_values':brand,'tnved_codes':codes,'exact_binding_rows':exact})
 result={'checked_at_utc':now(),'read_only':True,'certificate_id':CERT_ID,'certificate_number':NUMBER,'record':{k:v for k,v in record.items() if k not in {'certificate_file','file_content'}},'binding_count':len(bindings),'binding_status_counts':dict(collections.Counter(str(b.get('product_status_code') or '') for b in bindings)),'targets':targets}
 save('legrand_03134_ozon_fresh_readonly_20261014.json',result)
 print(json.dumps({'output':'legrand_03134_ozon_fresh_readonly_20261014.json','checked_at_utc':result['checked_at_utc'],'record_id':record.get('certificate_id') or record.get('id'),'record_status':record.get('status_code'),'targets':len(targets),'exact_identities':sum(t['product_id']==t['expected_product_id'] and t['sku']==t['expected_sku'] and t['is_archived'] is False for t in targets),'approved_exact_bindings':sum(len(t['exact_binding_rows'])==1 and t['exact_binding_rows'][0].get('product_status_code')=='approved' for t in targets),'brand_counts':dict(collections.Counter(b for t in targets for b in t['brand_values'])),'tnved_counts':dict(collections.Counter(code for t in targets for code in t['tnved_codes']))},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
