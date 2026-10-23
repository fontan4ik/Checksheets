#!/usr/bin/env python3
"""Fresh read-only marketplace confirmation before retiring shared Navigator source PDFs."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

MAIN_PREFLIGHT = HERE / "navigator_nll_08110_06643_fresh_preflight_20261022.json"
ADDENDUM_PREFLIGHT = HERE / "navigator_93812_two_docs_live_preflight_20261023.json"
OUT = HERE / "navigator_nll_93812_crossplatform_cleanup_readback_20261023.json"

DECLARATION = {
    "number": "ЕАЭС N RU Д-CN.РА11.В.08110/24",
    "type_code": "declaration",
    "wb_type": 2,
    "issue": "2024-12-02",
    "expiry": "2029-12-01",
}
CERTIFICATE = {
    "number": "ЕАЭС RU С-CN.НВ54.В.06643/24",
    "type_code": "certificate_of_conformity",
    "wb_type": 1,
    "issue": "2024-12-04",
    "expiry": "2029-12-03",
}
ADDENDUM_CERTIFICATE = {
    "number": "ЕАЭС RU С-CN.НВ93.В.03629/23",
    "type_code": "certificate_of_conformity",
    "wb_type": 1,
    "issue": "2023-07-18",
    "expiry": "2028-07-17",
}


def ozon_records(client: Client) -> list[dict]:
    result: list[dict] = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("invalid_ozon_certificate_list")
        result.extend(batch)
        if not batch or page >= int(body.get("page_count") or 0):
            return result
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    main_pre = json.loads(MAIN_PREFLIGHT.read_text())
    add_pre = json.loads(ADDENDUM_PREFLIGHT.read_text())
    main_targets = {str(x["offer_id"]): x for x in main_pre["targets"]}
    add_targets = {str(x["offer_id"]): x for x in add_pre["targets"]}
    ozon_targets = {k: v for k, v in main_targets.items() if v.get("ozon_eligible") is True}
    ozon_targets.update(add_targets)
    if len(main_targets) != 153 or len(ozon_targets) != 58 or len(add_targets) != 2:
        raise RuntimeError("source_preflight_target_counts_changed")

    client = Client()
    records = ozon_records(client)
    ozon_results = []
    for doc, eligible in ((DECLARATION, ozon_targets), (CERTIFICATE, {k: v for k, v in ozon_targets.items() if k in main_targets})):
        matches = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) != 1:
            raise RuntimeError(f"ozon_record_count:{doc['number']}:{len(matches)}")
        record = matches[0]
        if record.get("type_code") != doc["type_code"] or str(record.get("issue_date") or "")[:10] != doc["issue"] or str(record.get("expire_date") or "")[:10] != doc["expiry"]:
            raise RuntimeError(f"ozon_record_metadata_conflict:{doc['number']}")
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        by_product = {(str(x.get("product_id")), str(x.get("sku"))): x for x in bindings}
        expected = {(str(x["product_id"]), str(x["sku"])) for x in eligible.values()}
        found = {pair: by_product[pair] for pair in expected if pair in by_product}
        counts = collections.Counter(str(x.get("product_status_code") or "unknown") for x in found.values())
        ozon_results.append({
            "number": doc["number"], "record_id": str(record.get("certificate_id")),
            "record_status": record.get("status_code"), "expected_bindings": len(expected),
            "visible_exact_bindings": len(found), "missing_bindings": len(expected - set(by_product)),
            "binding_status_counts": dict(counts),
            "target_details": [
                {"offer_id": offer, "product_id": str(x["product_id"]), "sku": str(x["sku"]),
                 "status": by_product.get((str(x["product_id"]), str(x["sku"])), {}).get("product_status_code")}
                for offer, x in sorted(eligible.items())
            ],
            "all_expected_approved": record.get("status_code") == "approved" and len(found) == len(expected) and counts == {"approved": len(expected)},
        })

    wb_main_docs = [DECLARATION, CERTIFICATE]
    wb_addendum_docs = [DECLARATION, ADDENDUM_CERTIFICATE]
    wb_targets = {k: v for k, v in main_targets.items() if v.get("wb_eligible") is True}
    wb_targets.update(add_targets)
    if len(wb_targets) != 155:
        raise RuntimeError("wb_target_count_changed")
    wb_rows = []
    wb_failures = []
    verdict_counts: collections.Counter[str] = collections.Counter()
    for i, (offer, target) in enumerate(sorted(wb_targets.items()), start=1):
        cards = client.wb_cards(offer)
        if len(cards) != 1 or str(cards[0].get("vendorCode") or "") != offer:
            wb_failures.append({"offer_id": offer, "reason": "card_missing_or_ambiguous", "count": len(cards)})
            continue
        card = cards[0]
        want_docs = wb_main_docs if offer in main_targets else wb_addendum_docs
        # copy_documents() intentionally strips verdicts for upload payloads;
        # this readback must inspect the raw marketplace response instead.
        live_docs = (card.get("documents") or {}).get("items") or []
        if not isinstance(live_docs, list):
            wb_failures.append({"offer_id": offer, "reason": "documents_items_missing"})
            continue
        doc_results = []
        for doc in want_docs:
            same = [x for x in live_docs if norm_number(x.get("number")) == norm_number(doc["number"])]
            exact = [x for x in same if int(x.get("type") or 0) == doc["wb_type"]
                     and str(x.get("startDate") or "")[:10] == doc["issue"]
                     and str(x.get("endDate") or "")[:10] == doc["expiry"]
                     and x.get("isEndless") is False]
            if len(exact) != 1:
                wb_failures.append({"offer_id": offer, "number": doc["number"],
                                    "reason": "exact_document_count", "found": len(exact), "same_number": len(same)})
                continue
            verdict = exact[0].get("verdict") or {}
            status = "valid" if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid" else "pending_or_unverified"
            verdict_counts[status] += 1
            doc_results.append({"number": doc["number"], "status": status, "verdict": verdict})
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
                        "document_count": len(doc_results), "expected_document_count": len(want_docs), "documents": doc_results})
        if i % 25 == 0 or i == len(wb_targets):
            print(json.dumps({"live_wb_readbacks": i, "total": len(wb_targets)}, ensure_ascii=False), flush=True)

    all_ozon_approved = all(x["all_expected_approved"] for x in ozon_results)
    all_wb_valid = not wb_failures and len(wb_rows) == len(wb_targets) and all(
        len(x["documents"]) == x["expected_document_count"] and all(d["status"] == "valid" for d in x["documents"])
        for x in wb_rows
    )
    report = {
        "checked_at_utc": now(), "read_only": True, "ozon_expected_eligible_offers": len(ozon_targets),
        "ozon_skipped_out_of_scope_count": len(main_pre.get("ozon_skipped_targets") or []),
        "ozon_documents": ozon_results, "all_ozon_expected_bindings_approved": all_ozon_approved,
        "wb_target_count": len(wb_targets), "wb_verdict_counts": dict(verdict_counts),
        "wb_failure_count": len(wb_failures), "wb_failures": wb_failures, "wb_cards": wb_rows,
        "all_wb_exact_documents_valid": all_wb_valid,
        "no_marketplace_writes_sent": True, "no_local_files_deleted": True,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("wb_cards", "wb_failures")}, ensure_ascii=False, indent=2))
    if not all_ozon_approved or not all_wb_valid:
        raise RuntimeError("cleanup_readback_not_complete")


if __name__ == "__main__":
    main()
