#!/usr/bin/env python3
"""Read-only delayed reconciliation for Navigator certificate 47173/26."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, comparable_card,
)

STATE = HERE / "navigator_47173_execution_20261024.json"
BEFORE = HERE / "navigator_47173_wb_before_20261024.json"
READBACK = HERE / "navigator_47173_readback_20261024.json"
NUMBER = "ЕАЭС RU С-CN.АЯ46.В.47173/26"
OFFER = "61758-1"
PRODUCT_ID = "6023704564"
SKU = "5523867268"
NM_ID = "1507703964"
ISSUE = "2026-04-10"
EXPIRY = "2031-04-09"


def atomic(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    client = Client()
    records = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) != 1:
        raise RuntimeError("ozon_exact_certificate_record_not_unique")
    record = records[0]
    bindings = client.ozon_bindings(int(record["certificate_id"]))
    exact_bindings = [x for x in bindings
                      if str(x.get("product_id")) == PRODUCT_ID and str(x.get("sku")) == SKU]
    ozon = {"record_count": len(records), "certificate_id": str(record.get("certificate_id")),
            "record_status": record.get("status_code"), "type_code": record.get("type_code"),
            "issue_date": str(record.get("issue_date", ""))[:10],
            "expire_date": str(record.get("expire_date", ""))[:10],
            "expected_exact_binding_count": 1, "visible_exact_binding_count": len(exact_bindings),
            "binding_statuses": [x.get("product_status_code") for x in exact_bindings],
            "unexpected_binding_count": sum(
                (str(x.get("product_id")), str(x.get("sku"))) != (PRODUCT_ID, SKU) for x in bindings)}
    ozon["confirmed"] = (ozon["record_status"] == "approved"
                         and ozon["type_code"] == "certificate_of_conformity"
                         and ozon["issue_date"] == ISSUE and ozon["expire_date"] == EXPIRY
                         and len(exact_bindings) == 1
                         and exact_bindings[0].get("product_status_code") == "approved"
                         and ozon["unexpected_binding_count"] == 0)

    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError("wb_exact_card_not_unique")
    card = cards[0]
    docs = copy_documents(card)
    found = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)
             and doc_key(x) == (1, norm_number(NUMBER))
             and str(x.get("startDate", ""))[:10] == ISSUE
             and str(x.get("endDate", ""))[:10] == EXPIRY
             and x.get("isEndless") is False]
    before = json.loads(BEFORE.read_text())
    if (str(card.get("vendorCode")) != OFFER or str(card.get("nmID")) != NM_ID
            or str(card.get("brand") or "").casefold() != "navigator"):
        raise RuntimeError("wb_card_identity_changed")
    old_sigs = {(doc_key(x), norm_number(x.get("number")), str(x.get("startDate", ""))[:10],
                 str(x.get("endDate", ""))[:10], bool(x.get("isEndless")))
                for x in copy_documents(before["card"])}
    new_sigs = {(doc_key(x), norm_number(x.get("number")), str(x.get("startDate", ""))[:10],
                 str(x.get("endDate", ""))[:10], bool(x.get("isEndless"))) for x in docs}
    verdict = found[0].get("verdict") if len(found) == 1 else None
    wb = {"card_count": len(cards), "nmID": str(card.get("nmID")),
          "exact_metadata_count": len(found), "document_verdict": verdict,
          "overall_verdict": (card.get("documents") or {}).get("overallVerdict"),
          "prior_documents_preserved": old_sigs <= new_sigs,
          "unrelated_card_fields_preserved": comparable_card(card) == comparable_card(before["card"]),
          "document_visible": len(found) == 1}
    wb["review_status"] = "valid" if (isinstance(verdict, dict)
        and verdict.get("verified") is True and verdict.get("reason") == "valid") else "pending_review_or_unverified"
    wb["confirmed_card_attachment"] = (wb["document_visible"]
                                        and wb["prior_documents_preserved"]
                                        and wb["unrelated_card_fields_preserved"])

    result = {"checked_at_utc": now(), "document_number": NUMBER, "ozon": ozon, "wb": wb,
              "wb_left_for_marketplace_review": wb["review_status"] != "valid",
              "local_source_file_deleted": False}
    atomic(READBACK, result)
    state = json.loads(STATE.read_text())
    state["ozon_readback"] = ozon
    state["wb_readback"] = wb
    state["phase"] = ("document_readback_verified_wb_review_pending"
                      if ozon["confirmed"] and wb["confirmed_card_attachment"]
                      and wb["review_status"] != "valid"
                      else "readback_reconciled_with_remaining_problems")
    state["finished_at_utc"] = now()
    state["local_source_file_deleted"] = False
    atomic(STATE, state)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
