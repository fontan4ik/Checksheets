"""Read-only reconciliation for the three WB cards after asynchronous update indexing."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

PLAN = BASE / "arlight_69060_wb_extras_plan_20261012.json"
RUN = BASE / "arlight_69060_wb_extras_execution_20261012.json"
OUT = BASE / "arlight_69060_wb_extras_verification_final_20261012.json"
OZON = BASE / "arlight_69060_aggregate_verification_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def clean_doc(row: dict) -> dict:
    return {k: row[k] for k in DOC_FIELDS if k in row}


def signature(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Final readback report already exists; inspect it before regenerating")
    plan = json.loads(PLAN.read_text())
    run = json.loads(RUN.read_text())
    ozon = json.loads(OZON.read_text())
    updates = plan.get("updates") or []
    if (run.get("phase") not in {"readback_incomplete", "readback_complete"}
            or run.get("response", {}).get("error") is not False or len(updates) != 3
            or ozon.get("all_bindings_confirmed") is not True or ozon.get("target_sku_count") != 552):
        raise RuntimeError("Accepted WB update or all 552 Ozon bindings are not confirmed")
    client = Client()
    failures = []
    verdicts = Counter()
    rows_by_offer = {}
    for item in updates:
        offer = item["offer_id"]
        cards = client.wb_cards(offer)
        if (len(cards) != 1 or cards[0].get("vendorCode") != offer
                or str(cards[0].get("nmID")) != str(item["nmID"])):
            failures.append({"offer_id": offer, "error": "card_identity_mismatch"})
            continue
        card = cards[0]
        before = item["before"]
        for field in CARD_FIELDS:
            if field != "characteristics" and card.get(field) != before.get(field):
                failures.append({"offer_id": offer, "error": "non_document_card_field_changed", "field": field})
        old_chars = Counter(map(signature, before.get("characteristics") or []))
        current_chars = Counter(map(signature, card.get("characteristics") or []))
        extras = current_chars - old_chars
        allowed = Counter({
            signature({"id": 15001135, "name": "Номер декларации соответствия", "value": [NUMBER]}): 1,
            signature({"id": 15001137, "name": "Дата регистрации сертификата/декларации", "value": ["10.03.2025"]}): 1,
            signature({"id": 15001138, "name": "Дата окончания действия сертификата/декларации", "value": ["09.03.2030"]}): 1,
        })
        if old_chars - current_chars or extras - allowed:
            failures.append({"offer_id": offer, "error": "existing_characteristics_changed_or_unexpected_addition"})

        container = card.get("documents") or {}
        if container.get("excludeDocuments") is not False:
            failures.append({"offer_id": offer, "error": "documents_excluded"})
        docs = container.get("items") or []
        exact = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
        if len(exact) != 1:
            failures.append({"offer_id": offer, "error": "exact_document_row_count", "count": len(exact)})
            continue
        row = exact[0]
        if (int(row.get("type", -1)) != 2 or str(row.get("startDate", ""))[:10] != "2025-03-10"
                or str(row.get("endDate", ""))[:10] != "2030-03-09" or row.get("isEndless") is not False):
            failures.append({"offer_id": offer, "error": "document_metadata_mismatch"})
        old_docs = [clean_doc(d) for d in ((before.get("documents") or {}).get("items") or [])]
        non_target_docs = [clean_doc(d) for d in docs if norm(d.get("number")) != norm(NUMBER)]
        if Counter(map(signature, old_docs)) != Counter(map(signature, non_target_docs)):
            failures.append({"offer_id": offer, "error": "existing_document_rows_changed"})
        verdict = row.get("verdict") or {}
        normalized = {"verified": verdict.get("verified"), "status": verdict.get("status"),
                      "reason": verdict.get("reason")}
        verdicts[signature(normalized)] += 1
        rows_by_offer[offer] = {"nmID": str(card["nmID"]), "row": row, "verdict": normalized}

    all_present = len(rows_by_offer) == 3 and not any(x["error"] == "exact_document_row_count" for x in failures)
    all_valid = all_present and not failures and all(
        json.loads(key).get("verified") is True and json.loads(key).get("status") == 1
        and json.loads(key).get("reason") == "valid" for key in verdicts)
    report = {"checked_at": now(), "number": NUMBER, "ozon_certificate_id": 5624646,
              "ozon_exact_pairs_confirmed": 552, "target_pair_count": 3,
              "readback_count": len(rows_by_offer), "verdict_counts": dict(verdicts),
              "failures": failures, "document_rows": rows_by_offer,
              "all_exact_rows_present_and_metadata_correct": all_present and not failures,
              "all_rows_valid": all_valid, "wb_review_left_to_platform": True,
              "local_cleanup_allowed": False,
              "local_cleanup_reason": "The 69060/25 source group has an out-of-scope offer and an unresolved manufacturer-lot candidate; keep its local files."}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in (
        "number", "ozon_exact_pairs_confirmed", "target_pair_count", "readback_count", "verdict_counts",
        "failures", "all_exact_rows_present_and_metadata_correct", "all_rows_valid",
        "wb_review_left_to_platform", "local_cleanup_allowed")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
