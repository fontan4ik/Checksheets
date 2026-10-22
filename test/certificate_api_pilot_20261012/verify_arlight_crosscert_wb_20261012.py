"""Verify exact WB document rows, preserve-all-fields readback, and moderation state."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
PLAN = BASE / "arlight_crosscert_wb_plan_prewrite_20261012.json"
RUN = BASE / "arlight_crosscert_wb_execution_20261012.json"
WB_AFTER = BASE / "arlight_crosscert_wb_fullcards_after_20261012.json"
OZON_DECLARATION = BASE / "arlight_41382_ozon_verification_20261012.json"
OZON_CERTIFICATE = BASE / "arlight_00356_ozon_verification_20261012.json"
OUT = BASE / "arlight_crosscert_wb_verification_20261012.json"
DECLARATION = {"number": "ЕАЭС N RU Д-RU.РА08.В.41382/26", "type": 2,
               "issue": "2026-09-16", "expiry": "2031-09-15"}
CERTIFICATE = {"number": "ЕАЭС RU С-RU.НК50.В.00356/26", "type": 1,
               "issue": "2026-09-16", "expiry": "2031-09-15"}
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_CHAR_NAMES = {15001135: "Номер декларации соответствия",
                  15001137: "Дата регистрации сертификата/декларации",
                  15001138: "Дата окончания действия сертификата/декларации"}


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def clean_doc(doc: dict) -> dict:
    return {k: doc[k] for k in DOC_FIELDS if k in doc}


def signature(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def valid_characteristic_addition(row: dict) -> bool:
    try:
        ident = int(row.get("id", -1))
    except (TypeError, ValueError):
        return False
    if ident not in DOC_CHAR_NAMES or row.get("name") != DOC_CHAR_NAMES[ident]:
        return False
    values = row.get("value") or []
    if ident == 15001135:
        allowed = {DECLARATION["number"], CERTIFICATE["number"]}
        return bool(values) and set(map(str, values)).issubset(allowed)
    expected = {"16.09.2026"} if ident == 15001137 else {"15.09.2031"}
    return bool(values) and set(map(str, values)).issubset(expected)


def main() -> None:
    if OUT.exists():
        raise RuntimeError("WB verification already exists; inspect it before regenerating")
    plan = json.loads(PLAN.read_text())
    run = json.loads(RUN.read_text())
    wb = json.loads(WB_AFTER.read_text())
    ozon_declaration = json.loads(OZON_DECLARATION.read_text())
    ozon_certificate = json.loads(OZON_CERTIFICATE.read_text())
    if (run.get("phase") != "accepted_waiting_for_review" or run.get("response", {}).get("error") is not False
            or not wb.get("complete") or wb.get("target_count") != 339 or wb.get("targets_found") != 339
            or wb.get("duplicate_nmids") != 0
            or not ozon_declaration.get("all_bindings_confirmed") or ozon_declaration.get("covered_target_sku_count") != 339
            or not ozon_certificate.get("all_bindings_confirmed") or ozon_certificate.get("covered_target_sku_count") != 339):
        raise RuntimeError("WB update acceptance, complete target readback, or Ozon binding evidence is missing")
    cards = wb.get("cards_by_offer") or {}
    plan_offers = {x["offer_id"] for x in plan.get("updates", [])}
    excluded_offers = {x["offer_id"] for x in plan.get("excluded", [])}
    already_offers = {x["offer_id"] for x in plan.get("already_present", [])}
    if set(cards) != plan_offers | excluded_offers | already_offers:
        raise RuntimeError("WB readback offer set differs from plan coverage")

    failures = []
    verdicts = {DECLARATION["number"]: Counter(), CERTIFICATE["number"]: Counter()}
    checked_cards = 0
    for item in plan.get("updates", []):
        offer = item["offer_id"]
        after, before = cards[offer], item["before"]
        if after.get("vendorCode") != offer or str(after.get("nmID")) != str(item["nmID"]):
            failures.append({"offer_id": offer, "error": "identity_changed"})
            continue
        changed = [field for field in CARD_FIELDS if field != "characteristics"
                   and after.get(field) != before.get(field)]
        if changed:
            failures.append({"offer_id": offer, "error": "non_document_card_fields_changed", "fields": changed})
        old_chars = Counter(map(signature, before.get("characteristics") or []))
        new_chars = Counter(map(signature, after.get("characteristics") or []))
        missing_old = old_chars - new_chars
        extras = new_chars - old_chars
        bad_extras = [json.loads(x) for x, count in extras.items()
                      for _ in range(count) if not valid_characteristic_addition(json.loads(x))]
        if missing_old or bad_extras:
            failures.append({"offer_id": offer, "error": "existing_characteristics_changed_or_unexpected_addition",
                             "missing_old_count": sum(missing_old.values()), "unexpected_additions": bad_extras})

        actual_docs = ((after.get("documents") or {}).get("items") or [])
        if (after.get("documents") or {}).get("excludeDocuments") is not False:
            failures.append({"offer_id": offer, "error": "documents_excluded_after_update"})
        for spec in (DECLARATION, CERTIFICATE):
            exact = [d for d in actual_docs if normalize(d.get("number")) == normalize(spec["number"])]
            if len(exact) != 1:
                failures.append({"offer_id": offer, "number": spec["number"],
                                 "error": "exact_document_row_count", "count": len(exact)})
                continue
            row = exact[0]
            if (int(row.get("type", -1)) != spec["type"]
                    or str(row.get("startDate", ""))[:10] != spec["issue"]
                    or str(row.get("endDate", ""))[:10] != spec["expiry"]
                    or row.get("isEndless") is not False):
                failures.append({"offer_id": offer, "number": spec["number"],
                                 "error": "exact_document_metadata_conflict", "row": row})
            ver = row.get("verdict") or {}
            verdicts[spec["number"]][signature({"verified": ver.get("verified"), "status": ver.get("status"),
                                                 "reason": ver.get("reason")})] += 1
        old_docs = [clean_doc(x) for x in ((before.get("documents") or {}).get("items") or [])]
        non_target = [clean_doc(x) for x in actual_docs
                      if normalize(x.get("number")) not in {normalize(DECLARATION["number"]), normalize(CERTIFICATE["number"])}]
        if Counter(map(signature, old_docs)) != Counter(map(signature, non_target)):
            failures.append({"offer_id": offer, "error": "existing_document_rows_changed"})
        checked_cards += 1

    for item in plan.get("already_present", []):
        offer = item["offer_id"]
        actual_docs = ((cards[offer].get("documents") or {}).get("items") or [])
        for number in item.get("documents", []):
            if sum(normalize(d.get("number")) == normalize(number) for d in actual_docs) != 1:
                failures.append({"offer_id": offer, "number": number, "error": "already_present_row_not_visible"})

    excluded_rows = []
    for item in plan.get("excluded", []):
        offer = item["offer_id"]
        card = cards[offer]
        docs = (card.get("documents") or {}).get("items") or []
        found = [d.get("number") for d in docs if normalize(d.get("number")) in {
            normalize(DECLARATION["number"]), normalize(CERTIFICATE["number"])}]
        excluded_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                              "reason": item["reason"], "wb_tnved_codes": item.get("wb_tnved_codes"),
                              "target_documents_visible": found})
        if found:
            failures.append({"offer_id": offer, "error": "excluded_out_of_scope_card_contains_target_document",
                             "documents": found})

    status_summary = {number: {k: v for k, v in counts.items()} for number, counts in verdicts.items()}
    all_valid = not failures and all(
        json.loads(key).get("verified") is True and json.loads(key).get("status") == 1
        and json.loads(key).get("reason") == "valid"
        for counts in verdicts.values() for key in counts)
    report = {
        "checked_at": wb.get("checked_at"),
        "wb_snapshot_complete": wb.get("complete"),
        "source_targets": plan.get("counts", {}).get("source_targets"),
        "wb_cards_updated": plan.get("counts", {}).get("wb_cards_to_update"),
        "wb_cards_read_back": checked_cards,
        "wb_document_rows_expected": plan.get("counts", {}).get("document_rows_to_add"),
        "wb_document_verdict_counts_by_number": status_summary,
        "ozon": {
            DECLARATION["number"]: {"certificate_id": ozon_declaration.get("certificate_id"),
                                    "pairs_confirmed": ozon_declaration.get("covered_target_sku_count"),
                                    "status_counts": ozon_declaration.get("product_status_counts")},
            CERTIFICATE["number"]: {"certificate_id": ozon_certificate.get("certificate_id"),
                                    "pairs_confirmed": ozon_certificate.get("covered_target_sku_count"),
                                    "status_counts": ozon_certificate.get("product_status_counts")},
        },
        "excluded_wb_tnved_conflict_count": len(excluded_rows),
        "excluded_wb_tnved_conflicts": excluded_rows,
        "documents_enabled_on_cards": plan.get("counts", {}).get("cards_where_documents_will_be_enabled"),
        "wb_failures": failures,
        "wb_failure_count": len(failures),
        "all_submitted_rows_present_and_preserved": not failures,
        "all_rows_approved": all_valid,
        "wb_documents_left_for_review": True,
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "Not all marketplace bindings and final WB review outcomes are confirmed for the entire local source group.",
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: report[k] for k in (
        "source_targets", "wb_cards_updated", "wb_cards_read_back", "wb_document_rows_expected",
        "wb_document_verdict_counts_by_number", "excluded_wb_tnved_conflict_count",
        "documents_enabled_on_cards", "wb_failure_count", "all_submitted_rows_present_and_preserved",
        "all_rows_approved", "wb_documents_left_for_review", "local_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
