from __future__ import annotations
import json
from collections import Counter
from datetime import date,datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
SNAP=HERE/'live_marketplaces_snapshot_resume_20261024.json'
OUT=HERE/'completion_live_summary_20261024.json'
def current(d):return (d or '')[:10] if isinstance(d,str) else ''
def main():
 s=json.loads(SNAP.read_text())
 if not all(s.get(k,{}).get('complete') is True for k in ('ozon_products','ozon_certificates','wb_catalog')):raise RuntimeError('Need complete current Ozon products/docs and WB catalog')
 products=s['ozon_products']['products'];certs=s['ozon_certificates']['certificates'];cards=s['wb_catalog']['cards'];today=date.today().isoformat()
 products_by_sku={str(p.get('sku')):p for p in products if p.get('sku')}
 covered=set();binding_status=Counter();
 for c in certs:
  binding_status[str(c.get('status_code') or 'unknown')]+=0
  if c.get('status_code')!='approved' or current(c.get('issue_date'))>today or current(c.get('expire_date'))<today:continue
  for b in c.get('live_bindings') or []:
   p=products_by_sku.get(str(b.get('sku') or ''))
   if b.get('product_status_code')=='approved' and p and str(p.get('product_id'))==str(b.get('product_id')) and p.get('is_archived') is False:
    covered.add(str(p['product_id']))
 for c in certs:binding_status[str(c.get('status_code') or 'unknown')]+=int(c.get('live_binding_count') or 0)
 wb=Counter();
 for card in cards:
  docs=((card.get('documents') or {}).get('items') or [])
  def v(d):return d.get('verdict') or {}
  valid=any(v(x).get('verified') is True and v(x).get('status')==1 and v(x).get('reason')=='valid' for x in docs)
  pending=any(v(x).get('status') in (None,1) and v(x).get('reason') in (None,'','valid') and not(v(x).get('verified') is True and v(x).get('status')==1 and v(x).get('reason')=='valid') for x in docs)
  rejected=any(v(x).get('status') not in (None,1) or v(x).get('reason') not in (None,'','valid') for x in docs)
  if valid: wb['valid']=1+wb['valid']
  elif pending: wb['pending_only']=1+wb['pending_only']
  elif rejected: wb['rejected_only']=1+wb['rejected_only']
  else: wb['no_status']=1+wb['no_status']
 nll=next((c for c in certs if c.get('certificate_id')==5976285),None)
 nrc=next((c for c in certs if c.get('certificate_id')==5976215),None)
 out={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'today':today,'snapshot':str(SNAP),'snapshot_complete':s['complete'],'ozon':{'catalog_products':len(products),'active':sum(p.get('is_archived') is False for p in products),'missing_sku':sum(not p.get('sku') for p in products),'certificates':len(certs),'certificate_status_counts':dict(Counter(str(c.get('status_code') or 'unknown') for c in certs)),'bindings':sum(int(c.get('live_binding_count') or 0) for c in certs),'active_approved_covered_products':len(covered),'active_with_sku':sum(p.get('is_archived') is False and bool(p.get('sku')) for p in products),'active_with_sku_no_approved_doc':sum(p.get('is_archived') is False and bool(p.get('sku')) and str(p.get('product_id')) not in covered for p in products),'navigator_95777':{'record_status':nll.get('status_code') if nll else None,'binding_status_counts':dict(Counter(str(b.get('product_status_code') or 'unknown') for b in (nll or {}).get('live_bindings',[]))),'binding_count':len((nll or {}).get('live_bindings',[]))},'navigator_47173':{'record_status':nrc.get('status_code') if nrc else None,'binding_status_counts':dict(Counter(str(b.get('product_status_code') or 'unknown') for b in (nrc or {}).get('live_bindings',[]))),'binding_count':len((nrc or {}).get('live_bindings',[]))}},'wb':{'catalog_cards':len(cards),'document_status_partition':dict(wb)}}
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
