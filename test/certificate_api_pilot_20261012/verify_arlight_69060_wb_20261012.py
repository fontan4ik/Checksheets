"""Verify WB card readback and document verdicts after the submitted update."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLAN = BASE / "arlight_69060_wb_plan_20261012.json"
RUN = BASE / "arlight_69060_wb_execution_20261012.json"
WB_AFTER = BASE / "arlight_69060_wb_fullcards_after_stable_retry_20261012.json"
OZON = BASE / "arlight_69060_ozon_verification_20261012.json"
OUT = BASE / "arlight_69060_wb_verification_final_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def clean_doc(doc: dict) -> dict:
    return {k: doc[k] for k in DOC_FIELDS if k in doc}


def characteristic_signature(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("WB verification already exists; inspect it before regenerating")
    plan = json.loads(PLAN.read_text())
    run = json.loads(RUN.read_text())
    wb = json.loads(WB_AFTER.read_text())
    ozon = json.loads(OZON.read_text())
    if (run.get("phase") != "accepted_waiting_for_review" or run.get("response", {}).get("error") is not False
            or not wb.get("complete") or wb.get("target_count") != 549 or wb.get("targets_found") != 549
            or not ozon.get("all_bindings_confirmed") or ozon.get("covered_target_sku_count") != 549):
        raise RuntimeError("WB update acceptance, complete readback, or Ozon binding evidence is missing")
    if wb.get("duplicate_nmids"):
        raise RuntimeError("WB full catalog has duplicate nmIDs")
    cards = wb.get("cards_by_offer") or {}
    if set(cards) != {x["offer_id"] for x in plan.get("updates", [])} | {x["offer_id"] for x in plan.get("already_present", [])} | {x["offer_id"] for x in plan.get("excluded", [])}:
        raise RuntimeError("WB readback offer set differs from plan coverage")
    failures = []
    statuses = Counter()
    checked = 0
    for item in plan.get("updates", []):
        offer = item["offer_id"]
        after = cards[offer]
        before = item["before"]
        if (after.get("vendorCode") != offer or str(after.get("nmID")) != str(item["nmID"])):
            failures.append({"offer_id": offer, "error": "identity_changed"})
            continue
        changed = [field for field in CARD_FIELDS if field != "characteristics"
                   and after.get(field) != before.get(field)]
        if changed:
            failures.append({"offer_id": offer, "error": "non_document_card_fields_changed", "fields": changed})
        old_characteristics = Counter(map(characteristic_signature, before.get("characteristics") or []))
        allowed_document_characteristics = Counter()
        for item in (
            {"id": 15001135, "name": "Номер декларации соответствия", "value": [NUMBER]},
            {"id": 15001137, "name": "Дата регистрации сертификата/декларации", "value": ["10.03.2025"]},
            {"id": 15001138, "name": "Дата окончания действия сертификата/декларации", "value": ["09.03.2030"]},
        ):
            allowed_document_characteristics[characteristic_signature(item)] += 1
        actual_characteristics = Counter(map(characteristic_signature, after.get("characteristics") or []))
        missing_old_characteristics = old_characteristics - actual_characteristics
        extra_characteristics = actual_characteristics - old_characteristics
        if missing_old_characteristics or extra_characteristics - allowed_document_characteristics:
            failures.append({"offer_id": offer, "error": "existing_characteristics_changed_or_unexpected_field_added"})
        actual_docs = ((after.get("documents") or {}).get("items") or [])
        exact = [d for d in actual_docs if normalize(d.get("number")) == normalize(NUMBER)]
        if len(exact) != 1:
            failures.append({"offer_id": offer, "error": "exact_document_row_count", "count": len(exact)})
            continue
        row = exact[0]
        if (int(row.get("type", -1)) != 2 or str(row.get("startDate", ""))[:10] != "2025-03-10"
                or str(row.get("endDate", ""))[:10] != "2030-03-09" or row.get("isEndless") is not False):
            failures.append({"offer_id": offer, "error": "exact_document_metadata_conflict", "row": row})
        if (after.get("documents") or {}).get("excludeDocuments") is not False:
            failures.append({"offer_id": offer, "error": "documents_excluded"})
        old_clean = [clean_doc(x) for x in ((before.get("documents") or {}).get("items") or [])]
        actual_non_target = [clean_doc(x) for x in actual_docs if normalize(x.get("number")) != normalize(NUMBER)]
        signature = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)
        if Counter(map(signature, old_clean)) != Counter(map(signature, actual_non_target)):
            failures.append({"offer_id": offer, "error": "existing_document_rows_changed"})
        verdict = row.get("verdict") or {}
        status_key = json.dumps({"verified": verdict.get("verified"), "status": verdict.get("status"),
                                 "reason": verdict.get("reason")}, ensure_ascii=False, sort_keys=True)
        statuses[status_key] += 1
        checked += 1

    for item in plan.get("already_present", []):
        offer = item["offer_id"]
        rows = [d for d in ((cards[offer].get("documents") or {}).get("items") or [])
                if normalize(d.get("number")) == normalize(NUMBER)]
        if len(rows) != 1:
            failures.append({"offer_id": offer, "error": "already_present_row_not_visible"})

    report = {
        "checked_at": wb.get("checked_at"), "number": NUMBER,
        "ozon_certificate_id": ozon.get("certificate_id"),
        "ozon_target_pairs_confirmed": ozon.get("covered_target_sku_count"),
        "wb_plan_target_count": plan.get("counts", {}).get("source_targets"),
        "wb_cards_updated": plan.get("counts", {}).get("wb_cards_to_update"),
        "wb_exact_rows_read_back": checked,
        "wb_exact_rows_already_present": len(plan.get("already_present", [])),
        "wb_cards_excluded_by_tnved": plan.get("excluded", []),
        "wb_document_verdict_counts": {k: v for k, v in statuses.items()},
        "wb_cards_with_all_original_characteristics_preserved_and_only_document_characteristics_added":
            checked - sum(1 for x in failures if x.get("error") == "existing_characteristics_changed_or_unexpected_field_added"),
        "wb_failures": failures,
        "wb_failure_count": len(failures),
        "wb_failure_sample": failures[:10],
        "all_submitted_rows_present_and_preserved": not failures,
        "all_rows_approved": not failures and checked > 0 and all(
            json.loads(k).get("verified") is True and json.loads(k).get("status") == 1
            and json.loads(k).get("reason") == "valid" for k in statuses),
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "WB document verification is pending or not valid for every exact row; retain local source files.",
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: report[k] for k in (
        "number", "ozon_certificate_id", "ozon_target_pairs_confirmed", "wb_plan_target_count",
        "wb_cards_updated", "wb_exact_rows_read_back", "wb_document_verdict_counts",
        "wb_cards_with_all_original_characteristics_preserved_and_only_document_characteristics_added",
        "wb_failure_count", "wb_failure_sample", "all_submitted_rows_present_and_preserved", "all_rows_approved",
        "local_cleanup_allowed")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
