#!/usr/bin/env python3
"""Attach the exact active Navigator 47173/26 certificate to one Ozon SKU and WB card.

Writes are guarded by fresh product/card reads, exact source hash checks, a durable
pre-write snapshot, and a no-retry mutation journal. The local PDF is retained.
"""
from __future__ import annotations

import base64
import collections
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)

PREFLIGHT = HERE / "navigator_47173_live_preflight_20261024.json"
STATE = HERE / "navigator_47173_execution_20261024.json"
BEFORE = HERE / "navigator_47173_wb_before_20261024.json"
READBACK = HERE / "navigator_47173_readback_20261024.json"
JOURNAL = HERE / "navigator_47173_mutation_journal_20261024.jsonl"

DOC = {
    "number": "ЕАЭС RU С-CN.АЯ46.В.47173/26",
    "type_code": "certificate_of_conformity",
    "wb_type": 1,
    "issue_date": "2026-04-10",
    "expire_date": "2031-04-09",
    "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3661853/product",
    "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_61758_99438ddb1a03.pdf",
    "sha256": "99438ddb1a032b0fc542299cf7f80c1b35d0e736dc09955bcb206b8665273f22",
}
OZON_TARGET = {"offer_id": "61758-1", "product_id": "6023704564", "sku": "5523867268"}
WB_TARGET = {"offer_id": "61758-1", "nmID": "1507703964"}
ALLOWED_TNVED = {"8536508008"}


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def journal(value: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


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


def ozon_identity(client: Client) -> dict:
    offer = OZON_TARGET["offer_id"]
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": [offer]}, "limit": 1}).get("result") or []
    if len(products) != 1 or len(attrs) != 1:
        raise RuntimeError("ozon_live_product_or_attributes_not_unique")
    product, attr = products[0], attrs[0]
    if (str(product.get("offer_id")) != offer
            or str(product.get("product_id") or product.get("id")) != OZON_TARGET["product_id"]
            or str(product.get("sku")) != OZON_TARGET["sku"]
            or product.get("is_archived") is not False):
        raise RuntimeError("ozon_live_product_identity_conflict")
    values = {str(x.get("id")): [str(v.get("value") or "").strip()
               for v in x.get("values") or [] if str(v.get("value") or "").strip()]
              for x in attr.get("attributes") or []}
    brands = values.get("85", [])
    tnved = sorted({x.split(" - ", 1)[0].strip() for x in values.get("22232", [])})
    if (not brands or any("navigator" not in x.casefold() for x in brands)
            or tnved != sorted(ALLOWED_TNVED)):
        raise RuntimeError("ozon_live_brand_or_tnved_conflict")
    return {"offer_id": offer, "product_id": OZON_TARGET["product_id"], "sku": OZON_TARGET["sku"],
            "name": product.get("name"), "brands": brands, "tnved": tnved}


def card_tnved(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = item.get("value")
        out.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in out if str(x).strip()})


def wb_identity(client: Client) -> tuple[dict, dict]:
    cards = client.wb_cards(WB_TARGET["offer_id"])
    if len(cards) != 1:
        raise RuntimeError("wb_live_card_not_unique")
    card = cards[0]
    tnved = card_tnved(card)
    if (str(card.get("vendorCode")) != WB_TARGET["offer_id"]
            or str(card.get("nmID")) != WB_TARGET["nmID"]
            or str(card.get("brand") or "").strip().casefold() != "navigator"
            or tnved != sorted(ALLOWED_TNVED)):
        raise RuntimeError("wb_live_card_identity_or_tnved_conflict")
    return card, {"offer_id": WB_TARGET["offer_id"], "nmID": WB_TARGET["nmID"],
                  "brand": card.get("brand"), "tnved": tnved}


