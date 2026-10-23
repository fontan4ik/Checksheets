#!/usr/bin/env python3
"""Read-only delayed readback after WB accepted declaration 48971/24."""
from __future__ import annotations
import collections, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number

NUMBER = "ЕАЭС N RU Д-CN.РА08.В.48971/24"
ISSUE, EXPIRY = "2024-09-18", "2029-09-17"
PREFLIGHT = HERE / "gauss_48971_crossplatform_preflight_20261023.json"
EXECUTION = HERE / "gauss_48971_execution_20261023.json"
WB_BEFORE = HERE / "gauss_48971_wb_before_20261023.json"
OUT = HERE / "gauss_48971_wb_delayed_readback_20261023.json"


def main():
    if OUT.exists():
        raise RuntimeError("readback_artifact_exists_inspect_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    state = json.loads(EXECUTION.read_text(encoding="utf-8"))
    before_doc = json.loads(WB_BEFORE.read_text(encoding="utf-8"))
    if state.get("wb_result", {}).get("response", {}).get("error") is not False:
        raise RuntimeError("wb_write_not_confirmed_accepted")
    before = {str(c.get("vendorCode") or ""): c for c in before_doc.get("full_cards") or []}
    rows = []
    client = Client()
    for target in pre["targets"]:
        offer = target["offer_id"]
        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            rows.append({"offer_id": offer, "card_count": len(cards), "exact_metadata_count": 0,
                         "verdicts": [], "readback_error": "card_not_unique"})
            continue
        card = cards[0]
        docs = ((card.get("documents") or {}).get("items") or [])
        exact = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)
                 and str(d.get("type")) == "2" and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY and d.get("isEndless") is False]
        prior_card = before.get(offer) or {}
        prior_docs = ((prior_card.get("documents") or {}).get("items") or [])
        prior_keys = {(norm_number(d.get("number")), str(d.get("type") or "")) for d in prior_docs}
        current_keys = {(norm_number(d.get("number")), str(d.get("type") or "")) for d in docs}
        fields = ("nmID", "vendorCode", "brand", "title", "description", "dimensions", "sizes",
                  "kizMarked", "needKiz", "characteristics")
        changed_fields = [k for k in fields if prior_card.get(k) != card.get(k)]
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "exact_metadata_count": len(exact), "verdicts": [d.get("verdict") for d in exact],
                     "document_count": len(docs), "prior_document_count": len(prior_docs),
                     "prior_documents_preserved": prior_keys.issubset(current_keys),
                     "changed_existing_fields": changed_fields})
    exact_total = sum(r.get("exact_metadata_count") == 1 for r in rows)
    verdicts = collections.Counter(str(v.get("reason", "unknown")) for row in rows
                                   for v in row.get("verdicts", []) if isinstance(v, dict))
    report = {"checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
              "cards": rows, "exact_metadata_visible": exact_total, "cards_expected": len(pre["targets"]),
              "verdict_reasons": dict(verdicts), "wb_review_left_to_marketplace": True,
              "cards_with_prior_documents_preserved": sum(r.get("prior_documents_preserved") is True for r in rows),
              "cards_without_changed_existing_fields": sum(not r.get("changed_existing_fields") for r in rows),
              "local_file_deleted": False}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"exact_metadata_visible": exact_total, "cards_expected": len(rows),
                      "verdict_reasons": dict(verdicts)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
