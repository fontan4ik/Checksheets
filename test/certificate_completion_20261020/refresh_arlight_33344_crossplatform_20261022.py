from __future__ import annotations
import collections, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent; ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number, comparable_card
PRE=HERE/'arlight_33344_partial_preflight_live_20261021.json'
OUT=HERE/'arlight_33344_fresh_crossplatform_readback_20261022.json'
NUMBER='ЕАЭС N RU Д-CN.РА03.В.33344/26'; CERT_ID=5920706

def main():
    pre=json.loads(PRE.read_text()); targets=pre['ozon_targets']; client=Client()
    info=client.call('ozon','/v1/product/certificate/info',{'certificate_number':NUMBER}).get('result') or {}
    ozon_bindings=client.ozon_bindings(CERT_ID)
    by_identity=collections.defaultdict(list)
    for b in ozon_bindings:
        by_identity[(str(b.get('product_id') or ''),str(b.get('sku') or ''))].append(b)
    ozon=[]; oc=collections.Counter()
    for t in targets:
        offer=str(t['offer_id']); key=(str(t.get('product_id') or ''),str(t.get('sku') or ''))
        exact=by_identity.get(key,[])
        statuses=[str(b.get('product_status_code') or '') for b in exact]
        approved=bool(exact) and all(s.upper()=='APPROVED' for s in statuses)
        oc['approved' if approved else ('bound_unapproved' if exact else 'missing')]+=1
        ozon.append({'offer_id':offer,'product_id':key[0],'sku':key[1],'exact_binding_count':len(exact),'product_status_codes':statuses,'approved':approved})
    wb=[]; wc=collections.Counter()
    for t in targets:
        offer=str(t['offer_id']); cards=client.wb_cards(offer)
        exact_card=[c for c in cards if str(c.get('vendorCode') or '')==offer]
        row={'offer_id':offer,'card_count':len(exact_card)}
        if len(exact_card)==1:
            card=exact_card[0]; docs=((card.get('documents') or {}).get('items') or [])
            same=[d for d in docs if norm_number(d.get('number'))==norm_number(NUMBER)]
            exact=[d for d in same if int(d.get('type') or 0)==2 and str(d.get('startDate',''))[:10]=='2026-04-13' and str(d.get('endDate',''))[:10]=='2031-04-09' and d.get('isEndless') is False]
            verdict=(exact[0].get('verdict') or {}) if len(exact)==1 else {}
            state='valid' if verdict.get('verified') is True and verdict.get('reason')=='valid' else ('review' if len(exact)==1 and verdict.get('verified') is not True else 'missing_or_conflict')
            row.update({'nmID':str(card.get('nmID') or ''),'document_count':len(same),'exact_document_count':len(exact),'document_state':state,'verdict':verdict})
            wc[state]+=1
        else:
            row['document_state']='no_exact_card' if not exact_card else 'ambiguous_card'; wc[row['document_state']]+=1
        wb.append(row)
    out={'checked_at':now(),'number':NUMBER,'official_fsa_record_id':21321061,'certificate_id':CERT_ID,'ozon_record':info,'ozon_binding_count':len(ozon_bindings),'ozon_status_counts':dict(oc),'ozon_targets':ozon,'wb_status_counts':dict(wc),'wb_targets':wb,'wb_review_left_pending':True,'local_pdf_deleted':False,'read_only':True}
    tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2));tmp.replace(OUT)
    print(json.dumps({'checked_at':out['checked_at'],'ozon_record_status':info.get('status_code'),'ozon_binding_count':len(ozon_bindings),'ozon_counts':dict(oc),'wb_counts':dict(wc),'wb_review_left_pending':True},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
