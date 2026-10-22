"""Read-only fresh WB item and card verdict check for Arlight 46747/26."""
from __future__ import annotations
import collections, csv, json, pathlib, sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'test/certificate_api_pilot_20261012'))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number
SHA='2fc3790ce4644d8e1c4150df3d1efdb2a06361442dc916e9c288c48fa7363d5c'
NUMBER='ЕАЭС RU С-CN.АЯ46.В.46747/26'
ISSUE='2026-03-23'; EXPIRY='2031-03-22'
ASSIGN=ROOT/'output_to_user/certificates/document_assignments.csv'
OUT=HERE/'arlight_46747_wb_verdicts_raw_recheck_20261021.json'

def item_state(doc, overall, exclude):
    v=doc.get('verdict') or {}
    if v.get('verified') is True and v.get('status')==1 and v.get('reason')=='valid':
        if exclude is False and overall.get('status')==1 and overall.get('isFullyChecked') is True:
            return 'valid_final'
        return 'valid_item_card_not_final'
    if v.get('verified') is False or v.get('status')==2:
        return 'rejected_or_invalid'
    return 'pending_review_or_verdict_missing'

def main():
    if OUT.exists(): raise RuntimeError('output_already_exists')
    with ASSIGN.open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if str(r.get('SHA256 фактический') or '').lower()==SHA and r.get('Применимость')=='Подтверждено статусом покрытия']
    offers=sorted({str(r.get('Артикул продавца') or '') for r in rows})
    if len(rows)!=114 or len(offers)!=114: raise RuntimeError(f'assignment_count_changed:{len(rows)}:{len(offers)}')
    c=Client(); results=[]
    for i,offer in enumerate(offers,1):
        cards=c.wb_cards(offer)
        if len(cards)!=1:
            results.append({'offer_id':offer,'card_count':len(cards),'state':'missing_or_ambiguous_card'})
        else:
            card=cards[0]; docs=(card.get('documents') or {}); overall=docs.get('overallVerdict') or {}; exclude=docs.get('excludeDocuments')
            matches=[d for d in docs.get('items') or [] if norm_number(d.get('number') or '')==norm_number(NUMBER) and d.get('type')==1 and str(d.get('startDate') or '')[:10]==ISSUE and str(d.get('endDate') or '')[:10]==EXPIRY and d.get('isEndless') is False]
            if len(matches)!=1:
                results.append({'offer_id':offer,'nmID':card.get('nmID'),'card_count':1,'exact_document_count':len(matches),'state':'missing_or_ambiguous_exact_document'})
            else:
                d=matches[0]; v=d.get('verdict') or {}
                results.append({'offer_id':offer,'nmID':str(card.get('nmID') or ''),'card_count':1,'exact_document_count':1,'state':item_state(d,overall,exclude),'document_id':d.get('id'),'document_verdict':v,'overall_verdict':overall,'excludeDocuments':exclude})
        if i%25==0: print(json.dumps({'phase':'fresh_raw_wb_verdicts','checked':i,'total':len(offers)},ensure_ascii=False),flush=True)
    counts=collections.Counter(x['state'] for x in results)
    out={'checked_at':now(),'read_only':True,'certificate_number':NUMBER,'source_assignment_count':len(offers),'wb_target_rows':len(results),'state_counts':dict(counts),'results':results}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:out[k] for k in ('checked_at','read_only','source_assignment_count','wb_target_rows','state_counts')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
