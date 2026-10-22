#!/usr/bin/env python3
"""Bind one freshly verified Feron LD product to its approved certificate."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
sys.path.insert(0, str(API.parent / "certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

PREFLIGHT = HERE / "feron_01354_target_preflight_20261022.json"
STATE = HERE / "feron_01354_48881_execution_20261022.json"
READBACK = HERE / "feron_01354_48881_readback_20261022.json"
JOURNAL = HERE / "feron_01354_48881_journal_20261022.jsonl"
NUMBER = "ЕАЭС RU C-CN.НВ85.В.01354/22"
CERTIFICATE_ID = 5909852
OFFER_ID = "48881-1"
PRODUCT_ID = "2038491225"
SKU = "2340237155"
ALLOWED_TNVED = {"8537109100", "8537109800"}


def atomic(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def jsonl(path: pathlib.Path, row: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def main() -> None:
    for path in (STATE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError(f"execution_artifact_exists_review_first:{path.name}")
    preflight = json.loads(PREFLIGHT.read_text())
    if (preflight.get("offer_id") != OFFER_ID
            or preflight.get("product_id") != PRODUCT_ID
            or preflight.get("sku") != SKU
            or preflight.get("brand_values") != ["Feron"]
            or preflight.get("ozon_certificate", {}).get("certificate_id") != CERTIFICATE_ID
            or preflight.get("ozon_certificate", {}).get("status_code") != "approved"
            or str(preflight.get("ozon_certificate", {}).get("issue_date", ""))[:10] != "2022-08-29"
            or str(preflight.get("ozon_certificate", {}).get("expire_date", ""))[:10] != "2027-08-28"
            or preflight.get("already_bound")
            or preflight.get("source_pdf_sha256") != "d827db4ec09ead602917154fc8e630630ba0e28fd0a370ab4df932a4ab0e75cd"):
        raise RuntimeError("saved_preflight_conflict")

    c = Client()
    product = c.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER_ID]}).get("items") or []
    attrs = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [OFFER_ID]}, "limit": 1
    }).get("result") or []
    if len(product) != 1 or len(attrs) != 1:
        raise RuntimeError("fresh_ozon_product_or_attribute_read_incomplete")
    p, a = product[0], attrs[0]
    if (str(p.get("offer_id")) != OFFER_ID
            or str(p.get("product_id") or p.get("id")) != PRODUCT_ID
            or str(p.get("sku")) != SKU
            or p.get("is_archived") is not False):
        raise RuntimeError("fresh_ozon_product_identity_changed")
    values = {str(x.get("id")): [str(v.get("value") or "").strip()
               for v in x.get("values") or [] if str(v.get("value") or "").strip()]
              for x in a.get("attributes") or []}
    tnved = sorted({v.split(" - ", 1)[0].strip() for v in values.get("22232", [])})
    model_values = values.get("9048", [])
    if values.get("85") != ["Feron"] or not set(tnved) or not set(tnved) <= ALLOWED_TNVED:
        raise RuntimeError("fresh_ozon_brand_or_tnved_out_of_scope")
    if not any("LD" in v.upper() for v in model_values) and "LD" not in str(p.get("name") or "").upper():
        raise RuntimeError("fresh_ozon_model_out_of_scope")

    records = []
    for page in range(1, 101):
        data = c.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("fresh_certificate_list_incomplete")
        records.extend(batch)
        if page >= int(data.get("page_count") or 0):
            break
    else:
        raise RuntimeError("fresh_certificate_list_page_limit")
    found = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(found) != 1:
        raise RuntimeError(f"fresh_exact_certificate_count:{len(found)}")
    cert = found[0]
    if (int(cert.get("certificate_id") or 0) != CERTIFICATE_ID
            or cert.get("type_code") != "certificate_of_conformity"
            or cert.get("status_code") != "approved"
            or str(cert.get("issue_date", ""))[:10] != "2022-08-29"
            or str(cert.get("expire_date", ""))[:10] != "2027-08-28"):
        raise RuntimeError("fresh_certificate_metadata_or_status_changed")

    bindings = c.ozon_bindings(CERTIFICATE_ID)
    by_product = {str(x.get("product_id")): x for x in bindings}
    existing = by_product.get(PRODUCT_ID)
    if existing:
        if str(existing.get("sku")) != SKU:
            raise RuntimeError("existing_binding_identity_conflict")
        raise RuntimeError("target_binding_already_visible_reconcile_only")

    request = {"certificate_id": CERTIFICATE_ID, "skus": [SKU]}
    entry = {"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
             "request_sha256": hashlib.sha256(json.dumps(request, ensure_ascii=False,
                 separators=(",", ":")).encode()).hexdigest(), "phase": "prepared",
             "offer_id": OFFER_ID, "product_id": PRODUCT_ID, "sku": SKU}
    jsonl(JOURNAL, entry)
    atomic(STATE, {"started_at_utc": now(), "phase": "bind_prepared", "offer_id": OFFER_ID,
                   "product_id": PRODUCT_ID, "sku": SKU, "certificate_id": CERTIFICATE_ID,
                   "wb_write_sent": False, "local_pdf_deleted": False})
    try:
        response = c.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
    except Exception as exc:
        entry.update(phase="uncertain", finished_at=now(), error_type=type(exc).__name__)
        jsonl(JOURNAL, entry)
        atomic(STATE, {"started_at_utc": entry["at"], "phase": "bind_uncertain",
                       "offer_id": OFFER_ID, "product_id": PRODUCT_ID, "sku": SKU,
                       "certificate_id": CERTIFICATE_ID, "wb_write_sent": False,
                       "local_pdf_deleted": False})
        raise RuntimeError("bind_outcome_uncertain_readback_required_before_retry") from None
    entry.update(phase="response", finished_at=now(), response=response)
    jsonl(JOURNAL, entry)
    if response.get("result") is not True:
        atomic(STATE, {"started_at_utc": entry["at"], "phase": "bind_rejected",
                       "response": response, "wb_write_sent": False, "local_pdf_deleted": False})
        raise RuntimeError("ozon_bind_not_accepted")
    atomic(STATE, {"started_at_utc": entry["at"], "phase": "bind_accepted",
                   "response": response, "offer_id": OFFER_ID, "product_id": PRODUCT_ID,
                   "sku": SKU, "certificate_id": CERTIFICATE_ID, "wb_write_sent": False,
                   "local_pdf_deleted": False})

    observed = None
    info = None
    for attempt in range(1, 7):
        info = c.call("ozon", "/v1/product/certificate/info", {"certificate_number": cert["certificate_number"]}).get("result") or {}
        live = c.ozon_bindings(CERTIFICATE_ID)
        hit = next((x for x in live if str(x.get("product_id")) == PRODUCT_ID), None)
        if hit:
            if str(hit.get("sku")) != SKU:
                raise RuntimeError("readback_binding_identity_mismatch")
            observed = hit
            break
        if attempt < 6:
            time.sleep(2)
    if not observed:
        atomic(STATE, {"started_at_utc": entry["at"], "phase": "accepted_readback_pending",
                       "response": response, "wb_write_sent": False, "local_pdf_deleted": False})
        raise RuntimeError("accepted_write_not_visible_yet_no_retry")

    wb_cards = c.wb_cards(OFFER_ID)
    if len(wb_cards) != 1 or str(wb_cards[0].get("nmID")) != str(preflight.get("wb_nmID")):
        raise RuntimeError("wb_card_identity_changed_after_ozon_binding")
    wbdocs = ((wb_cards[0].get("documents") or {}).get("items") or [])
    exact_wb = [d for d in wbdocs if norm_number(d.get("number")) == norm_number(NUMBER)
                and str(d.get("startDate", ""))[:10] == "2022-08-29"
                and str(d.get("endDate", ""))[:10] == "2027-08-28"]
    if len(exact_wb) != 1:
        raise RuntimeError("wb_document_not_exactly_visible_or_date_conflict")
    result = {"checked_at_utc": now(), "offer_id": OFFER_ID, "product_id": PRODUCT_ID,
              "sku": SKU, "product_name": p.get("name"), "ozon_brand": values.get("85"),
              "ozon_model_values": model_values, "ozon_tnved_codes": tnved,
              "certificate_id": CERTIFICATE_ID, "certificate_number": cert.get("certificate_number"),
              "certificate_status": info.get("status_code"),
              "ozon_binding_visible": True, "ozon_binding_sku": observed.get("sku"),
              "ozon_binding_status": observed.get("product_status_code"),
              "wb_nmID": str(wb_cards[0].get("nmID")), "wb_exact_document_visible": True,
              "wb_document_verdict": exact_wb[0].get("verdict"),
              "wb_write_sent": False, "wb_left_for_marketplace_review": True,
              "local_source_pdf_deleted": False}
    atomic(READBACK, result)
    state = {"completed_at_utc": now(), "phase": "finished_verified_readback",
             "offer_id": OFFER_ID, "product_id": PRODUCT_ID, "sku": SKU,
             "certificate_id": CERTIFICATE_ID, "write_response": response,
             "verification": result, "wb_write_sent": False, "local_pdf_deleted": False}
    atomic(STATE, state)
    print(json.dumps({"state_file": str(STATE), "readback_file": str(READBACK), **result},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
