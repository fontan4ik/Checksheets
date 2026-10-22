#!/usr/bin/env python3
"""Fresh read-only cross-platform verification before cleaning Navigator source PDFs."""
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
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

PREFLIGHT = HERE / "navigator_14009_93270_43404_preflight_20261022.json"
BEFORE = HERE / "navigator_14009_93270_43404_wb_before_20261022.json"
OUT = HERE / "navigator_14009_93270_43404_final_live_crossplatform_readback_20261022.json"
DOCS = [
    {"number": "ЕАЭС N RU Д-CN.РА08.В.93270/25", "type_code": "declaration", "wb_type": 2,
     "issue": "2025-10-06", "expiry": "2030-10-02", "id": 5945811},
    {"number": "ЕАЭС RU С-CN.АЯ46.В.43404/25", "type_code": "certificate_of_conformity", "wb_type": 1,
     "issue": "2025-10-03", "expiry": "2030-10-02", "id": 5945813},
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
    before = json.loads(BEFORE.read_text()).get("cards") or {}
    targets = {str(x["offer_id"]): x for x in pre["targets"]}
    if len(targets) != 74 or pre.get("ozon_eligible_targets") != 74 or pre.get("wb_eligible_targets") != 74:
        raise RuntimeError("preflight_target_scope_not_exactly_74")
    client = Client()
    records = all_records(client)
    ozon = {}
    for doc in DOCS:
        matches = [r for r in records if norm_number(r.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) != 1:
            raise RuntimeError("ozon_record_missing_or_duplicate:" + doc["number"])
        record = matches[0]
        if (record.get("type_code") != doc["type_code"] or record.get("status_code") != "approved"
                or str(record.get("issue_date", ""))[:10] != doc["issue"]
                or str(record.get("expire_date", ""))[:10] != doc["expiry"]
                or str(record.get("certificate_id")) != str(doc["id"])):
            raise RuntimeError("ozon_record_metadata_or_status_changed:" + doc["number"])
        bindings = client.ozon_bindings(int(doc["id"]))
        expected = {(str(x["product_id"]), str(x["sku"])) for x in targets.values()}
        observed = {(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings}
        if len(bindings) != 74 or observed != expected:
            raise RuntimeError("ozon_exact_binding_set_incomplete:" + doc["number"])
        ozon[doc["number"]] = {
            "certificate_id": doc["id"], "record_status": record["status_code"],
            "expected_exact_bindings": 74, "visible_exact_bindings": len(bindings),
            "binding_status_counts": dict(collections.Counter(
                str(x.get("product_status_code") or "unknown") for x in bindings)),
        }

    wb_rows = []
    for offer, target in sorted(targets.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("wb_card_missing_or_duplicate:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(target.get("wb_nmID") or "")
                or (card.get("brand") or "").strip().casefold() not in {"navigator", "navigator light"}
                or sorted(set(code_values(card))) != ["8539520009"]):
            raise RuntimeError("wb_identity_or_scope_changed:" + offer)
        docs = copy_documents(card)
        doc_readback = {}
        for doc in DOCS:
            same = [x for x in docs if norm_number(x.get("number")) == norm_number(doc["number"])]
            exact = (len(same) == 1 and str(same[0].get("type")) == str(doc["wb_type"])
                     and str(same[0].get("startDate", ""))[:10] == doc["issue"]
                     and str(same[0].get("endDate", ""))[:10] == doc["expiry"]
                     and same[0].get("isEndless") is False)
            verdict = (same[0].get("verdict") or {}) if len(same) == 1 else {}
            if not exact or verdict.get("verified") is not True or verdict.get("reason") != "valid":
                raise RuntimeError("wb_document_or_verdict_not_valid:" + offer + ":" + doc["number"])
            doc_readback[doc["number"]] = {"exact_metadata": True, "verdict": verdict}
        prior = before.get(offer)
        if not prior or comparable_card(prior) != comparable_card(card):
            raise RuntimeError("wb_other_fields_changed_or_before_missing:" + offer)
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                        "documents": doc_readback, "non_document_fields_unchanged": True})

    out = {"checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "read_only": True,
        "target_cards": 74, "ozon_documents": ozon,
        "ozon_all_records_approved": True, "ozon_exact_bindings_per_document": 74,
        "wb_cards_with_both_exact_valid_documents": len(wb_rows),
        "wb_document_verdict_counts": {"valid": len(wb_rows) * 2},
        "wb_all_non_document_fields_unchanged": True, "wb_review_left_pending": True,
        "wb_rows": wb_rows, "local_source_files_deleted": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({"artifact": OUT.name, "ozon_bindings_per_document": 74,
        "ozon_binding_statuses": {k: v["binding_status_counts"] for k, v in ozon.items()},
        "wb_cards_with_both_exact_valid_documents": len(wb_rows),
        "wb_review_left_pending": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
