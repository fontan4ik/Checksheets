"""Fresh read-only exact Ozon/WB verification for the Legrand 00841 card."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402
from feron_53483_crossplatform_20261013 import wb_tnved_codes  # noqa: E402

OFFER, PRODUCT_ID, SKU, NMID = "404025-1", "6159325973", "5641222494", "1506951587"
NUMBER, CERT_ID, ISSUE, EXPIRY, TNVED = (
    "ЕАЭС KG 417/032.FR.02.00841", "5458718", "2025-10-28", "2030-10-27", "8536201007"
)


def main() -> None:
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    rows = products.get("items") or products.get("result", {}).get("items")
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Ozon exact product missing or ambiguous")
    product = rows[0]
    attrs_body = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [OFFER]}, "limit": 1})
    attr_rows = attrs_body.get("result") or attrs_body.get("items")
    if not isinstance(attr_rows, list) or len(attr_rows) != 1:
        raise RuntimeError("Ozon exact attributes missing or ambiguous")
    attrs = {str(x.get("id")): x for x in attr_rows[0].get("attributes") or []}
    brand = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    tnved = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
    info = client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != CERT_ID:
        raise RuntimeError("Ozon certificate record missing or ambiguous")
    bindings = client.ozon_bindings(int(CERT_ID))
    exact = [x for x in bindings if str(x.get("sku")) == SKU
             and str(x.get("product_id")) == PRODUCT_ID]
    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError("WB exact card missing or ambiguous")
    card = cards[0]
    docs = card.get("documents") or card.get("docs") or {}
    wb_rows = [x for x in (docs.get("items") or [])
               if int(x.get("type") or 0) == 1 and x.get("number") == NUMBER]
    wb_codes = sorted(wb_tnved_codes(card))
    result = {
        "checked_at_utc": now(), "read_only": True,
        "official_source": "https://assets.legrand.com/pim/Certif/LGNOBFKRPB.PDF",
        "ozon": {
            "offer_id": str(product.get("offer_id") or ""),
            "product_id": str(product.get("id") or product.get("product_id") or ""),
            "sku": str(product.get("sku") or ""), "archived": bool(product.get("is_archived")),
            "brand": brand, "tnved_codes": tnved,
            "certificate_id": str(info.get("certificate_id")),
            "certificate_number": info.get("certificate_number"),
            "certificate_status": info.get("status_code"),
            "type_code": info.get("type_code"), "issue_date": info.get("issue_date"),
            "expire_date": info.get("expire_date"),
            "exact_binding_count": len(exact),
            "exact_binding_statuses": [x.get("product_status_code") for x in exact],
        },
        "wb": {
            "vendorCode": str(card.get("vendorCode") or ""), "nmID": str(card.get("nmID") or ""),
            "brand": card.get("brand"), "tnved_codes": wb_codes,
            "excludeDocuments": docs.get("excludeDocuments"), "matching_rows": wb_rows,
        },
    }
    result["complete_on_both_platforms"] = (
        result["ozon"]["offer_id"] == OFFER and result["ozon"]["product_id"] == PRODUCT_ID
        and result["ozon"]["sku"] == SKU and not result["ozon"]["archived"]
        and brand == ["Legrand"] and tnved == [TNVED]
        and result["ozon"]["certificate_status"] == "approved"
        and result["ozon"]["type_code"] == "certificate_of_conformity"
        and len(exact) == 1 and exact[0].get("product_status_code") == "approved"
        and str(card.get("vendorCode") or "") == OFFER and str(card.get("nmID") or "") == NMID
        and card.get("brand") == "Legrand" and wb_codes == [TNVED]
        and docs.get("excludeDocuments") is False and len(wb_rows) == 1
        and wb_rows[0].get("startDate", "")[:10] == ISSUE
        and wb_rows[0].get("endDate", "")[:10] == EXPIRY
        and (wb_rows[0].get("verdict") or {}).get("verified") is True
        and (wb_rows[0].get("verdict") or {}).get("status") == 1
        and (wb_rows[0].get("verdict") or {}).get("reason") == "valid"
    )
    save("legrand_00841_crossplatform_final_recheck_20261013.json", result)
    print(json.dumps({"checked_at_utc": result["checked_at_utc"],
                      "complete_on_both_platforms": result["complete_on_both_platforms"],
                      "ozon_status": result["ozon"]["certificate_status"],
                      "ozon_exact_binding_statuses": result["ozon"]["exact_binding_statuses"],
                      "wb_status": (wb_rows[0].get("verdict") if wb_rows else None)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
