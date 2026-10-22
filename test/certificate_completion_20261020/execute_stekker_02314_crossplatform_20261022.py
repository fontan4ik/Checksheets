#!/usr/bin/env python3
"""Bind only exact, in-scope STEKKER 02314/23 targets on Ozon and WB."""
from __future__ import annotations
import collections
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

PREFLIGHT = HERE / "stekker_02314_crossplatform_preflight_20261022.json"
STATE = HERE / "stekker_02314_crossplatform_execution_20261022.json"
JOURNAL = HERE / "stekker_02314_crossplatform_journal_20261022.jsonl"
SOURCE = ROOT / "output_to_user/certificates/additional_search/brand_research/stekker/stekker_hm_cert_02314_23.pdf"
NUMBER = "ЕАЭС RU С-CN.НВ85.В.02314/23"
ISSUE, EXPIRY = "2023-08-30", "2028-08-29"
OZON_TARGET = "39523-1"
ALL_WB_TARGETS = ["39197-1", "39199-1", "39200-1", "39522-1", "39523-1"]
TNV = "8544429009"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def card_tnved(card: dict) -> list[str]:
    codes = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        codes.extend(str(v or "").split(" - ", 1)[0].strip()
                     for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(codes))


def get_exact_products(c: Client, offers: list[str]) -> tuple[dict, dict]:
    ps = c.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    ats = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result") or []
    if len(ps) != len(offers) or len(ats) != len(offers):
        raise RuntimeError("fresh_ozon_product_data_incomplete")
    pm = {str(x.get("offer_id") or ""): x for x in ps}
    am = {str(x.get("offer_id") or ""): x for x in ats}
    if set(pm) != set(offers) or set(am) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_changed")
    return pm, am


def validate_target(offer: str, p: dict, a: dict, *, require_ozon_tnved: bool) -> tuple[str, str]:
    brand = attr_values(a, 85)
    tnved_values = attr_values(a, 22232)
    codes = sorted({str(v).split(" - ", 1)[0].strip() for v in tnved_values})
    name = str(p.get("name") or "")
    if (str(p.get("offer_id") or "") != offer or p.get("is_archived") is not False
            or brand != ["Stekker"] or "удлинитель" not in name.casefold()
            or "HM" not in name):
        raise RuntimeError("ozon_identity_or_scope_changed:" + offer)
    if require_ozon_tnved and codes != [TNV]:
        raise RuntimeError("ozon_tnved_not_in_source_scope:" + offer + ":" + repr(codes))
    pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
    if not pid or not sku:
        raise RuntimeError("ozon_product_id_or_sku_missing:" + offer)
    return pid, sku


