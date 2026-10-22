#!/usr/bin/env python3
"""Fresh delayed read-only cross-platform check for Saffit SSL declaration."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFLIGHT = HERE / "saffit_03649_scope_preflight_v3_20261022.json"
BEFORE = HERE / "saffit_03649_scope_wb_before_20261022.json"
OUT = HERE / "saffit_03649_scope_delayed_readback_20261022.json"
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, doc_key, norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА07.В.03649/23"
ISSUE = "2023-08-31"
EXPIRE = "2028-08-30"
OZON_ID = 5951274


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
    if pre.get("target_count") != 5 or before.get("complete") is not True or before.get("target_count") != 5:
        raise RuntimeError("preflight_or_before_evidence_incomplete")
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
    if record.get("status_code") != "approved" or str(record.get("issue_date", ""))[:10] != ISSUE or str(record.get("expire_date", ""))[:10] != EXPIRE:
        raise RuntimeError("ozon_record_status_or_metadata_conflict")
    bindings = client.ozon_bindings(OZON_ID)
    expected_pairs = {(str(x["product_id"]), str(x["sku"])) for x in pre["targets"]}
    actual_by_pair = {}
    duplicate_pairs = []
    for row in bindings:
        pair = (str(row.get("product_id") or ""), str(row.get("sku") or ""))
        if pair in actual_by_pair:
            duplicate_pairs.append(pair)
        actual_by_pair[pair] = row
    visible = {pair: actual_by_pair[pair] for pair in expected_pairs if pair in actual_by_pair}
    statuses = collections.Counter(str(x.get("product_status_code") or "unknown") for x in visible.values())
    outside = [x for x in bindings if (str(x.get("product_id") or ""), str(x.get("sku") or "")) not in expected_pairs]

    wb_rows = []
    verdict_counts = collections.Counter()
    failures = []
    for offer in sorted(pre_by_offer):
        target = pre_by_offer[offer]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "wb_card_count", "count": len(cards)})
            continue
        card = cards[0]
        if str(card.get("vendorCode")) != offer or str(card.get("nmID")) != str(target.get("wb_nmID")):
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
            verdict_counts["valid" if valid else "pending_review_or_unverified"] += 1
        else:
            failures.append({"offer_id": offer, "problem": "wb_document_missing_or_duplicate", "exact_count": len(exact)})
        current_sigs = {freeze(signature(x)) for x in docs}
        prior_preserved = all(freeze(sig) in current_sigs for sig in before_by_offer[offer]["prior_doc_signatures"])
        unrelated_preserved = comparable_card(card) == comparable_card(before_by_offer[offer]["card"])
        if not prior_preserved or not unrelated_preserved:
            failures.append({"offer_id": offer, "problem": "wb_card_preservation_changed"})
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                        "exact_declaration_count": len(exact), "verdict": verdict,
                        "prior_documents_preserved": prior_preserved,
                        "unrelated_card_fields_preserved": unrelated_preserved})

    result = {
        "checked_at_utc": now(), "read_only": True, "document_number": NUMBER,
        "ozon_certificate_id": OZON_ID, "ozon_record_status": record.get("status_code"),
        "ozon_expected_bindings": len(expected_pairs), "ozon_visible_bindings": len(visible),
        "ozon_all_expected_pairs_visible": len(visible) == len(expected_pairs) and not duplicate_pairs and not outside,
        "ozon_binding_status_counts": dict(statuses), "ozon_outside_binding_count": len(outside),
        "ozon_duplicate_binding_pairs": duplicate_pairs,
        "wb_target_cards": len(pre_by_offer),
        "wb_cards_with_exact_declaration": sum(x["exact_declaration_count"] == 1 for x in wb_rows),
        "wb_document_verdict_counts": dict(verdict_counts),
        "wb_previous_documents_preserved": all(x["prior_documents_preserved"] for x in wb_rows),
        "wb_unrelated_card_fields_preserved": all(x["unrelated_card_fields_preserved"] for x in wb_rows),
        "wb_left_for_marketplace_review": True, "failures": failures, "cards": wb_rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cards"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
