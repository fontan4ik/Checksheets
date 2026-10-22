"""Bind one proven AlphaCable PVS product to FSA certificate 02888/22 on Ozon and WB."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from feron_53483_crossplatform_20261013 import CARD_FIELDS, clean_wb_doc, wb_tnved_codes  # noqa: E402

PREFLIGHT = BASE / "alphacable_02888_20261013_preflight.json"
EXECUTION = BASE / "alphacable_02888_20261013_execution.json"
VERIFICATION = BASE / "alphacable_02888_20261013_verification.json"
NUMBER = "ЕАЭС RU С-RU.НА46.В.02888/22"
OFFER = "7253052-1"
PRODUCT_ID = "6503121324"
SKU = "5938247888"
NMID = "1862720940"
CERTIFICATE_ID = "5524634"
ISSUE = "2022-03-13"
EXPIRY = "2027-03-12"
TNVED = "8544499509"
TYPE = 1  # Wildberries certificate of conformity
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3057753/product"


def save(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def exact_info(client: Client) -> dict:
    body = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER})
    result = body.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Ozon exact certificate info is missing")
    if (str(result.get("certificate_id")) != CERTIFICATE_ID
            or result.get("certificate_status", result.get("status_code")) != "approved"
            or result.get("type_code") != "certificate_of_conformity"
            or str(result.get("certificate_number") or result.get("number") or "") != NUMBER):
        raise RuntimeError("Ozon certificate identity or status changed")
    if (str(result.get("issue_date") or "")[:10] != ISSUE
            or str(result.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("Ozon certificate dates no longer match the official FSA record")
    return result


def exact_product(client: Client) -> dict:
    body = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    rows = body.get("items") or body.get("result", {}).get("items")
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Ozon exact product info is missing or ambiguous")
    p = rows[0]
    if (str(p.get("offer_id") or "") != OFFER
            or str(p.get("id") or p.get("product_id") or "") != PRODUCT_ID
            or str(p.get("sku") or "") != SKU or p.get("is_archived")):
        raise RuntimeError("Ozon offer/Product ID/SKU changed or product is archived")
    attrs_body = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [OFFER]}, "limit": 1})
    attrs_rows = attrs_body.get("result") or attrs_body.get("items")
    if not isinstance(attrs_rows, list) or len(attrs_rows) != 1:
        raise RuntimeError("Ozon exact product attributes are missing or ambiguous")
    attrs = {str(x.get("id")): x for x in attrs_rows[0].get("attributes") or []}
    brand_values = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
    if brand_values != ["АЛЬФАКАБЕЛЬ"] or codes != [TNVED]:
        raise RuntimeError("Ozon brand or TN VED no longer matches the official FSA scope")
    return {"product": p, "brand_values": brand_values, "tnved_values": tnved_values}


def exact_wb_card(client: Client) -> dict:
    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError("WB exact card is missing or ambiguous")
    card = cards[0]
    if (str(card.get("nmID") or "") != NMID or str(card.get("vendorCode") or "") != OFFER
            or str(card.get("brand") or "").strip().casefold() != "альфакабель"
            or wb_tnved_codes(card) != {TNVED}):
        raise RuntimeError("WB identity, brand, or TN VED changed")
    docs = card.get("documents") or card.get("docs") or {}
    if docs.get("excludeDocuments") is not False:
        raise RuntimeError("WB card does not explicitly include documents")
    items = docs.get("items") or []
    if not isinstance(items, list):
        raise RuntimeError("WB documents.items is malformed")
    unknown = [key for row in items for key in set(row) - {
        "id", "type", "number", "productNumber", "tradeName", "applicant", "startDate", "endDate",
        "isEndless", "verdict", "createdAt", "updatedAt"}]
    if unknown:
        raise RuntimeError("Unknown WB document fields; stop rather than drop data")
    return card


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("Execution journal exists; reconcile marketplace state before any further write")
    pf = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (pf.get("fsa_record", {}).get("id") != 3057753
            or pf.get("fsa_record", {}).get("status") != "Действует"
            or pf.get("fsa_record", {}).get("tnved") != TNVED
            or pf.get("ozon_binding_count_before") != 6
            or pf.get("ozon_target_binding_before")
            or pf.get("wb_card", {}).get("vendorCode") != OFFER
            or str(pf.get("wb_card", {}).get("nmID")) != NMID):
        raise RuntimeError("Saved exact cross-platform preflight no longer proves this target")

    client = Client()
    product_snapshot = exact_product(client)
    cert_before = exact_info(client)
    bindings_before = client.ozon_bindings(int(CERTIFICATE_ID))
    if any(str(b.get("product_id")) == PRODUCT_ID or str(b.get("sku")) == SKU for b in bindings_before):
        raise RuntimeError("Target is already bound on Ozon; reconcile instead of sending a duplicate")
    wb_before = exact_wb_card(client)
    wb_docs = (wb_before.get("documents") or wb_before.get("docs") or {}).get("items") or []
    if any(str(d.get("number") or "") == NUMBER for d in wb_docs):
        raise RuntimeError("Target document appeared on WB; reconcile instead of updating again")
    for key in [key for key in CARD_FIELDS[:-1] if key not in wb_before]:
        raise RuntimeError("WB full card omitted required preserved field: " + key)

    plan = {
        "prepared_at_utc": now(), "phase": "prepared", "fsa_url": FSA_URL,
        "fsa_record_id": 3057753, "number": NUMBER, "fsa_status": "Действует",
        "issue_date": ISSUE, "expiry_date": EXPIRY, "tnved_code": TNVED,
        "scope_basis": "ALFAKABEL PVS, 2-5 copper conductors, 0.75-6.0 mm², PVC insulation/sheath, flexible, up to 380 V; exact Ozon title is PVS 3x4 mm²",
        "offer_id": OFFER, "product_id": PRODUCT_ID, "sku": SKU, "nmID": NMID,
        "ozon_certificate_id": CERTIFICATE_ID, "ozon_certificate_status_before": cert_before.get("certificate_status", cert_before.get("status_code")),
        "ozon_binding_count_before": len(bindings_before), "ozon_target_binding_before": [],
        "ozon_product": product_snapshot,
        "wb_brand": wb_before.get("brand"), "wb_tnved": sorted(wb_tnved_codes(wb_before)),
        "wb_document_count_before": len(wb_docs), "wb_existing_documents": wb_docs,
        "wb_updated_at_before": wb_before.get("updatedAt"),
        "fields_to_preserve": list(CARD_FIELDS), "attempts": {"ozon_bind": 0, "wb_update": 0},
    }
    save(EXECUTION, plan)

    plan.update({"phase": "ozon_bind_started", "attempts": {"ozon_bind": 1, "wb_update": 0},
                 "ozon_bind_sent_at_utc": now()})
    save(EXECUTION, plan)
    try:
        response = client.call("ozon", "/v1/product/certificate/bind",
                               {"certificate_id": int(CERTIFICATE_ID), "skus": [SKU]}, mutation=True)
    except Exception as exc:
        plan.update({"phase": "ozon_bind_uncertain", "error_type": type(exc).__name__, "updated_at_utc": now()})
        save(EXECUTION, plan)
        raise RuntimeError("Ozon mutation outcome uncertain; do not retry without exact readback") from None
    plan["ozon_bind_response"] = response
    if response.get("result") is not True:
        plan.update({"phase": "ozon_bind_rejected", "updated_at_utc": now()})
        save(EXECUTION, plan)
        raise RuntimeError("Ozon did not accept the exact binding")
    plan.update({"phase": "ozon_bind_accepted_readback_pending", "updated_at_utc": now()})
    save(EXECUTION, plan)

    exact_binding = None
    for _ in range(8):
        current = client.ozon_bindings(int(CERTIFICATE_ID))
        matches = [b for b in current if str(b.get("product_id")) == PRODUCT_ID and str(b.get("sku")) == SKU]
        if len(matches) > 1:
            plan.update({"phase": "ozon_duplicate_binding_detected", "ozon_bindings_after": current,
                        "updated_at_utc": now()})
            save(EXECUTION, plan)
            raise RuntimeError("Duplicate exact Ozon binding appeared; WB update stopped")
        if len(matches) == 1:
            exact_binding = matches[0]
            break
        time.sleep(2)
    if exact_binding is None:
        plan.update({"phase": "ozon_binding_not_yet_visible", "updated_at_utc": now()})
        save(EXECUTION, plan)
        raise RuntimeError("Ozon accepted the bind but exact relation is not visible; WB update stopped")
    plan["ozon_binding_after"] = exact_binding
    plan.update({"phase": "ozon_binding_visible_preparing_wb", "updated_at_utc": now()})
    save(EXECUTION, plan)

    # Re-read the exact full WB card immediately before mutation.
    wb_before = exact_wb_card(client)
    wb_docs = (wb_before.get("documents") or wb_before.get("docs") or {}).get("items") or []
    if any(str(d.get("number") or "") == NUMBER for d in wb_docs):
        plan.update({"phase": "wb_document_already_visible_no_update", "wb_card_after": wb_before,
                    "updated_at_utc": now()})
        save(EXECUTION, plan)
        return
    clean_items = [clean_wb_doc(row) for row in wb_docs]
    new_doc = {"type": TYPE, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
               "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
    payload = {key: wb_before[key] for key in CARD_FIELDS if key in wb_before}
    payload["documents"] = {"items": clean_items + [new_doc], "excludeDocuments": False}
    for key in CARD_FIELDS:
        if key in wb_before and payload.get(key) != wb_before.get(key):
            raise RuntimeError("Prepared WB update changes a non-document field: " + key)
    encoded = json.dumps([payload], ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 10_000_000:
        raise RuntimeError("WB full-card payload exceeds safety limit")
    plan.update({"phase": "wb_update_started", "attempts": {"ozon_bind": 1, "wb_update": 1},
                 "wb_update_sent_at_utc": now(), "wb_payload_sha256": hashlib.sha256(encoded).hexdigest(),
                 "wb_payload_bytes": len(encoded), "wb_payload": [payload],
                 "wb_fields_changed": ["documents"], "wb_all_card_fields_preserved": True})
    save(EXECUTION, plan)
    try:
        wb_response = client.call("wb", "/content/v2/cards/update", [payload], mutation=True)
    except Exception as exc:
        plan.update({"phase": "wb_update_uncertain", "error_type": type(exc).__name__, "updated_at_utc": now()})
        save(EXECUTION, plan)
        raise RuntimeError("WB update outcome uncertain; reconcile exact card before any retry") from None
    plan["wb_response"] = wb_response
    plan.update({"phase": "wb_update_accepted_waiting_for_readback" if wb_response.get("error") is False else "wb_update_rejected",
                 "updated_at_utc": now()})
    save(EXECUTION, plan)

    wb_after = None
    exact_rows = []
    for _ in range(8):
        cards_after = client.wb_cards(OFFER)
        if len(cards_after) != 1 or str(cards_after[0].get("nmID")) != NMID:
            plan.update({"phase": "wb_card_readback_ambiguous", "updated_at_utc": now()})
            save(EXECUTION, plan)
            raise RuntimeError("WB exact-card readback became ambiguous")
        wb_after = cards_after[0]
        after_items = ((wb_after.get("documents") or {}).get("items") or [])
        exact_rows = [d for d in after_items if str(d.get("number") or "") == NUMBER
                      and int(d.get("type") or 0) == TYPE
                      and str(d.get("startDate") or "")[:10] == ISSUE
                      and str(d.get("endDate") or "")[:10] == EXPIRY]
        if len(exact_rows) == 1:
            break
        time.sleep(3)
    if wb_after is None:
        raise RuntimeError("WB readback returned no exact card")
    exact_binding = next(b for b in client.ozon_bindings(int(CERTIFICATE_ID))
                         if str(b.get("product_id")) == PRODUCT_ID and str(b.get("sku")) == SKU)
    final_cert_info = exact_info(client)
    verify = {
        "checked_at_utc": now(), "number": NUMBER, "fsa_url": FSA_URL,
        "ozon_certificate_id": CERTIFICATE_ID,
        "ozon_certificate_status": final_cert_info.get("certificate_status", final_cert_info.get("status_code")),
        "ozon_binding": exact_binding, "ozon_product": exact_product(client),
        "wb_card": wb_after, "wb_exact_document_rows": exact_rows,
        "wb_validity_verdict": (exact_rows[0].get("verdict") if exact_rows else None),
        "wb_exclude_documents": (wb_after.get("documents") or {}).get("excludeDocuments"),
        "wb_readback_confirmed": len(exact_rows) == 1,
        "wb_non_document_fields_unchanged": all(wb_after.get(k) == wb_before.get(k) for k in CARD_FIELDS),
    }
    save(VERIFICATION, verify)
    plan.update({"phase": "complete_readback_confirmed" if verify["wb_readback_confirmed"] else "accepted_not_visible_do_not_retry",
                 "verification_file": str(VERIFICATION), "updated_at_utc": now()})
    save(EXECUTION, plan)
    print(json.dumps({"phase": plan["phase"], "ozon_binding": exact_binding,
                      "wb_readback_confirmed": verify["wb_readback_confirmed"],
                      "wb_verdict": verify["wb_validity_verdict"], "execution": str(EXECUTION),
                      "verification": str(VERIFICATION)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
