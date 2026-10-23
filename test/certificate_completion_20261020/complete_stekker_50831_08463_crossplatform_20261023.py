"""Bind the exact, already-approved Stekker declaration to its missing Ozon target and verify both marketplaces."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"))
from api_client import BASE, Client, now, save

OFFER = "50831-1"
EXPECTED_PRODUCT_ID = "6124668479"
CERTIFICATE_ID = 5442206
NUMBER_PART = "08463/26"
WB_TYPE = 2
OUT = "stekker_50831_08463_crossplatform_live_20261023.json"


def brand(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())

def doc_num(v: str) -> str:
    tr = str.maketrans({"А":"A","В":"B","Е":"E","К":"K","М":"H","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X","Ё":"E","Э":"E","Д":"D","П":"P"})
    return "".join(c for c in str(v or "").upper().translate(tr) if c.isalnum())

def wb_docs(card: dict) -> list[dict]:
    docs = card.get("documents") or card.get("docs") or {}
    return docs.get("items") or []


def main() -> None:
    client = Client()
    product_resp = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    products = product_resp.get("items") or product_resp.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != 1:
        raise RuntimeError("Ozon exact offer read missing or duplicated")
    product = products[0]
    product_id = str(product.get("id") or product.get("product_id") or "")
    sku = str(product.get("sku") or "")
    if product_id != EXPECTED_PRODUCT_ID or not sku or product.get("is_archived") is not False:
        raise RuntimeError("Ozon product identity/status changed; stop before write")

    attrs_resp = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [OFFER]}, "limit": 100})
    attrs = attrs_resp.get("result") or attrs_resp.get("items")
    if not isinstance(attrs, list) or len(attrs) != 1:
        raise RuntimeError("Ozon live attributes missing/duplicated")
    attr_map = {str(x.get("id")): x for x in attrs[0].get("attributes") or []}
    brands = [str(v.get("value") or "") for v in (attr_map.get("85") or {}).get("values") or []]
    tnved_values = [str(v.get("value") or "") for v in (attr_map.get("22232") or {}).get("values") or []]
    tnved_codes = sorted({v.split(" - ", 1)[0].strip() for v in tnved_values if v.strip()})
    if len(brands) != 1 or brand(brands[0]) != "stekker" or "8536699008" not in tnved_codes:
        raise RuntimeError("Ozon live brand/TNVED no longer matches the evidence")

    records = []
    for page in range(1, 100):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate list")
        records.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded")
    matches = [r for r in records if str(r.get("certificate_id")) == str(CERTIFICATE_ID)]
    if len(matches) != 1:
        raise RuntimeError("Expected approved Ozon record no longer uniquely present")
    cert = matches[0]
    if (cert.get("status_code") != "approved" or cert.get("type_code") != "declaration"
            or NUMBER_PART not in str(cert.get("certificate_number", ""))
            or str(cert.get("expire_date", ""))[:10] < "2026-10-23"):
        raise RuntimeError("Ozon document no longer approved/current/exact")

    bindings = client.ozon_bindings(CERTIFICATE_ID)
    target_rows = [x for x in bindings if str(x.get("product_id") or "") == product_id]
    if len(target_rows) > 1 or (target_rows and str(target_rows[0].get("sku") or "") != sku):
        raise RuntimeError("Ozon target binding has an identity conflict")

    cards = [c for c in client.wb_cards(OFFER) if str(c.get("vendorCode") or "") == OFFER]
    if len(cards) != 1 or brand(cards[0].get("brand")) != "stekker":
        raise RuntimeError("Exact WB card missing/duplicated or brand changed")
    matching_wb = [d for d in wb_docs(cards[0]) if int(d.get("type") or 0) == WB_TYPE and NUMBER_PART in str(d.get("number") or "")]
    if len(matching_wb) != 1:
        raise RuntimeError("WB exact card does not contain exactly one matching declaration")
    verdict = matching_wb[0].get("verdict") or {}
    if verdict.get("verified") is not True or verdict.get("reason") != "valid":
        raise RuntimeError("WB declaration is not currently verified valid")

    mutation_result = {"performed": False, "reason": "already_bound" if target_rows else None}
    if not target_rows:
        response = client.call("ozon", "/v1/product/certificate/bind", {"certificate_id": CERTIFICATE_ID, "skus": [sku]}, mutation=True)
        if response.get("result") is not True:
            raise RuntimeError("Ozon bind response did not confirm success; reconcile before any retry")
        mutation_result = {"performed": True, "api_result": response.get("result")}

    verified_bindings = client.ozon_bindings(CERTIFICATE_ID)
    final_rows = [x for x in verified_bindings if str(x.get("product_id") or "") == product_id and str(x.get("sku") or "") == sku]
    if len(final_rows) != 1 or final_rows[0].get("product_status_code") != "approved":
        raise RuntimeError("Ozon binding readback is missing or not approved")
    final_cards = [c for c in client.wb_cards(OFFER) if str(c.get("vendorCode") or "") == OFFER]
    final_wb_rows = [d for c in final_cards for d in wb_docs(c) if int(d.get("type") or 0) == WB_TYPE and NUMBER_PART in str(d.get("number") or "")]
    if len(final_cards) != 1 or len(final_wb_rows) != 1 or (final_wb_rows[0].get("verdict") or {}).get("verified") is not True or (final_wb_rows[0].get("verdict") or {}).get("reason") != "valid":
        raise RuntimeError("WB delayed verification changed during the run")

    report = {
        "checked_at_utc": now(), "read_only_after_write": True,
        "offer_id": OFFER, "document_number": cert.get("certificate_number"),
        "ozon_certificate_id": CERTIFICATE_ID, "ozon_document_status": cert.get("status_code"),
        "ozon_identity": {"product_id": product_id, "sku": sku, "brand": brands, "tnved_codes": tnved_codes, "archived": product.get("is_archived")},
        "mutation": mutation_result,
        "ozon_binding_readback": final_rows,
        "wb_card": {"nmID": str(cards[0].get("nmID") or ""), "vendorCode": OFFER, "brand": cards[0].get("brand"), "matching_document_rows": final_wb_rows},
        "both_platforms_confirmed": True,
        "local_source_deleted": False,
        "local_source_deletion_reason": "The source covers a larger group and five WB rows have no exact current card; retained for unresolved rows.",
    }
    save(OUT, report)
    print(json.dumps({"output": OUT, "checked_at_utc": report["checked_at_utc"], "offer_id": OFFER,
                      "ozon_product_id": product_id, "sku": sku, "ozon_status": cert.get("status_code"),
                      "ozon_binding_status": final_rows[0].get("product_status_code"),
                      "wb_nmID": report["wb_card"]["nmID"], "wb_verdict": final_wb_rows[0].get("verdict"),
                      "mutation": mutation_result, "both_platforms_confirmed": True,
                      "local_source_deleted": False}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
