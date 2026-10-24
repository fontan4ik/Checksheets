#!/usr/bin/env python3
"""Upload Gauss declaration RU Д-CN.РА04.В.36172/23 to exact GFL offers."""
from __future__ import annotations

import base64
import collections
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, comparable_card,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_resume_20261023.csv"
GAP_AUDIT = HERE / "confirmed_source_gaps_audit_resume_20261024.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/46f6a73ea3c97e66d057a8fd.pdf"
OUT = HERE / "gauss_36172_execution_20261024.json"
JOURNAL = HERE / "gauss_36172_execution_journal_20261024.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА04.В.36172/23"
ISSUE = "2023-06-02"
EXPIRE = "2028-06-01"
RECORD_ID = "17751189"
REGISTRY = "https://pub.fsa.gov.ru/rds/declaration/view/17751189/common"
EXPECTED_OFFERS = {"GF102-1", "GF201-1"}
EXPECTED_TNVED = {"8513100000"}
WB_DOC = {"type": 2, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
          "endDate": EXPIRE + "T00:00:00Z", "isEndless": False}


def atomic(path: Path, data) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def log(event: str, **fields) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now(), "event": event, **fields}, ensure_ascii=False) + "\n")


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


def wb_tnved(card: dict) -> set[str]:
    found = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            values = item.get("value")
            values = values if isinstance(values, list) else [values]
            found.update(str(x).split(" - ", 1)[0].strip() for x in values if str(x or "").strip())
    return found