def main() -> None:
    if STATE.exists() or JOURNAL.exists():
        raise RuntimeError("execution_artifacts_exist_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    if (pre.get("read_only") is not True or pre.get("ozon_target_offers") != [OZON_TARGET]
            or pre.get("ozon_tnved_mismatch_offers") != ALL_WB_TARGETS[:-1]
            or pre.get("wb_target_offers") != ALL_WB_TARGETS
            or sha256(SOURCE) != pre.get("source_pdf_sha256")):
        raise RuntimeError("preflight_or_source_hash_mismatch")
    c = Client()
    offers = sorted(set(ALL_WB_TARGETS))
    pm, am = get_exact_products(c, offers)
    target_info = {}
    for offer in offers:
        product_id, sku = validate_target(
            offer, pm[offer], am[offer], require_ozon_tnved=(offer == OZON_TARGET)
        )
        target_info[offer] = {"product_id": product_id, "sku": sku}

    certs = []
    for page in range(1, 101):
        result = c.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("fresh_ozon_certificate_snapshot_incomplete")
        certs.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_pages_exceeded")
    matches = [x for x in certs
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) != 1:
        raise RuntimeError("fresh_ozon_record_count_changed:" + str(len(matches)))
    cert = matches[0]
    if (str(cert.get("certificate_id")) != str(pre["ozon_certificate"]["certificate_id"])
            or cert.get("status_code") != "approved"
            or cert.get("type_code") != "certificate_of_conformity"
            or str(cert.get("issue_date", ""))[:10] != ISSUE
            or str(cert.get("expire_date", ""))[:10] != EXPIRY):
        raise RuntimeError("fresh_ozon_document_status_or_metadata_changed")

    before_bindings = c.ozon_bindings(int(cert["certificate_id"]))
    binding_map = {str(x.get("product_id")): x for x in before_bindings}
    oz_target = target_info[OZON_TARGET]
    existing = binding_map.get(oz_target["product_id"])
    if existing and str(existing.get("sku")) != oz_target["sku"]:
        raise RuntimeError("ozon_existing_binding_identity_conflict")
    state = {
        "started_at_utc": now(), "phase": "fresh_preflight_verified",
        "number": NUMBER, "ozon_certificate_id": cert["certificate_id"],
        "ozon_target_offer": OZON_TARGET, "wb_target_offers": ALL_WB_TARGETS,
        "ozon_preexisting_target_binding": existing,
        "ozon_tnved_mismatch_skipped": ALL_WB_TARGETS[:-1],
        "wb_updates_sent": False, "ozon_bind_sent": False,
        "wb_review_left_to_marketplace": True, "local_source_pdf_deleted": False,
    }
    save(STATE, state)

    if not existing:
        payload = {"certificate_id": int(cert["certificate_id"]), "skus": [oz_target["sku"]]}
        prepared = {"at_utc": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                    "phase": "prepared", "payload_sha256": hashlib.sha256(
                        json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    "offers": [OZON_TARGET], "skus": [oz_target["sku"]]}
        journal(prepared)
        state.update(phase="ozon_binding_in_progress", ozon_bind_sent=True, updated_at_utc=now())
        save(STATE, state)
        response = c.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
        journal({**prepared, "phase": "response", "response": response, "finished_at_utc": now()})
        if response.get("result") is not True:
            state.update(phase="ozon_bind_response_not_accepted", ozon_bind_response=response)
            save(STATE, state)
            raise RuntimeError("ozon_bind_not_accepted")
    else:
        state["ozon_bind_already_present"] = True

    live_bindings = c.ozon_bindings(int(cert["certificate_id"]))
    binding = next((x for x in live_bindings
                    if str(x.get("product_id")) == oz_target["product_id"]), None)
    if not binding or str(binding.get("sku")) != oz_target["sku"]:
        raise RuntimeError("ozon_binding_readback_missing_or_identity_conflict")
    state.update(phase="ozon_binding_readback_confirmed", ozon_binding_readback=binding,
                 ozon_binding_confirmed=True, updated_at_utc=now())
    save(STATE, state)

    desired = {
        "type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
        "endDate": wb_datetime(EXPIRY), "isEndless": False,
    }
    wb_cards_before = {}
    wb_payloads = []
    for offer in ALL_WB_TARGETS:
        cards = c.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_count_changed:" + offer)
        card = cards[0]
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(
                    next(x["wb_nmID"] for x in pre["targets"] if x["offer_id"] == offer))
                or str(card.get("brand") or "").strip().casefold() != "stekker"
                or card_tnved(card) != [TNV]):
            raise RuntimeError("fresh_wb_identity_or_scope_conflict:" + offer)
        same = [x for x in copy_documents(card)
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        if same:
            if len(same) == 1 and doc_key(same[0]) == (1, norm_number(NUMBER)) \
                    and str(same[0].get("startDate", ""))[:10] == ISSUE \
                    and str(same[0].get("endDate", ""))[:10] == EXPIRY:
                wb_cards_before[offer] = card
                continue
            raise RuntimeError("wb_same_number_conflict:" + offer)
        payload = merge_wb(card, [desired])
        if payload is None:
            raise RuntimeError("wb_missing_doc_did_not_produce_payload:" + offer)
        wb_cards_before[offer] = card
        wb_payloads.append(payload)

    if len(wb_payloads) != len(ALL_WB_TARGETS):
        raise RuntimeError("wb_partial_or_already_present_state_changed_before_update")
    payload_bytes = json.dumps(wb_payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payload_bytes) > 9_500_000:
        raise RuntimeError("wb_update_payload_too_large")
    req_sha = hashlib.sha256(payload_bytes).hexdigest()
    prep = {"at_utc": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
            "phase": "prepared", "payload_sha256": req_sha,
            "offers": ALL_WB_TARGETS, "nmIDs": [str(wb_cards_before[x].get("nmID")) for x in ALL_WB_TARGETS],
            "payload_bytes": len(payload_bytes)}
    journal(prep)
    state.update(phase="wb_metadata_update_in_progress", wb_updates_sent=True,
                 wb_before_cards=wb_cards_before, wb_update_count=len(wb_payloads),
                 wb_request_sha256=req_sha, updated_at_utc=now())
    save(STATE, state)
    response = c.call("wb", "/content/v2/cards/update", wb_payloads, mutation=True)
    journal({**prep, "phase": "response", "response": response, "finished_at_utc": now()})
    if response.get("error") is not False:
        state.update(phase="wb_update_response_not_accepted", wb_update_response=response)
        save(STATE, state)
        raise RuntimeError("wb_update_not_accepted")

    readback = {}
    for offer in ALL_WB_TARGETS:
        card_rows = c.wb_cards(offer)
        if len(card_rows) != 1:
            raise RuntimeError("wb_readback_card_count_changed:" + offer)
        card = card_rows[0]
        docs = copy_documents(card)
        exact = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        before_docs = copy_documents(wb_cards_before[offer])
        before_keys = collections.Counter(
            (doc_key(x), str(x.get("startDate", ""))[:10], str(x.get("endDate", ""))[:10])
            for x in before_docs)
        after_keys = collections.Counter(
            (doc_key(x), str(x.get("startDate", ""))[:10], str(x.get("endDate", ""))[:10])
            for x in docs)
        if (len(exact) != 1 or doc_key(exact[0]) != (1, norm_number(NUMBER))
                or str(exact[0].get("startDate", ""))[:10] != ISSUE
                or str(exact[0].get("endDate", ""))[:10] != EXPIRY
                or not (before_keys <= after_keys)
                or str(card.get("nmID")) != str(wb_cards_before[offer].get("nmID"))
                or str(card.get("vendorCode")) != offer):
            raise RuntimeError("wb_document_readback_or_preservation_mismatch:" + offer)
        readback[offer] = {
            "nmID": str(card.get("nmID")), "vendorCode": card.get("vendorCode"),
            "brand": card.get("brand"), "tnved": card_tnved(card),
            "certificate_document": exact[0],
            "all_preexisting_documents_preserved": True,
        }

    state.update(phase="finished_verified_readback", completed_at_utc=now(),
                 wb_readback=readback, wb_readback_count=len(readback),
                 wb_review_left_to_marketplace=True, local_source_pdf_deleted=False)
    save(STATE, state)
    print(json.dumps({
        "phase": state["phase"], "completed_at_utc": state["completed_at_utc"],
        "ozon_certificate_id": cert["certificate_id"], "ozon_bound_target": OZON_TARGET,
        "ozon_binding_status": binding.get("product_status_code"),
        "ozon_binding_readback": state["ozon_binding_confirmed"],
        "wb_cards_updated_and_read_back": len(readback),
        "wb_verdicts": {k: (v["certificate_document"].get("verdict") or {}) for k,v in readback.items()},
        "ozon_tnved_mismatch_skipped": ALL_WB_TARGETS[:-1],
        "wb_review_left_to_marketplace": True, "local_source_pdf_deleted": False,
        "state": str(STATE), "journal": str(JOURNAL),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
