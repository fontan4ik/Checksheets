#!/usr/bin/env python3
"""Fresh read-only cross-platform verification for Navigator NFL documents."""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

PREFLIGHT = HERE / "navigator_nfl_90815_00107_fresh_v2_20261022.json"
OZON = HERE / "navigator_00107_ozon_certificate_retry_20261022.json"
BEFORE = HERE / "navigator_nfl_90815_00107_wb_before_20261022.json"
OUT = HERE / "navigator_nfl_90815_00107_final_live_crossplatform_readback_20261022.json"
DOCS = [
    {"number": "ЕАЭС N RU Д-RU.РА11.В.90815/24", "type_code": "declaration", "wb_type": 2,
     "issue": "2024-12-27", "expiry": "2029-12-25", "id": 5946929},
    {"number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "type_code": "certificate_of_conformity", "wb_type": 1,
     "issue": "2024-12-24", "expiry": "2029-12-23", "id": 5947021},
]


def all_records(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    pre = json.loads(PREFLIGHT.read_text())
    ozon_expected = {x["offer_id"]: x for x in json.loads(OZON.read_text())["ozon_targets"]}
    wb_before_rows = json.loads(BEFORE.read_text()).get("cards") or []
    wb_before = {str(x.get("offer_id") or ""): x.get("card") or {} for x in wb_before_rows}
    targets = {str(x["offer_id"]): x for x in pre["targets"]}
    if len(targets) != 11 or set(targets) != set(ozon_expected):
        raise RuntimeError("cross_platform_target_set_not_exactly_11")
    client = Client()
    records = all_records(client)
    ozon = {}
    for doc in DOCS:
        matches = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) != 1:
            raise RuntimeError("ozon_record_missing_or_duplicate:" + doc["number"])
        record = matches[0]
        if (record.get("type_code") != doc["type_code"] or record.get("status_code") != "approved"
                or str(record.get("issue_date", ""))[:10] != doc["issue"]
                or str(record.get("expire_date", ""))[:10] != doc["expiry"]
                or str(record.get("certificate_id")) != str(doc["id"])):
            raise RuntimeError("ozon_record_metadata_or_status_changed:" + doc["number"])
        rows = client.ozon_bindings(doc["id"])
        expected = {(str(x["product_id"]), str(x["sku"])) for x in ozon_expected.values()}
        observed = {(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in rows}
        if len(rows) != 11 or observed != expected:
            raise RuntimeError("ozon_exact_binding_set_incomplete:" + doc["number"])
        statuses = collections.Counter(str(x.get("product_status_code") or "unknown") for x in rows)
        if statuses != {"approved": 11}:
            raise RuntimeError("ozon_product_binding_status_not_approved:" + doc["number"])
        ozon[doc["number"]] = {"certificate_id": doc["id"], "record_status": "approved",
            "expected_exact_bindings": 11, "visible_exact_bindings": len(rows),
            "binding_status_counts": dict(statuses)}

    wb_rows = []
    for offer, target in sorted(targets.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("wb_card_missing_or_duplicate:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(target.get("wb_nmID") or "")
                or sorted(set(code_values(card))) != ["9405420012"]):
            raise RuntimeError("wb_identity_or_scope_changed:" + offer)
        doc_rows = ((card.get("documents") or {}).get("items") or [])
        current_docs = {}
        for doc in DOCS:
            matches = [x for x in doc_rows if norm_number(x.get("number")) == norm_number(doc["number"])]
            exact = (len(matches) == 1 and str(matches[0].get("type")) == str(doc["wb_type"])
                     and str(matches[0].get("startDate", ""))[:10] == doc["issue"]
                     and str(matches[0].get("endDate", ""))[:10] == doc["expiry"]
                     and matches[0].get("isEndless") is False)
            verdict = matches[0].get("verdict") or {} if len(matches) == 1 else {}
            if not exact or verdict.get("verified") is not True or verdict.get("reason") != "valid":
                raise RuntimeError("wb_document_exact_valid_readback_missing:" + offer + ":" + doc["number"])
            current_docs[doc["number"]] = {"type": matches[0].get("type"),
                "startDate": matches[0].get("startDate"), "endDate": matches[0].get("endDate"),
                "isEndless": matches[0].get("isEndless"), "verdict": verdict}
        prior = wb_before.get(offer)
        if not prior or comparable_card(prior) != comparable_card(card):
            raise RuntimeError("wb_other_fields_changed_or_before_missing:" + offer)
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
            "documents": current_docs, "overall_verdict": (card.get("documents") or {}).get("overallVerdict"),
            "non_document_fields_unchanged": True})

    out = {"checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "read_only": True,
        "target_cards": 11, "ozon_documents": ozon,
        "ozon_all_records_approved": True, "ozon_exact_approved_bindings_per_document": 11,
        "wb_cards_with_both_exact_valid_documents": len(wb_rows),
        "wb_document_verdict_counts": {"valid": len(wb_rows) * 2},
        "wb_all_non_document_fields_unchanged": True, "wb_review_state_changed_by_agent": False,
        "wb_rows": wb_rows, "local_source_files_deleted": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({"artifact": OUT.name, "ozon_approved_bindings_per_document": 11,
        "wb_cards_with_both_exact_valid_documents": len(wb_rows),
        "wb_review_state_changed_by_agent": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
