#!/usr/bin/env python3
"""Fresh read-only delayed confirmation for Gauss declaration 53277/22."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFLIGHT = HERE / "gauss_53277_scope_preflight_20261022.json"
BEFORE = HERE / "gauss_53277_scope_wb_before_20261022.json"
OUT = HERE / "gauss_53277_scope_delayed_readback_20261022.json"
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, doc_key, norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.PA01.В.53277/22"
ISSUE = "2022-02-01"
EXPIRE = "2027-01-31"
OZON_ID = 5951098


def signature(item: dict) -> tuple:
    return (doc_key(item), str(item.get("startDate", ""))[:10],
            str(item.get("endDate", ""))[:10], bool(item.get("isEndless")))


def freeze(value):
    if isinstance(value, (list, tuple)):
        return tuple(freeze(x) for x in value)
    return value


def main() -> None:
    if OUT.exists():
        raise RuntimeError("delayed_readback_output_exists_inspect_first")
    pre = json.loads(PREFLIGHT.read_text())
    before = json.loads(BEFORE.read_text())
    if pre.get("target_count") != 90 or before.get("complete") is not True or before.get("target_count") != 90:
        raise RuntimeError("preflight_or_wb_before_incomplete")
    pre_by_offer = {str(x["offer_id"]): x for x in pre["targets"]}
    before_by_offer = {str(x["offer_id"]): x for x in before["cards"]}
    if set(pre_by_offer) != set(before_by_offer):
        raise RuntimeError("preflight_and_before_offer_sets_differ")

    client = Client()
    records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        records.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_page_limit")
    exact_records = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(exact_records) != 1 or int(exact_records[0].get("certificate_id") or 0) != OZON_ID:
        raise RuntimeError("ozon_exact_record_missing_or_duplicate")
    record = exact_records[0]
    if (record.get("status_code") != "approved"
            or str(record.get("issue_date", ""))[:10] != ISSUE
            or str(record.get("expire_date", ""))[:10] != EXPIRE):
        raise RuntimeError("ozon_record_metadata_or_status_conflict")
    bindings = client.ozon_bindings(OZON_ID)
    expected_pairs = {(str(x["product_id"]), str(x["sku"])) for x in pre["targets"]}
    target_by_product = {str(x["product_id"]): x for x in pre["targets"]}
    actual_by_pair = {}
    duplicate_pairs = []
    for row in bindings:
        pair = (str(row.get("product_id") or ""), str(row.get("sku") or ""))
        if pair in actual_by_pair:
            duplicate_pairs.append(pair)
        actual_by_pair[pair] = row
    visible = {pair: actual_by_pair[pair] for pair in expected_pairs if pair in actual_by_pair}
    statuses = collections.Counter(str(x.get("product_status_code") or "unknown") for x in visible.values())
    declined = []
    for (pid, sku), row in visible.items():
        if row.get("product_status_code") == "declined":
            target = target_by_product.get(pid) or {}
            declined.append({"offer_id": target.get("offer_id"), "product_id": pid, "sku": sku})
    outside = [x for x in bindings if (str(x.get("product_id") or ""), str(x.get("sku") or "")) not in expected_pairs]

    wb_cards = []
    verdicts = collections.Counter()
    failures = []
    for index, offer in enumerate(sorted(pre_by_offer), start=1):
        target = pre_by_offer[offer]
        card_rows = client.wb_cards(offer)
        if len(card_rows) != 1:
            failures.append({"offer_id": offer, "problem": "wb_card_count", "count": len(card_rows)})
            continue
        card = card_rows[0]
        if str(card.get("nmID")) != str(target.get("wb_nmID")) or str(card.get("vendorCode")) != offer:
            failures.append({"offer_id": offer, "problem": "wb_identity_changed"})
        docs = ((card.get("documents") or {}).get("items") or [])
        matches = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in matches if int(x.get("type") or 0) == 2
                 and str(x.get("startDate", ""))[:10] == ISSUE
                 and str(x.get("endDate", ""))[:10] == EXPIRE
                 and x.get("isEndless") is False]
        verdict = exact[0].get("verdict") if len(exact) == 1 else None
        if len(exact) == 1:
            valid = isinstance(verdict, dict) and verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid"
            verdicts["valid" if valid else "pending_review_or_unverified"] += 1
        else:
            failures.append({"offer_id": offer, "problem": "wb_document_missing_or_duplicate", "exact_count": len(exact)})
        current_sigs = {freeze(signature(x)) for x in docs}
        prior_preserved = all(freeze(sig) in current_sigs for sig in before_by_offer[offer]["prior_doc_signatures"])
        unrelated_preserved = comparable_card(card) == comparable_card(before_by_offer[offer]["card"])
        if not prior_preserved or not unrelated_preserved:
            failures.append({"offer_id": offer, "problem": "wb_card_preservation_changed",
                             "prior_documents_preserved": prior_preserved,
                             "unrelated_card_fields_preserved": unrelated_preserved})
        wb_cards.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                         "exact_declaration_count": len(exact), "verdict": verdict,
                         "prior_documents_preserved": prior_preserved,
                         "unrelated_card_fields_preserved": unrelated_preserved})
        if index % 20 == 0 or index == len(pre_by_offer):
            print(json.dumps({"fresh_wb_cards_read": index, "total": len(pre_by_offer)}, ensure_ascii=False), flush=True)

    result = {
        "checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
        "ozon_certificate_id": OZON_ID, "ozon_record_status": record.get("status_code"),
        "ozon_expected_bindings": len(expected_pairs), "ozon_visible_bindings": len(visible),
        "ozon_all_expected_pairs_visible": len(visible) == len(expected_pairs) and not duplicate_pairs and not outside,
        "ozon_binding_status_counts": dict(statuses), "ozon_declined_offers": declined,
        "ozon_outside_binding_count": len(outside), "ozon_duplicate_binding_pairs": duplicate_pairs,
        "wb_target_cards": len(pre_by_offer),
        "wb_cards_with_exact_declaration": sum(x["exact_declaration_count"] == 1 for x in wb_cards),
        "wb_document_verdict_counts": dict(verdicts), "wb_left_for_marketplace_review": True,
        "wb_previous_documents_preserved": all(x["prior_documents_preserved"] for x in wb_cards),
        "wb_unrelated_card_fields_preserved": all(x["unrelated_card_fields_preserved"] for x in wb_cards),
        "failures": failures, "cards": wb_cards,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cards"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
