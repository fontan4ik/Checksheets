#!/usr/bin/env python3
"""Read-only delayed WB confirmation for Navigator NGX-S2 documents."""
from __future__ import annotations
import collections, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, doc_key, norm_number  # noqa: E402

PREFLIGHT = HERE / "navigator_67886_40114_live_preflight_20261022.json"
BEFORE = HERE / "navigator_67886_40114_wb_before_20261022.json"
OUT = HERE / "navigator_67886_40114_wb_delayed_readback_20261022.json"
DOCS = [
    {"number": "ЕАЭС N RU Д-CN.РА03.В.67886/25", "type": 2, "start": "2025-04-17", "end": "2030-04-15"},
    {"number": "ЕАЭС RU С-CN.АЯ46.В.40114/25", "type": 1, "start": "2025-04-16", "end": "2030-04-15"},
]

def main():
    if OUT.exists(): raise RuntimeError("readback_artifact_exists_inspect_first")
    pre=json.loads(PREFLIGHT.read_text()); before=json.loads(BEFORE.read_text()); client=Client()
    before_by_offer=before["cards"]
    rows=[]; verdicts=collections.Counter(); exact_counts=collections.Counter(); failures=[]
    for target in pre["wb_targets"]:
        offer=str(target["offer_id"])
        cards=[x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "")==offer]
        if len(cards)!=1:
            failures.append({"offer_id":offer,"problem":"card_count","count":len(cards)}); continue
        card=cards[0]; docs=copy_documents(card); document_rows=[]
        for wanted in DOCS:
            matches=[x for x in docs if norm_number(x.get("number"))==norm_number(wanted["number"])
                     and str(x.get("type"))==str(wanted["type"])
                     and str(x.get("startDate") or "")[:10]==wanted["start"]
                     and str(x.get("endDate") or "")[:10]==wanted["end"]
                     and x.get("isEndless") is False]
            document_rows.extend(matches)
            if len(matches)==1:
                verdict=matches[0].get("verdict")
                label="valid" if isinstance(verdict,dict) and verdict.get("verified") is True and verdict.get("reason")=="valid" else "pending_or_unverified" if verdict is None else "other"
                verdicts[label]+=1
            else:
                failures.append({"offer_id":offer,"problem":"document_missing_or_duplicate","number":wanted["number"],"count":len(matches)})
        prior=before_by_offer[offer]
        current_sigs=[(doc_key(x),str(x.get("startDate") or "")[:10],str(x.get("endDate") or "")[:10],bool(x.get("isEndless"))) for x in docs]
        prior_sigs=prior["prior_signatures"]
        prior_preserved=all(sig in current_sigs for sig in prior_sigs)
        unrelated_preserved=comparable_card(card)==comparable_card(prior["card"])
        if not prior_preserved or not unrelated_preserved:
            failures.append({"offer_id":offer,"problem":"preservation_check_failed"})
        exact_counts[len(document_rows)]+=1
        rows.append({"offer_id":offer,"nmID":str(card.get("nmID") or ""),"exact_document_count":len(document_rows),
                     "document_verdicts":[x.get("verdict") for x in document_rows],
                     "prior_documents_preserved":prior_preserved,"unrelated_card_fields_preserved":unrelated_preserved})
    result={"checked_at_utc":now(),"read_only":True,"target_cards":len(pre["wb_targets"]),
            "exact_document_count_distribution":dict(exact_counts),"document_verdict_counts":dict(verdicts),
            "cards_with_both_exact_documents":sum(x["exact_document_count"]==2 for x in rows),
            "failures":failures,"cards":rows,"wb_left_for_marketplace_review":True}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="cards"},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
