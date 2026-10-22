"""Correct one Legrand WB card to the exact official EAEU certificate number."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now
from feron_53483_crossplatform_20261013 import CARD_FIELDS, clean_wb_doc, norm

PREFLIGHT = BASE / "legrand_00841_wb_prefix_preflight_20261013.json"
OUT = BASE / "legrand_00841_wb_number_correction_20261013.json"
OFFER = "404025-1"
PRODUCT_ID = "6159325973"
SKU = "5641222494"
NMID = "1506951587"
NUMBER = "ЕАЭС KG 417/032.FR.02.00841"
OLD_WB_NUMBER = "EAC KG 417/032.FR.02.00841"
ISSUE = "2025-10-28"
EXPIRY = "2030-10-27"
TNVED = "8536201007"
CERTIFICATE_ID = "5458718"
DOC_NUMBER_CHAR_ID = 15001136


def list_certificates(client: Client) -> list[dict]:
    out = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate list")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate list pagination limit exceeded")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("WB correction journal already exists; reconcile live state before another write")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if not preflight.get("ozon_identity_and_scope_match"):
        raise RuntimeError("Saved Ozon preflight does not prove exact identity and applicability")
    official = preflight["official_document"]
    if (official.get("number") != NUMBER or official.get("issue_date") != ISSUE
            or official.get("expiry_date") != EXPIRY or official.get("tnved_code") != TNVED):
        raise RuntimeError("Official Legrand certificate values differ from the reviewed scope")

    client = Client()
    product = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    products = product.get("items") or product.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != 1:
        raise RuntimeError("Fresh Ozon product readback missing or ambiguous")
    live_product = products[0]
    if (str(live_product.get("offer_id") or "") != OFFER
            or str(live_product.get("id") or live_product.get("product_id") or "") != PRODUCT_ID
            or str(live_product.get("sku") or "") != SKU or live_product.get("is_archived")):
        raise RuntimeError("Ozon Product ID/SKU changed; no WB write sent")
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": [OFFER]}, "limit": 1})
    attr_items = attrs.get("result") or attrs.get("items")
    if not isinstance(attr_items, list) or len(attr_items) != 1:
        raise RuntimeError("Fresh Ozon attributes missing or ambiguous")
    ozon_attrs = {str(x.get("id")): x for x in attr_items[0].get("attributes") or []}
    brand_values = [str(x.get("value") or "") for x in (ozon_attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (ozon_attrs.get("22232") or {}).get("values") or []]
    tnved_codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
    if brand_values != ["Legrand"] or tnved_codes != [TNVED]:
        raise RuntimeError("Fresh Ozon brand/TN VED no longer matches the official certificate")

    records = [x for x in list_certificates(client)
               if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if len(records) != 1 or str(records[0].get("certificate_id")) != CERTIFICATE_ID:
        raise RuntimeError("Ozon exact certificate record is missing or ambiguous")
    if records[0].get("status_code") != "approved" or records[0].get("type_code") != "certificate_of_conformity":
        raise RuntimeError("Ozon certificate record is not approved as a conformity certificate")
    bindings = client.ozon_bindings(int(CERTIFICATE_ID))
    exact_bindings = [x for x in bindings if str(x.get("sku")) == SKU]
    if (len(exact_bindings) != 1 or str(exact_bindings[0].get("product_id")) != PRODUCT_ID
            or exact_bindings[0].get("product_status_code") != "approved"):
        raise RuntimeError("Ozon does not have one approved exact product/SKU binding")

    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError("WB exact card missing or ambiguous")
    card = cards[0]
    if (str(card.get("nmID") or "") != NMID or str(card.get("vendorCode") or "") != OFFER
            or card.get("brand") != "Legrand"):
        raise RuntimeError("WB card identity/brand changed; no update sent")
    codes = set()
    for row in card.get("characteristics") or []:
        if int(row.get("id", -1)) == 15000001:
            codes.update(str(x).strip().split(" ", 1)[0] for x in row.get("value") or [] if str(x).strip())
    if codes != {TNVED}:
        raise RuntimeError("WB TN VED no longer matches the official Legrand certificate")
    docs = card.get("documents") or card.get("docs") or {}
    if docs.get("excludeDocuments") is not False:
        raise RuntimeError("WB card does not explicitly include certificate documents")
    items = docs.get("items") or []
    matches = [x for x in items if int(x.get("type") or 0) == 1
               and str(x.get("number") or "") == OLD_WB_NUMBER]
    if len(items) != 1 or len(matches) != 1:
        raise RuntimeError("WB certificate row is missing, duplicated, or accompanied by other documents")
    old_doc = matches[0]
    if (str(old_doc.get("startDate") or "")[:10] != ISSUE
            or str(old_doc.get("endDate") or "")[:10] != EXPIRY):
        raise RuntimeError("WB certificate dates differ from the official document")
    for key in [x for x in CARD_FIELDS[:-1] if x not in card]:
        raise RuntimeError("WB full-card response omitted field: " + key)
    chars = card.get("characteristics") or []
    number_chars = [x for x in chars if int(x.get("id", -1)) == DOC_NUMBER_CHAR_ID]
    if len(number_chars) != 1 or number_chars[0].get("value") != [OLD_WB_NUMBER]:
        raise RuntimeError("WB certificate-number characteristic is not a single exact old value")

    clean_items = [clean_wb_doc(x) for x in items]
    corrected_items = []
    for item in clean_items:
        row = dict(item)
        if row.get("type") == 1 and row.get("number") == OLD_WB_NUMBER:
            row["number"] = NUMBER
        corrected_items.append(row)
    payload = {key: card[key] for key in CARD_FIELDS if key in card}
    payload["documents"] = {"items": corrected_items, "excludeDocuments": False}
    payload["characteristics"] = [
        ({**x, "value": [NUMBER]} if int(x.get("id", -1)) == DOC_NUMBER_CHAR_ID else x)
        for x in chars
    ]
    if len([x for x in payload["characteristics"] if int(x.get("id", -1)) == DOC_NUMBER_CHAR_ID]) != 1:
        raise RuntimeError("Prepared card no longer has one number characteristic")
    for key in CARD_FIELDS:
        if key == "characteristics":
            for before, after in zip(chars, payload["characteristics"]):
                if int(before.get("id", -1)) != DOC_NUMBER_CHAR_ID and before != after:
                    raise RuntimeError("Prepared card changed an unrelated characteristic")
        elif key in card and key != "documents" and payload.get(key) != card.get(key):
            raise RuntimeError("Prepared card changes a non-document field: " + key)
    state = {
        "prepared_at_utc": now(), "phase": "prepared", "target_count": 1,
        "offer_id": OFFER, "product_id": PRODUCT_ID, "sku": SKU, "nmID": NMID,
        "old_wb_number": OLD_WB_NUMBER, "official_number": NUMBER,
        "official_source_url": official["source_url"], "source_scope_verified": True,
        "ozon_record_id": CERTIFICATE_ID, "ozon_record_status": "approved",
        "ozon_binding_status": "approved", "wb_fields_changed": ["documents.items[0].number",
                                                                    "characteristics[15001136].value"],
        "other_full_card_fields_preserved": True, "preexisting_documents_preserved": True,
        "payload_sha256": hashlib.sha256(json.dumps([payload], ensure_ascii=False,
                                                     separators=(",", ":")).encode()).hexdigest(),
        "mutation_attempts": 0, "payload": [payload],
    }
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    state.update({"phase": "mutation_started", "mutation_attempts": 1, "sent_at_utc": now()})
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        response = client.call("wb", "/content/v2/cards/update", [payload], mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "finished_at_utc": now()})
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("WB update uncertain; read exact card before retry") from None
    state.update({"phase": "accepted_waiting_for_wb_sync" if response.get("error") is False else "rejected",
                  "response": response, "finished_at_utc": now()})
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": state["phase"], "offer_id": OFFER, "nmID": NMID,
                      "response": response, "artifact": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
