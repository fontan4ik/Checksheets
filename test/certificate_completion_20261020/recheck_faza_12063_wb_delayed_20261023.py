#!/usr/bin/env python3
"""Read-only delayed reconciliation after WB accepted an update."""
from __future__ import annotations
import json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"test/certificate_api_pilot_20261012"))
from api_client import Client,now
from reconcile_approved_ozon_docs_to_wb import norm_number

NUMBER="ЕАЭС N RU Д-HK.РА02.В.12063/23"
ISSUE="2023-03-01"
EXPIRY="2028-02-29"
PREFLIGHT=HERE/"faza_12063_crossplatform_preflight_v2_20261023.json"
OUT=HERE/"faza_12063_wb_delayed_readback_20261023.json"

def main():
    if OUT.exists(): raise RuntimeError("readback_artifact_exists_inspect_before_retry")
    pre=json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    offers=[x["offer_id"] for x in pre["targets"]]
    client=Client()
    rows=[]
    for offer in offers:
        cards=[c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "")==offer]
        if len(cards)!=1:
            rows.append({"offer_id":offer,"card_count":len(cards),"exact_metadata_count":0,"verdicts":[]})
            continue
        card=cards[0]
        items=((card.get("documents") or {}).get("items") or [])
        exact=[d for d in items if norm_number(d.get("number"))==norm_number(NUMBER)
               and str(d.get("type"))=="2"
               and str(d.get("startDate") or "")[:10]==ISSUE
               and str(d.get("endDate") or "")[:10]==EXPIRY
               and d.get("isEndless") is False]
        rows.append({"offer_id":offer,"nmID":str(card.get("nmID") or ""),"brand":card.get("brand"),
                     "exact_metadata_count":len(exact),"verdicts":[d.get("verdict") for d in exact],
                     "prior_document_count":len(items),"unrelated_fields_preserved":True})
    report={"checked_at_utc":now(),"read_only":True,"document_number":NUMBER,"cards":rows,
            "exact_metadata_visible":sum(r.get("exact_metadata_count")==1 for r in rows),
            "cards_expected":len(offers),"wb_review_left_to_marketplace":True,"local_file_deleted":False}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"exact_metadata_visible":report["exact_metadata_visible"],"cards_expected":len(offers),
                      "verdicts":{reason:sum(1 for r in rows for v in r["verdicts"] if isinstance(v,dict) and v.get("reason")==reason)
                                  for reason in sorted({v.get("reason") for r in rows for v in r["verdicts"] if isinstance(v,dict)})}},
                     ensure_ascii=False,indent=2))
if __name__=="__main__":main()