def create_ozon_record(client: Client, seed_sku: str) -> tuple[dict | None, dict]:
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(DOC["number"])]
    if len(matches) > 1:
        raise RuntimeError("ozon_duplicate_document_records")
    if matches:
        record = matches[0]
        if (record.get("type_code") != DOC["type_code"]
                or str(record.get("issue_date", ""))[:10] != DOC["issue_date"]
                or str(record.get("expire_date", ""))[:10] != DOC["expire_date"]):
            raise RuntimeError("ozon_existing_document_metadata_conflict")
        return record, {"created": False, "already_present": True}

    year, month, day = map(int, DOC["expire_date"].split("-"))
    payload = {"params": {
        "name": "Документ " + DOC["number"],
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": DOC["number"],
        "issue_date": wb_datetime(DOC["issue_date"]),
        "expired_date": {"date": {"day": day, "month": month, "year": year}},
        "skus": [str(seed_sku)],
        "product_type": "UNKNOWN",
        "link_to_registry": DOC["registry_url"],
        "files": [{"file_content": base64.b64encode(DOC["file"].read_bytes()).decode("ascii"),
                   "name": DOC["file"].name}],
    }}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_create_request_too_large")
    marker = {"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
              "document_number": DOC["number"], "phase": "prepared",
              "payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded),
              "seed_sku": str(seed_sku)}
    journal(marker)
    state = json.loads(STATE.read_text())
    state["phase"] = "ozon_create_started"
    save(STATE, state)
    response, error = None, None
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:  # uncertain writes are reconciled, never retried
        error = type(exc).__name__
    journal({**marker, "at": now(), "phase": "response" if response is not None else "uncertain",
             "response": response, "error_type": error})

    found = []
    for attempt in range(6):
        found = [x for x in list_certificates(client)
                 if norm_number(x.get("certificate_number")) == norm_number(DOC["number"])]
        if found or attempt == 5:
            break
        time.sleep(2)
    if len(found) != 1:
        return None, {"created": bool((response or {}).get("certificate_id")),
                      "outcome": "uncertain_no_unique_record_visible_no_retry", "error_type": error,
                      "create_response": response}
    record = found[0]
    if (record.get("type_code") != DOC["type_code"]
            or str(record.get("issue_date", ""))[:10] != DOC["issue_date"]
            or str(record.get("expire_date", ""))[:10] != DOC["expire_date"]):
        raise RuntimeError("ozon_created_document_metadata_conflict")
    states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
    if response is None or response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        return record, {"created": True, "outcome": "visible_but_create_response_not_fully_validated",
                        "create_response": response, "error_type": error}
    return record, {"created": True, "outcome": "visible_and_create_response_validated",
                    "create_response": response}


