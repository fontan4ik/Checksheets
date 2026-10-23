#!/usr/bin/env python3
"""Final read-only WB audit: exact doc verdict plus preservation of prior fields."""
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
BEFORE = HERE / "gauss_48971_wb_before_20261023.json"
WRITE = HERE / "gauss_48971_execution_20261023.json"
OUT = HERE / "gauss_48971_wb_final_verification_20261023.json"
DOC_CHARACTERISTICS = {
    15001135: NUMBER,
    15001137: "18.09.2024",
    15001138: "17.09.2029",
}


def char_map(card):
    return {str(x.get("id")): x for x in card.get("characteristics") or []}


def main():
    if OUT.exists():
        raise RuntimeError("verification_artifact_exists_inspect_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    state = json.loads(WRITE.read_text(encoding="utf-8"))
    if state.get("wb_result", {}).get("response", {}).get("error") is not False:
        raise RuntimeError("wb_update_not_confirmed_accepted")
    old_cards = {str(c.get("vendorCode") or ""): c for c in before.get("full_cards") or []}
    rows = []
    client = Client()
    for target in pre["targets"]:
        offer = target["offer_id"]
        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            rows.append({"offer_id": offer, "card_count": len(cards), "exact_metadata_count": 0,
                         "verdicts": [], "preservation_ok": False})
            continue
        card, old = cards[0], old_cards[offer]
        old_chars, new_chars = char_map(old), char_map(card)
        prior_chars_preserved = all(new_chars.get(k) == value for k, value in old_chars.items())
        extras = {int(k): v for k, v in new_chars.items() if k not in old_chars}
        expected_extras = {k: {"id": k, "name": name, "value": [value]}
                           for k, name, value in [
                               (15001135, "Номер декларации соответствия", NUMBER),
                               (15001137, "Дата регистрации сертификата/декларации", "18.09.2024"),
                               (15001138, "Дата окончания действия сертификата/декларации", "17.09.2029"),
                           ]}
        doc_chars_match = all(k in extras and extras[k].get("name") == v["name"]
                              and extras[k].get("value") == v["value"] for k, v in expected_extras.items())
        other_fields = ("nmID", "vendorCode", "brand", "title", "description", "dimensions", "sizes",
                        "kizMarked", "needKiz")
        changed = [k for k in other_fields if old.get(k) != card.get(k)]
        old_docs = ((old.get("documents") or {}).get("items") or [])
        current_docs = ((card.get("documents") or {}).get("items") or [])
        old_doc_keys = collections.Counter((norm_number(d.get("number")), str(d.get("type") or ""))
                                           for d in old_docs)
        current_doc_keys = collections.Counter((norm_number(d.get("number")), str(d.get("type") or ""))
                                               for d in current_docs)
        docs_preserved = all(current_doc_keys[k] >= count for k, count in old_doc_keys.items())
        exact = [d for d in current_docs if norm_number(d.get("number")) == norm_number(NUMBER)
                 and str(d.get("type")) == "2" and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY and d.get("isEndless") is False]
        verdicts = [d.get("verdict") for d in exact]
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "exact_metadata_count": len(exact), "verdicts": verdicts,
                     "prior_characteristic_count": len(old_chars),
                     "prior_characteristics_preserved": prior_chars_preserved,
                     "added_document_characteristics_match": doc_chars_match,
                     "other_fields_unchanged": not changed,
                     "changed_other_fields": changed,
                     "prior_document_items_preserved": docs_preserved})
    verdict_reasons = collections.Counter(str(v.get("reason", "unknown")) for row in rows
                                          for v in row.get("verdicts", []) if isinstance(v, dict))
    report = {"checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
              "cards_expected": len(pre["targets"]),
              "exact_metadata_visible": sum(r.get("exact_metadata_count") == 1 for r in rows),
              "wb_verdict_reasons": dict(verdict_reasons),
              "cards_with_prior_characteristics_preserved": sum(r.get("prior_characteristics_preserved") is True for r in rows),
              "cards_with_added_declaration_characteristics": sum(r.get("added_document_characteristics_match") is True for r in rows),
              "cards_with_other_fields_unchanged": sum(r.get("other_fields_unchanged") is True for r in rows),
              "cards_with_prior_documents_preserved": sum(r.get("prior_document_items_preserved") is True for r in rows),
              "rows": rows, "local_file_deleted": False, "wb_review_left_to_marketplace": True}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "read_only", "document_number"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
