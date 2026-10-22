#!/usr/bin/env python3
"""Delayed read-only confirmation for Navigator 94200 declaration links."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFLIGHT = HERE / "navigator_94200_halogens_scope_preflight_20261022.json"
BEFORE = HERE / "navigator_94200_halogens_scope_wb_before_20261022.json"
OUT = HERE / "navigator_94200_halogens_scope_delayed_readback_20261022.json"
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, doc_key, norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА11.В.61378/25"
ISSUE = "2025-12-12"
EXPIRE = "2030-12-11"
OZON_ID = 5950933


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
    if pre.get("target_count") != 45 or before.get("complete") is not True or before.get("target_count") != 45:
        raise RuntimeError("preflight_or_wb_before_evidence_incomplete")
    before_by_offer = {str(x["offer_id"]): x for x in before["cards"]}
    products = {str(x["offer_id"]): x for x in pre["targets"]}
    if set(before_by_offer) != set(products):
        raise RuntimeError("before_and_preflight_offer_sets_differ")

    client = Client()
    ozon_bindings = client.ozon_bindings(OZON_ID)
    expected_pairs = {(str(x["product_id"]), str(x["sku"])) for x in pre["targets"]}
    actual_by_pair = {}
    duplicate_pairs = []
    for row in ozon_bindings:
        pair = (str(row.get("product_id") or ""), str(row.get("sku") or ""))
        if pair in actual_by_pair:
            duplicate_pairs.append(pair)
        actual_by_pair[pair] = row
    visible_rows = {pair: actual_by_pair.get(pair) for pair in expected_pairs}
    visible = {pair: row for pair, row in visible_rows.items() if row is not None}
    ozon_statuses = collections.Counter(str(x.get("product_status_code") or "unknown") for x in visible.values())
    ozon_info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}

    wb_cards = []
    verdicts = collections.Counter()
    failures = []
    for index, offer in enumerate(sorted(products), start=1):
        target = products[offer]
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
        prior_sigs = before_by_offer[offer]["prior_doc_signatures"]
        current_sigs = {freeze(signature(x)) for x in docs}
        prior_preserved = all(freeze(sig) in current_sigs for sig in prior_sigs)
        unrelated_preserved = comparable_card(card) == comparable_card(before_by_offer[offer]["card"])
        if not prior_preserved or not unrelated_preserved:
            failures.append({"offer_id": offer, "problem": "wb_card_preservation_changed",
                             "prior_documents_preserved": prior_preserved,
                             "unrelated_card_fields_preserved": unrelated_preserved})
        wb_cards.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                         "exact_declaration_count": len(exact), "verdict": verdict,
                         "prior_documents_preserved": prior_preserved,
                         "unrelated_card_fields_preserved": unrelated_preserved})
        if index % 15 == 0 or index == len(products):
            print(json.dumps({"fresh_wb_cards_read": index, "total": len(products)}, ensure_ascii=False), flush=True)

    result = {
        "checked_at_utc": now(), "read_only": True,
        "document_number": NUMBER, "ozon_certificate_id": OZON_ID,
        "ozon_record_status": ozon_info.get("status_code"),
        "ozon_expected_bindings": len(expected_pairs),
        "ozon_visible_bindings": len(visible),
        "ozon_all_expected_pairs_visible": len(visible) == len(expected_pairs) and not duplicate_pairs,
        "ozon_product_binding_status_counts": dict(ozon_statuses),
        "ozon_duplicate_binding_pairs": duplicate_pairs,
        "wb_target_cards": len(products),
        "wb_cards_with_exact_declaration": sum(x["exact_declaration_count"] == 1 for x in wb_cards),
        "wb_document_verdict_counts": dict(verdicts),
        "wb_left_for_marketplace_review": True,
        "failures": failures,
        "cards": wb_cards,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cards"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
