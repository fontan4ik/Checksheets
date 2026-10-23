#!/usr/bin/env python3
"""Read-only live verification for every 87392/22 link on Ozon and WB."""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(ROOT))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.PA08.B.87392/22"
NUMBER_KEY = norm_number(NUMBER)
ISSUE = "2022-12-07"
EXPIRY = "2027-12-06"
CERTIFICATE_ID = 5944403
PRE = HERE / "arlight_87392_crossplatform_preflight_20261023.json"
OUTPUT = HERE / "arlight_87392_live_all_links_verification_20261023.json"
OLD_OFFERS = {"031117-1", "031017-1", "025550-1"}


def live_records(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_page_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def exact_wb_doc(card: dict) -> dict | None:
    found = []
    docs = (card.get("documents") or {}).get("items") or []
    for doc in docs:
        if norm_number(doc.get("number")) != NUMBER_KEY:
            continue
        if (str(doc.get("type")) == "2"
                and str(doc.get("startDate") or "")[:10] == ISSUE
                and str(doc.get("endDate") or "")[:10] == EXPIRY
                and doc.get("isEndless") is False):
            found.append(doc)
    return found[0] if len(found) == 1 else None


def verdict_of(doc: dict | None) -> str:
    if not doc:
        return "missing_or_conflicting"
    verdict = doc.get("verdict")
    if not verdict:
        return "pending_or_missing"
    status = str(verdict.get("status") or "unknown")
    if verdict.get("verified") is True or status.casefold() in {"valid", "approved", "verified"}:
        return "valid"
    if status.casefold() in {"rejected", "invalid", "declined", "document_not_found"}:
        return status.casefold()
    return "pending_or_missing"


def main() -> None:
    pre = json.loads(PRE.read_text(encoding="utf-8"))
    expected = {str(x["offer_id"]): x for x in pre.get("ozon_targets", [])}
    if len(expected) != 153:
        raise RuntimeError("preflight_target_count_changed")
    client = Client()

    records = [x for x in live_records(client)
               if norm_number(x.get("certificate_number")) == NUMBER_KEY]
    if len(records) != 1:
        raise RuntimeError("ozon_record_missing_or_duplicated")
    record = records[0]
    if (str(record.get("certificate_id")) != str(CERTIFICATE_ID)
            or record.get("type_code") != "declaration"
            or record.get("accordance_type_code") != "EAEU"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_record_identity_or_dates_changed")

    bindings = client.ozon_bindings(CERTIFICATE_ID)
    binding_by_pid = {str(x.get("product_id") or ""): x for x in bindings}
    if len(binding_by_pid) != len(bindings):
        raise RuntimeError("duplicate_ozon_binding_product_id")
    target_by_pid = {str(x.get("product_id") or ""): x for x in expected.values()}
    if len(target_by_pid) != 153:
        raise RuntimeError("duplicate_preflight_product_id")
    linked = []
    for offer, target in expected.items():
        binding = binding_by_pid.get(str(target["product_id"]))
        exact = bool(binding and str(binding.get("sku") or "") == str(target["sku"]))
        linked.append({"offer_id": offer, "product_id": str(target["product_id"]),
                       "sku": str(target["sku"]), "exact_visible": exact,
                       "status": (binding or {}).get("product_status_code")})
    old_products = {}
    for offer in sorted(OLD_OFFERS):
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items")
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("offer_id")) != offer:
            raise RuntimeError("old_target_ozon_identity_missing:" + offer)
        p = rows[0]
        old_products[offer] = {"offer_id": offer, "product_id": str(p.get("product_id") or p.get("id") or ""),
                               "sku": str(p.get("sku") or "")}
    for offer, target in old_products.items():
        binding = binding_by_pid.get(target["product_id"])
        exact = bool(binding and str(binding.get("sku") or "") == target["sku"])
        linked.append({**target, "exact_visible": exact, "status": (binding or {}).get("product_status_code")})

    wb_rows = []
    for index, (offer, target) in enumerate(sorted({**expected, **old_products}.items()), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "card_count": len(cards), "exact_metadata": False,
                            "verdict": "missing_or_duplicate_card"})
            continue
        card = cards[0]
        doc = exact_wb_doc(card)
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "exact_metadata": doc is not None, "verdict": verdict_of(doc),
                        "brand": card.get("brand")})
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_live_readback", "checked": index, "total": 156}, ensure_ascii=False), flush=True)

    ozon_statuses = collections.Counter(str(x.get("status") or "unknown")
                                         for x in linked if x.get("exact_visible"))
    wb_verdicts = collections.Counter(x["verdict"] for x in wb_rows)
    result = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "certificate_id": CERTIFICATE_ID, "ozon_record_status": record.get("status_code"),
        "ozon_total_record_bindings": len(bindings), "ozon_targets_expected": 156,
        "ozon_exact_visible": sum(x["exact_visible"] for x in linked),
        "ozon_binding_status_counts": dict(ozon_statuses), "ozon_links": linked,
        "wb_targets_expected": 156,
        "wb_exact_metadata": sum(x["exact_metadata"] for x in wb_rows),
        "wb_verdict_counts": dict(wb_verdicts), "wb_links": wb_rows,
        "cleanup_safe": (sum(x["exact_visible"] for x in linked) == 156
                         and sum(x["exact_metadata"] for x in wb_rows) == 156),
        "wb_review_left_pending": True,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("ozon_links", "wb_links")},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