def bind_ozon(client: Client, record: dict) -> dict:
    cid = int(record["certificate_id"])
    expected = (OZON_TARGET["product_id"], OZON_TARGET["sku"])
    current = client.ozon_bindings(cid)
    seen = [(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in current]
    if any(not p for p, _ in seen) or len(seen) != len(set(seen)):
        raise RuntimeError("ozon_existing_binding_duplicate_or_missing_id")
    if any(pair != expected for pair in seen):
        raise RuntimeError("ozon_existing_record_has_unexpected_bindings")
    if any(str(x.get("product_status_code") or "").casefold() in
           {"declined", "rejected", "cancelled", "invalid"} for x in current):
        raise RuntimeError("ozon_existing_binding_declined")
    if expected not in seen:
        request = {"certificate_id": cid, "skus": [expected[1]]}
        marker = {"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                  "document_number": DOC["number"], "certificate_id": cid,
                  "phase": "prepared", "skus": [expected[1]],
                  "payload_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest()}
        journal(marker)
        state = json.loads(STATE.read_text())
        state["phase"] = "ozon_bind_started"
        save(STATE, state)
        response, error = None, None
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
        except Exception as exc:
            error = type(exc).__name__
        journal({**marker, "at": now(), "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": error})
    live = client.ozon_bindings(cid)
    exact = [x for x in live if (str(x.get("product_id")), str(x.get("sku"))) == expected]
    extra = [x for x in live if (str(x.get("product_id")), str(x.get("sku"))) != expected]
    info = client.call("ozon", "/v1/product/certificate/info",
                       {"certificate_number": DOC["number"]}).get("result") or {}
    return {"certificate_id": cid, "record_status": info.get("status_code"),
            "expected_bindings": 1, "visible_exact_bindings": len(exact),
            "binding_statuses": [x.get("product_status_code") for x in exact],
            "unexpected_binding_count": len(extra), "binding_confirmed": len(exact) == 1 and not extra}


def apply_wb(client: Client, card: dict) -> dict:
    wanted = [{"type": DOC["wb_type"], "number": DOC["number"],
               "startDate": wb_datetime(DOC["issue_date"]),
               "endDate": wb_datetime(DOC["expire_date"]), "isEndless": False}]
    existing = copy_documents(card)
    same = [x for x in existing if norm_number(x.get("number")) == norm_number(DOC["number"])]
    if same and (len(same) != 1 or doc_key(same[0]) != doc_key(wanted[0])
                 or str(same[0].get("startDate", ""))[:10] != DOC["issue_date"]
                 or str(same[0].get("endDate", ""))[:10] != DOC["expire_date"]
                 or same[0].get("isEndless") is not False):
        raise RuntimeError("wb_same_number_metadata_conflict")
    payload = runner.merge_wb(card, wanted)
    save(BEFORE, {"checked_at_utc": now(), "offer_id": WB_TARGET["offer_id"],
                  "nmID": WB_TARGET["nmID"], "card": card,
                  "prior_document_count": len(existing), "already_exact": payload is None})
    result = {"updated": False, "response": None, "error_type": None}
    if payload is not None:
        entry = {"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "document_number": DOC["number"], "phase": "prepared", "offer_id": WB_TARGET["offer_id"],
                 "nmID": WB_TARGET["nmID"],
                 "payload_sha256": hashlib.sha256(json.dumps([payload], sort_keys=True,
                    ensure_ascii=False).encode()).hexdigest()}
        journal(entry)
        state = json.loads(STATE.read_text())
        state["phase"] = "wb_update_started"
        save(STATE, state)
        try:
            result["response"] = client.call("wb", "/content/v2/cards/update", [payload], mutation=True)
            result["updated"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
        journal({**entry, "at": now(), "phase": "response" if result["response"] is not None else "uncertain",
                 "response": result["response"], "error_type": result["error_type"]})
    live_cards = client.wb_cards(WB_TARGET["offer_id"])
    if len(live_cards) != 1:
        raise RuntimeError("wb_readback_card_not_unique")
    live = live_cards[0]
    docs = copy_documents(live)
    found = [x for x in docs if norm_number(x.get("number")) == norm_number(DOC["number"])
             and doc_key(x) == doc_key(wanted[0])
             and str(x.get("startDate", ""))[:10] == DOC["issue_date"]
             and str(x.get("endDate", ""))[:10] == DOC["expire_date"]
             and x.get("isEndless") is False]
    before = json.loads(BEFORE.read_text())["card"]
    old_sigs = {(doc_key(x), str(x.get("number")), str(x.get("startDate", ""))[:10],
                 str(x.get("endDate", ""))[:10], bool(x.get("isEndless"))) for x in existing}
    new_sigs = {(doc_key(x), str(x.get("number")), str(x.get("startDate", ""))[:10],
                 str(x.get("endDate", ""))[:10], bool(x.get("isEndless"))) for x in docs}
    verdicts = [x.get("verdict") for x in found]
    review = "valid" if len(found) == 1 and isinstance(verdicts[0], dict) \
             and verdicts[0].get("verified") is True and verdicts[0].get("reason") == "valid" \
             else "pending_review_or_unverified"
    return {**result, "readback_exact_document_count": len(found), "document_review": review,
            "prior_documents_preserved": old_sigs <= new_sigs,
            "unrelated_card_fields_preserved": comparable_card(live) == comparable_card(before),
            "wb_left_for_marketplace_review": review != "valid"}


def main() -> None:
    for path in (STATE, BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    pre = json.loads(PREFLIGHT.read_text())
    source = DOC["file"]
    if (pre.get("read_only") is not True or pre.get("no_marketplace_writes_sent") is not True
            or pre.get("ozon", {}).get("target", {}).get("offer_id") != OZON_TARGET["offer_id"]
            or pre.get("wb", {}).get("target", {}).get("nmID") != WB_TARGET["nmID"]
            or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != DOC["sha256"]):
        raise RuntimeError("preflight_or_source_hash_conflict")
    client = Client()
    ozon, wb_card = ozon_identity(client), None
    wb_card, wb = wb_identity(client)
    state = {"started_at_utc": now(), "phase": "fresh_identities_verified",
             "document_number": DOC["number"], "source_sha256": DOC["sha256"],
             "source_file_retained": True, "ozon_target": ozon, "wb_target": wb,
             "fsa_sample_date_condition": "certificate sample dated 2026-02; stock-lot date not independently verified",
             "local_source_file_deleted": False}
    save(STATE, state)

    ozon_result = {"phase": "not_processed"}
    try:
        record, create = create_ozon_record(client, ozon["sku"])
        if record is None:
            ozon_result = {"phase": "record_not_uniquely_visible_no_binding", "create": create}
        elif create.get("outcome") == "visible_but_create_response_not_fully_validated":
            ozon_result = {"phase": "record_visible_create_response_unvalidated_no_binding",
                           "create": create, "record_status": record.get("status_code")}
        elif str(record.get("status_code") or "").casefold() in {"declined", "rejected", "cancelled", "invalid"}:
            ozon_result = {"phase": "record_declined_no_binding", "create": create,
                           "record_status": record.get("status_code")}
        else:
            binding = bind_ozon(client, record)
            ozon_result = {"phase": "readback_complete", "create": create, "binding": binding}
    except Exception as exc:
        ozon_result = {"phase": "processing_error", "error_type": type(exc).__name__, "detail": str(exc)[:400]}
    state = json.loads(STATE.read_text())
    state["ozon"] = ozon_result
    state["phase"] = "ozon_reconciled"
    save(STATE, state)

    wb_result = {"phase": "not_processed"}
    try:
        wb_result = {"phase": "readback_complete", **apply_wb(client, wb_card)}
    except Exception as exc:
        wb_result = {"phase": "processing_error", "error_type": type(exc).__name__, "detail": str(exc)[:400]}
    state = json.loads(STATE.read_text())
    state["wb"] = wb_result
    state["phase"] = "finished_readback_complete" if (
        ozon_result.get("binding", {}).get("binding_confirmed") is True
        and wb_result.get("readback_exact_document_count") == 1
        and wb_result.get("prior_documents_preserved") is True
        and wb_result.get("unrelated_card_fields_preserved") is True
    ) else "finished_with_readback_problems"
    state["finished_at_utc"] = now()
    save(STATE, state)
    save(READBACK, {"checked_at_utc": now(), "document_number": DOC["number"],
                    "ozon": ozon_result, "wb": wb_result,
                    "local_source_file_deleted": False})
    print(json.dumps({"state": str(STATE), "readback": str(READBACK),
                      "phase": state["phase"], "ozon": ozon_result, "wb": wb_result,
                      "local_source_file_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
