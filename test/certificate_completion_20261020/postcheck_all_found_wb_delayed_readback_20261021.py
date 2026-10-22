"""Read back WB cards that were not visible immediately after the bulk update."""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number,
)

STATE = HERE / "all_found_coverage_state_20261021.json"
SUMMARY = HERE / "all_found_coverage_summary_20261021.json"
READBACK = HERE / "all_found_wb_readback_9ad97e303805b13c.json"
PRODUCTS = HERE / "all_found_ozon_products_snapshot_20261014.json"
CERTIFICATES = HERE / "all_found_ozon_certificates_snapshot_20261014.json"
OUT = HERE / "all_found_coverage_delayed_wb_readback_20261021.json"
TYPE_MAP = {"declaration": 2, "certificate_of_conformity": 1}


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def verdict(doc: dict) -> str:
    info = doc.get("verdict") or {}
    if info.get("verified") is True and info.get("reason") == "valid":
        return "valid"
    if info.get("verified") is True and info.get("reason") not in (None, "", "valid"):
        return "rejected_or_invalid"
    return "pending_or_missing_verdict"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("delayed_readback_output_exists_reconcile_first")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    initial = json.loads(READBACK.read_text(encoding="utf-8"))
    products_doc = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    cert_doc = json.loads(CERTIFICATES.read_text(encoding="utf-8"))
    if (state.get("phase") != "finished_review_pending_and_problems_skipped"
            or summary.get("wb_accepted_cards") != 68
            or len(initial.get("results") or []) != 68
            or products_doc.get("complete") is not True
            or cert_doc.get("complete") is not True):
        raise RuntimeError("delayed_readback_precondition_failed")

    products_by_pair = {}
    for product in products_doc.get("products") or []:
        pair = (str(product.get("product_id") or product.get("id") or ""),
                str(product.get("sku") or ""))
        if pair in products_by_pair:
            raise RuntimeError("duplicate_product_sku_pair_in_snapshot")
        products_by_pair[pair] = product
    docs_by_offer: dict[str, dict[tuple, dict]] = collections.defaultdict(dict)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for cert in cert_doc.get("certificates") or []:
        wb_type = TYPE_MAP.get(str(cert.get("type_code") or ""))
        issue = str(cert.get("issue_date") or "")[:10]
        expiry = str(cert.get("expire_date") or "")[:10]
        if (not wb_type or cert.get("status_code") != "approved"
                or cert.get("accordance_type_code") != "EAEU"
                or not issue or not expiry or issue > today or expiry < today):
            continue
        for binding in cert.get("live_bindings") or []:
            if binding.get("product_status_code") != "approved":
                continue
            pair = (str(binding.get("product_id") or ""), str(binding.get("sku") or ""))
            product = products_by_pair.get(pair)
            if not product or product.get("is_archived") is not False or not product.get("offer_id"):
                continue
            wanted = {"type": wb_type, "number": cert.get("certificate_number"),
                      "startDate": issue + "T00:00:00Z", "endDate": expiry + "T00:00:00Z",
                      "isEndless": False}
            docs_by_offer[str(product["offer_id"])][doc_key(wanted)] = wanted

    pending_rows = [row for row in initial.get("results") or []
                    if row.get("verdict") != "visible_review_left_pending"]
    if len(pending_rows) != 20:
        raise RuntimeError(f"unexpected_delayed_readback_row_count:{len(pending_rows)}")
    client = Client()
    results = []
    for row in pending_rows:
        offer = str(row.get("offer_id") or "")
        cards = client.wb_cards(offer)
        if len(cards) != 1 or not row.get("cards") or len(row["cards"]) != 1:
            results.append({"offer_id": offer, "readback_verified": False,
                            "reason": "missing_or_duplicate_card_snapshot"})
            continue
        card, old = cards[0], row["cards"][0]
        current_docs = (card.get("documents") or {}).get("items") or []
        old_docs = copy_documents(old)
        current_copy = copy_documents(card)
        current_sigs = collections.Counter(signature(doc) for doc in current_copy)
        old_sigs = collections.Counter(signature(doc) for doc in old_docs)
        preserved = (comparable_card(card) == comparable_card(old)
                     and all(current_sigs[sig] >= count for sig, count in old_sigs.items()))
        same_expected = list(docs_by_offer.get(offer, {}).values())
        existed_before = {(doc_key(doc), str(doc.get("startDate", ""))[:10],
                           str(doc.get("endDate", ""))[:10], doc.get("isEndless") is False)
                          for doc in old_docs}
        expected_items = [doc for doc in same_expected
                          if (doc_key(doc), str(doc["startDate"])[:10], str(doc["endDate"])[:10], True)
                          not in existed_before]
        checks = []
        for wanted in expected_items:
            same = [doc for doc in current_docs
                    if norm_number(doc.get("number")) == norm_number(wanted.get("number"))]
            exact = [doc for doc in same if doc_key(doc) == doc_key(wanted)
                     and str(doc.get("startDate", ""))[:10] == str(wanted["startDate"])[:10]
                     and str(doc.get("endDate", ""))[:10] == str(wanted["endDate"])[:10]
                     and doc.get("isEndless") is False]
            checks.append({"number": wanted.get("number"), "exact": len(same) == 1 and len(exact) == 1,
                           "status": verdict(exact[0]) if len(exact) == 1 else "missing_or_conflicting"})
        okay = (str(card.get("vendorCode") or "") == offer
                and str(card.get("nmID") or "") == str(row.get("cards", [{}])[0].get("nmID") or "")
                and preserved and bool(expected_items) and all(x["exact"] for x in checks))
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "readback_verified": okay, "preserved": preserved,
                        "expected_documents": checks,
                        "expected_document_count": len(expected_items)})

    counts = collections.Counter(x["status"] for row in results for x in row.get("expected_documents", []))
    result = {"checked_at": now(), "complete": all(x.get("readback_verified") for x in results),
              "bulk_run_finished_at": summary.get("finished_at"),
              "initially_pending_count": len(pending_rows),
              "late_readback_verified_count": sum(x.get("readback_verified") is True for x in results),
              "status_counts": dict(counts), "results": results,
              "no_repeat_write": True, "wb_review_left_pending": True}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