def find_source_hash() -> str:
    audit = json.loads(GAP_AUDIT.read_text())
    hits = [x for x in audit.get("candidate_source_groups") or []
            if x.get("document_number") == "RU Д-CN.PA04.B.36172/23"
            and "GF102-1" in x.get("offer_examples", [])]
    if len(hits) != 1 or not hits[0].get("sha256_matches"):
        raise RuntimeError("source_hash_not_uniquely_verified_in_gap_audit")
    return str(hits[0]["actual_sha256"])


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("execution_artifacts_exist_inspect_before_any_write")
    expected_hash = find_source_hash()
    if not SOURCE.is_file():
        raise RuntimeError("official_gauss_source_pdf_missing")
    actual_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError("official_gauss_source_pdf_hash_mismatch")

    assignment_rows = [r for r in csv.DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline=""))
                       if "36172" in r.get("number", "")]
    targets_by_offer = {r["offer_id"]: r for r in assignment_rows}
    if set(targets_by_offer) != EXPECTED_OFFERS or len(assignment_rows) != 2:
        raise RuntimeError("assignment_target_set_changed")
    if any(r.get("brand") != "Gauss" or r.get("type") != "declaration"
           or r.get("source_type_conflict") not in ("False", "false", "0")
           for r in assignment_rows):
        raise RuntimeError("source_assignment_brand_or_document_type_conflict")

    client = Client()
    offers = sorted(EXPECTED_OFFERS)
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pmap = collections.defaultdict(list)
    amap = collections.defaultdict(list)
    for p in products:
        pmap[str(p.get("offer_id"))].append(p)
    for a in attrs:
        amap[str(a.get("offer_id"))].append(a)

    ozon_targets = {}
    for offer in offers:
        source = targets_by_offer[offer]
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("ozon_offer_not_unique:" + offer)
        product, attrs_row = pmap[offer][0], amap[offer][0]
        values = {str(x.get("id")): [str(v.get("value") or "").strip()
                   for v in x.get("values") or [] if str(v.get("value") or "").strip()]
                  for x in attrs_row.get("attributes") or []}
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        brand = values.get("85", [])
        tnved = {x.split(" - ", 1)[0].strip() for x in values.get("22232", [])}
        if (product_id != str(source.get("ozon_product_id"))
                or sku != str(source.get("ozon_sku"))
                or product.get("is_archived") is not False
                or brand != ["Gauss"] or tnved != EXPECTED_TNVED):
            raise RuntimeError("ozon_live_identity_brand_or_tnved_conflict:" + offer)
        model = "GFL102" if offer == "GF102-1" else "GFL201"
        if model not in str(product.get("name") or "").upper():
            raise RuntimeError("ozon_live_model_not_in_fsa_gfl_scope:" + offer)
        ozon_targets[offer] = {"offer_id": offer, "product_id": product_id, "sku": sku,
                               "name": product.get("name"), "brand": brand, "tnved": sorted(tnved),
                               "model": model}

    wb_before = {}
    for offer in offers:
        source = targets_by_offer[offer]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_card_not_unique:" + offer)
        card = cards[0]
        if (str(card.get("nmID")) != str(source.get("wb_nmID"))
                or card.get("vendorCode") != offer
                or str(card.get("brand") or "").strip().casefold() != "gauss"
                or wb_tnved(card) != EXPECTED_TNVED):
            raise RuntimeError("wb_live_identity_brand_or_tnved_conflict:" + offer)
        existing_same = [x for x in copy_documents(card)
                         if norm_number(x.get("number")) == norm_number(NUMBER)]
        if existing_same:
            raise RuntimeError("wb_exact_number_already_present_reconcile_before_update:" + offer)
        wb_before[offer] = card

    certificates = list_certificates(client)
    existing = [x for x in certificates if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if existing:
        raise RuntimeError("ozon_exact_record_already_exists_inspect_before_create")

    option_response = client.call("ozon", "/v2/product/certification/options", {})
    option_values = {x.get("name"): {v.get("value") for v in x.get("variants") or []}
                     for x in option_response.get("option") or []}
    if "DECLARATION" not in option_values.get("CERTIFICATE_TYPE", set()):
        raise RuntimeError("ozon_declaration_type_not_supported")
    params_body = {
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "name": "Декларация о соответствии № " + NUMBER,
        "number": NUMBER, "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": 1, "month": 6, "year": 2028}},
        "skus": sorted(x["sku"] for x in ozon_targets.values()),
    }
    schema = client.call("ozon", "/v2/product/certification/params", {"params": params_body})
    schema_rows = schema.get("params") or []
    schema_names = {x.get("name") for x in schema_rows}
    if not {"CERTIFICATE_TYPE", "CERTIFICATE_COUNTRY", "ACCORDANCE_TYPE", "NUMBER", "ISSUE_DATE", "EXPIRED_DATE", "SKUS"} <= schema_names:
        raise RuntimeError("ozon_current_create_schema_incomplete")
    accordance_values = {v.get("value") for p in schema_rows if p.get("name") == "ACCORDANCE_TYPE"
                         for v in p.get("variants") or []}
    if "EAEU" not in accordance_values:
        raise RuntimeError("ozon_eaeu_accordance_not_supported")

    payload = {"params": {**params_body, "product_type": "UNKNOWN",
        "link_to_registry": REGISTRY,
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}]}}
    request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    if request_bytes >= 15_000_000:
        raise RuntimeError("ozon_create_payload_exceeds_safe_limit")

    wb_payload = []
    for offer in offers:
        merged = merge_wb(wb_before[offer], [WB_DOC])
        if merged is None:
            raise RuntimeError("wb_exact_doc_already_visible_after_preflight:" + offer)
        wb_payload.append(merged)

    state = {
        "started_at_utc": now(), "phase": "prepared",
        "source_file": str(SOURCE), "source_sha256": actual_hash, "create_request_bytes": request_bytes,
        "fsa": {"record_id": RECORD_ID, "number": NUMBER, "status": "Действует",
                "issue_date": ISSUE, "expiry_date": EXPIRE, "tnved": sorted(EXPECTED_TNVED),
                "brand": "Gauss", "model_family": "GFL", "registry_url": REGISTRY,
                "fsa_product_page": "https://pub.fsa.gov.ru/rds/declaration/view/17751189/product",
                "technical_regulation": "TR CU 037/2016"},
        "targets": list(ozon_targets.values()),
        "ozon": {"exact_number_absent_before_create": True, "supported_type": "DECLARATION",
                 "supported_accordance": "EAEU", "schema_param_names": sorted(schema_names),
                 "create": "not_started", "certificate_id": None, "record_status": None,
                 "target_binding_readback": None},
        "wb": {"card_count": len(wb_payload), "mutation": "not_started", "visible_edges": None,
               "old_documents_preserved": None, "unrelated_fields_preserved": None,
               "review_pending_or_returned": None},
        "local_files_deleted": False,
        "related_unverified_document": {"number": "RU Д-CN.PA04.В.52795/23",
                                        "state": "not_uploaded; no exact live FSA result verified"},
    }
    atomic(OUT, state)

    log("ozon_create_prepared", number=NUMBER, target_skus=params_body["skus"],
        source_sha256=actual_hash, request_bytes=request_bytes)
    state["phase"] = "ozon_create_submitting"
    state["ozon"]["create"] = "prepared"
    atomic(OUT, state)
    create_response = None
    try:
        create_response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        state["ozon"]["create"] = "accepted" if create_response.get("status") == "COMPLETED" else "response_incomplete"
        state["ozon"]["create_response"] = create_response
        log("ozon_create_response", response=create_response)
    except Exception as exc:
        state["ozon"]["create"] = "uncertain_reconcile_without_retry"
        state["ozon"]["create_error"] = type(exc).__name__
        log("ozon_create_uncertain", error=type(exc).__name__)
    atomic(OUT, state)

    if create_response is not None:
        create_param_states = [x.get("state") for x in create_response.get("params") or []
                               if isinstance(x, dict) and x.get("state")]
        if (create_response.get("status") != "COMPLETED"
                or (create_param_states and set(create_param_states) != {"VALID"})):
            state["phase"] = "ozon_create_response_incomplete_no_bind_or_wb"
            state["ozon"]["create_param_states"] = create_param_states
            atomic(OUT, state)
            raise RuntimeError("Ozon create response incomplete; no binding or WB update")

    created_id = str((create_response or {}).get("certificate_id") or "")
    state["phase"] = "ozon_record_reconcile"
    atomic(OUT, state)
    record = None
    for attempt in range(8):
        rows = list_certificates(client)
        matches = [x for x in rows if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
        if len(matches) > 1:
            state["phase"] = "ozon_duplicate_record_after_create_stop"
            state["ozon"]["matching_records"] = len(matches)
            atomic(OUT, state)
            raise RuntimeError("duplicate_ozon_record_after_create")
        if len(matches) == 1:
            record = matches[0]
            break
        if attempt < 7:
            time.sleep(3)
    if record is None:
        state["phase"] = "ozon_record_not_visible_no_retry_wb_not_submitted"
        state["finished_at_utc"] = now()
        atomic(OUT, state)
        raise RuntimeError("created_record_not_visible; no retry and no WB update")

    cid = str(record.get("certificate_id") or "")
    info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": record.get("certificate_number")}).get("result")
    if (not cid or (created_id and cid != created_id)
            or not isinstance(info, dict) or str(info.get("certificate_id")) != cid
            or info.get("type_code") != "declaration"
            or str(info.get("accordance_type_code") or "").upper() != "EAEU"
            or str(info.get("issue_date") or "")[:10] != ISSUE
            or str(info.get("expire_date") or "")[:10] != EXPIRE
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or record.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        state["phase"] = "ozon_record_metadata_conflict_wb_not_submitted"
        state["ozon"]["record"] = record
        state["ozon"]["info"] = info
        atomic(OUT, state)
        raise RuntimeError("Ozon record metadata/status mismatch; WB update stopped")
    state["ozon"].update({"certificate_id": cid, "record_status": record.get("status_code"),
                          "record_readback": {k: info.get(k) for k in (
                              "certificate_id", "certificate_number", "type_code", "accordance_type_code",
                              "issue_date", "expire_date", "status_code")}})

    bindings = client.ozon_bindings(int(cid))
    by_sku = {}
    for b in bindings:
        sku = str(b.get("sku") or "")
        if not sku or sku in by_sku:
            raise RuntimeError("ozon_initial_bindings_missing_or_duplicate_sku")
        by_sku[sku] = b
    targets_by_sku = {x["sku"]: x for x in ozon_targets.values()}
    unexpected = set(by_sku) - set(targets_by_sku)
    if unexpected:
        raise RuntimeError("ozon_initial_bindings_include_unexpected_skus")
    for sku, b in by_sku.items():
        if str(b.get("product_id") or "") != targets_by_sku[sku]["product_id"]:
            raise RuntimeError("ozon_initial_binding_product_id_mismatch")
    missing = sorted(set(targets_by_sku) - set(by_sku))
    if missing:
        bind_request = {"certificate_id": int(cid), "skus": missing}
        log("ozon_bind_prepared", certificate_id=cid, skus=missing)
        state["phase"] = "ozon_bind_submitting"
        state["ozon"]["bind"] = "prepared"
        atomic(OUT, state)
        try:
            bind_response = client.call("ozon", "/v1/product/certificate/bind", bind_request, mutation=True)
            state["ozon"]["bind"] = "accepted" if bind_response.get("result") is True else "response_not_true"
            state["ozon"]["bind_response"] = bind_response
            log("ozon_bind_response", response=bind_response)
        except Exception as exc:
            state["ozon"]["bind"] = "uncertain_reconcile_without_retry"
            state["ozon"]["bind_error"] = type(exc).__name__
            log("ozon_bind_uncertain", error=type(exc).__name__)
        atomic(OUT, state)

    expected = {x["sku"]: x["product_id"] for x in ozon_targets.values()}
    binding_after = []
    for attempt in range(8):
        binding_after = client.ozon_bindings(int(cid))
        current = {str(x.get("sku") or ""): x for x in binding_after}
        if (len(current) == len(binding_after) and set(current) == set(expected)
                and all(str(current[s].get("product_id") or "") == pid for s, pid in expected.items())):
            break
        if attempt < 7:
            time.sleep(5)
    current = {str(x.get("sku") or ""): x for x in binding_after}
    ozon_verified = (len(current) == len(binding_after) and set(current) == set(expected)
                     and all(str(current[s].get("product_id") or "") == pid for s, pid in expected.items()))
    state["ozon"]["target_binding_readback"] = {
        "expected": len(expected), "visible": sum(s in current for s in expected),
        "all_product_ids_match": ozon_verified,
        "status_counts": dict(collections.Counter(str(x.get("product_status_code") or "unknown")
                                                    for x in binding_after)),
    }
    if not ozon_verified:
        state["phase"] = "ozon_binding_readback_incomplete_wb_not_submitted"
        state["finished_at_utc"] = now()
        atomic(OUT, state)
        raise RuntimeError("Ozon product bindings not fully visible; WB write intentionally stopped")

    state["phase"] = "ozon_verified_wb_submitting"
    atomic(OUT, state)
    wb_payload = [merge_wb(wb_before[o], [WB_DOC]) for o in offers]
    log("wb_update_prepared", cards=len(wb_payload))
    try:
        response = client.call("wb", "/content/v2/cards/update", wb_payload, mutation=True)
        state["wb"]["mutation"] = "accepted" if response.get("error") is False else "response_not_accepted"
        state["wb"]["response"] = response
        log("wb_update_response", response=response)
    except Exception as exc:
        state["wb"]["mutation"] = "uncertain_reconcile_without_retry"
        state["wb"]["error"] = type(exc).__name__
        log("wb_update_uncertain", error=type(exc).__name__)
    state["phase"] = "wb_readback"
    atomic(OUT, state)

    wb_after = {}
    report = {}
    for attempt in range(6):
        wb_after = {}
        for offer in offers:
            cards = client.wb_cards(offer)
            if len(cards) == 1:
                wb_after[offer] = cards[0]
        per_offer = {}
        for offer in offers:
            before, after = wb_before[offer], wb_after.get(offer)
            docs = ((after or {}).get("documents") or {}).get("items") or []
            wanted = [x for x in docs if doc_key(x) == doc_key(WB_DOC)
                      and str(x.get("startDate", ""))[:10] == ISSUE
                      and str(x.get("endDate", ""))[:10] == EXPIRE
                      and x.get("isEndless") is False]
            old = {doc_key(x): x for x in copy_documents(before)}
            actual = {doc_key(x): x for x in copy_documents(after or {})}
            old_ok = all(k in actual
                         and str(actual[k].get("startDate", ""))[:10] == str(v.get("startDate", ""))[:10]
                         and str(actual[k].get("endDate", ""))[:10] == str(v.get("endDate", ""))[:10]
                         for k, v in old.items())
            per_offer[offer] = {
                "nmID": str((after or before).get("nmID")),
                "document_visible": len(wanted) == 1,
                "old_documents_preserved": old_ok,
                "unrelated_fields_preserved": bool(after and comparable_card(before) == comparable_card(after)),
                "verdict": next((x.get("verdict") for x in docs if doc_key(x) == doc_key(WB_DOC)), None),
            }
        report = {
            "cards_read": len(wb_after),
            "all_documents_visible": len(per_offer) == len(offers) and all(x["document_visible"] for x in per_offer.values()),
            "all_old_documents_preserved": len(per_offer) == len(offers) and all(x["old_documents_preserved"] for x in per_offer.values()),
            "all_unrelated_fields_preserved": len(per_offer) == len(offers) and all(x["unrelated_fields_preserved"] for x in per_offer.values()),
            "pending_or_returned": sum(1 for x in per_offer.values()
                                       if not (isinstance(x["verdict"], dict)
                                               and x["verdict"].get("verified") is True
                                               and x["verdict"].get("status") == 1
                                               and x["verdict"].get("reason") == "valid")),
            "per_offer": per_offer,
        }
        if report["all_documents_visible"] and report["all_old_documents_preserved"] and report["all_unrelated_fields_preserved"]:
            break
        if attempt < 5:
            time.sleep(15)

    state["wb"].update({"visible_edges": sum(x["document_visible"] for x in report["per_offer"].values()),
                        "old_documents_preserved": report["all_old_documents_preserved"],
                        "unrelated_fields_preserved": report["all_unrelated_fields_preserved"],
                        "review_pending_or_returned": report["pending_or_returned"],
                        "readback": report})
    state["phase"] = ("both_platform_links_readback_verified"
                       if report["all_documents_visible"] and report["all_old_documents_preserved"]
                       and report["all_unrelated_fields_preserved"] else "readback_incomplete_no_resend")
    state["finished_at_utc"] = now()
    atomic(OUT, state)
    log("finished", phase=state["phase"])
    print(json.dumps({"phase": state["phase"], "number": NUMBER,
        "ozon_certificate_id": cid, "ozon_record_status": record.get("status_code"),
        "ozon_target_bindings": state["ozon"]["target_binding_readback"],
        "wb_edges_visible": state["wb"]["visible_edges"],
        "wb_review_pending_or_returned": state["wb"]["review_pending_or_returned"],
        "wb_old_documents_preserved": state["wb"]["old_documents_preserved"],
        "wb_unrelated_fields_preserved": state["wb"]["unrelated_fields_preserved"],
        "local_files_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
