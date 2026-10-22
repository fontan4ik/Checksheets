#!/usr/bin/env python3
"""Read-only, delayed cross-platform verification for the Jazzway PPC documents."""
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
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from preflight_jazzway_power_connectors_20261022 import DOCS, EXPIRY, ISSUE, OUT, TNVED  # noqa: E402

STATE = HERE / "jazzway_power_connectors_execution_20261022.json"
BEFORE = HERE / "jazzway_power_connectors_wb_before_20261022.json"
OUTFILE = HERE / "jazzway_power_connectors_final_crossplatform_readback_20261022.json"


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


def doc_signature(row: dict) -> tuple:
    return (str(row.get("type")), norm_number(row.get("number")),
            str(row.get("startDate", ""))[:10], str(row.get("endDate", ""))[:10],
            str(row.get("isEndless", "false")).lower())


def main() -> None:
    pre = json.loads(OUT.read_text())
    before = json.loads(BEFORE.read_text()).get("cards") or {}
    ozon_targets = {x["offer_id"]: x for x in pre["ozon_targets"]}
    wb_targets = {x["offer_id"]: x for x in pre["wb_targets"]}
    if set(ozon_targets) != set(wb_targets) or len(ozon_targets) != 36:
        raise RuntimeError("cross_platform_target_set_changed")
    client = Client()

    records = all_records(client)
    ozon_results = {}
    for document in DOCS:
        matches = [x for x in records
                   if norm_number(x.get("certificate_number")) == norm_number(document["number"])]
        if len(matches) != 1:
            raise RuntimeError("ozon_exact_record_missing_or_duplicate:" + document["number"])
        record = matches[0]
        if (record.get("type_code") != document["type_code"]
                or str(record.get("issue_date", ""))[:10] != ISSUE
                or str(record.get("expire_date", ""))[:10] != EXPIRY
                or record.get("status_code") != "approved"):
            raise RuntimeError("ozon_record_type_date_or_status_mismatch:" + document["number"])
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        target_pairs = {(str(row["product_id"]), str(row["sku"])) for row in ozon_targets.values()}
        observed_pairs = {(str(row.get("product_id") or ""), str(row.get("sku") or ""))
                          for row in bindings}
        if observed_pairs != target_pairs or len(bindings) != 36:
            raise RuntimeError("ozon_binding_set_not_exact:" + document["number"])
        status_counts = collections.Counter(
            str(row.get("product_status_code") or "unknown") for row in bindings)
        ozon_results[document["key"]] = {
            "number": document["number"], "certificate_id": record["certificate_id"],
            "type_code": record["type_code"], "record_status": record["status_code"],
            "issue_date": str(record.get("issue_date", ""))[:10],
            "expire_date": str(record.get("expire_date", ""))[:10],
            "expected_exact_bindings": 36, "visible_exact_bindings": len(bindings),
            "binding_status_counts": dict(status_counts), "unexpected_bindings": 0,
        }

    wb_results = []
    for offer, expected in sorted(wb_targets.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("wb_exact_card_missing_or_duplicate:" + offer)
        card = cards[0]
        tnved = sorted(set(code_values(card)))
        if (str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() not in {"jazzway", "jazz way"}
                or tnved != [TNVED]):
            raise RuntimeError("wb_card_identity_or_tnved_changed:" + offer)
        docs = copy_documents(card)
        doc_results = {}
        for document in DOCS:
            matches = [x for x in docs if norm_number(x.get("number")) == norm_number(document["number"])]
            exact = (len(matches) == 1 and str(matches[0].get("type")) == str(document["wb_type"])
                     and str(matches[0].get("startDate", ""))[:10] == ISSUE
                     and str(matches[0].get("endDate", ""))[:10] == EXPIRY
                     and str(matches[0].get("isEndless", "false")).lower() not in {"true", "1"})
            if not exact:
                raise RuntimeError("wb_document_exact_metadata_missing:" + offer + ":" + document["key"])
            doc_results[document["key"]] = {
                "number": matches[0].get("number"), "type": matches[0].get("type"),
                "startDate": matches[0].get("startDate"), "endDate": matches[0].get("endDate"),
                "isEndless": matches[0].get("isEndless"), "verdict": matches[0].get("verdict"),
            }
        old = before.get(offer)
        if not old:
            raise RuntimeError("wb_before_snapshot_missing:" + offer)
        prior_signatures = {doc_signature(x) for x in copy_documents(old)}
        current_signatures = {doc_signature(x) for x in docs}
        if not prior_signatures.issubset(current_signatures):
            raise RuntimeError("wb_prior_documents_lost:" + offer)
        if comparable_card(old) != comparable_card(card):
            raise RuntimeError("wb_non_document_fields_changed:" + offer)
        wb_results.append({
            "offer_id": offer, "nmID": str(card.get("nmID")), "brand": card.get("brand"),
            "tnved": tnved, "documents": doc_results,
            "prior_documents_preserved": True, "non_document_fields_unchanged": True,
            "overall_verdict": (card.get("documents") or {}).get("overallVerdict"),
        })

    wb_verdicts = collections.Counter(
        str(((row.get("documents") or {}).get(DOCS[0]["key"], {}).get("verdict") or {}).get("reason")
            or "no_document_verdict") for row in wb_results)
    result = {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "read_only": True,
        "brand": "Jazzway",
        "scope": {"tnved": TNVED, "offers": 36, "document_numbers": [x["number"] for x in DOCS]},
        "ozon": {"exact_approved_documents": len(ozon_results), "documents": ozon_results,
                 "all_records_approved": True, "all_bindings_exact": True},
        "wb": {"target_cards": 36, "cards_with_both_exact_documents": len(wb_results),
               "all_prior_documents_preserved": True, "all_non_document_fields_unchanged": True,
               "verdict_reason_counts": dict(wb_verdicts), "review_left_pending": True,
               "verdicts_manually_changed": False, "cards": wb_results},
        "local_source_files_deleted": False,
    }
    temp = OUTFILE.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUTFILE)
    state = json.loads(STATE.read_text())
    state.update({"phase": "cross_marketplace_readback_complete", "finished_at_utc": result["checked_at_utc"],
        "final_readback_artifact": OUTFILE.name, "ozon_final_status_counts": {"approved": 2},
        "ozon_final_exact_bindings_per_document": 36, "wb_final_exact_cards_with_both_documents": 36,
        "wb_review_left_pending": True, "local_source_files_deleted": False})
    temp_state = STATE.with_suffix(".tmp")
    temp_state.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temp_state.replace(STATE)
    print(json.dumps({"artifact": OUTFILE.name, "ozon_records": 2,
        "ozon_bindings_per_document": 36, "binding_statuses": {k: v["binding_status_counts"] for k, v in ozon_results.items()},
        "wb_cards_with_both_exact_documents": len(wb_results),
        "wb_verdict_reason_counts": dict(wb_verdicts), "wb_review_left_pending": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
