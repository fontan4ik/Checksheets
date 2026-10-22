"""Read-only one-card check before correcting Legrand certificate number format on WB."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "legrand_00841_wb_prefix_preflight_20261013.json"
OFFER = "404025-1"
PRODUCT_ID = "6159325973"
SKU = "5641222494"
NMID = "1506951587"
NUMBER_SOURCE = "ЕАЭС KG 417/032.FR.02.00841"
NUMBER_WB = "EAC KG 417/032.FR.02.00841"
ISSUE = "2025-10-28"
EXPIRY = "2030-10-27"
TNVED = "8536201007"

sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from feron_53483_crossplatform_20261013 import norm, wb_tnved_codes  # noqa: E402


def main() -> None:
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    items = products.get("items") or products.get("result", {}).get("items")
    if not isinstance(items, list) or len(items) != 1 or str(items[0].get("offer_id")) != OFFER:
        raise RuntimeError("Ozon exact product readback missing or ambiguous")
    product = items[0]
    attr = client.call("ozon", "/v4/product/info/attributes",
                       {"filter": {"offer_id": [OFFER]}, "limit": 1})
    attr_items = attr.get("result") or attr.get("items")
    if not isinstance(attr_items, list) or len(attr_items) != 1:
        raise RuntimeError("Ozon exact attribute readback missing or ambiguous")
    attrs = {str(x.get("id")): x for x in attr_items[0].get("attributes") or []}
    brands = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    tnved_codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError(f"WB exact card lookup returned {len(cards)} cards")
    card = cards[0]
    docs = card.get("documents") or card.get("docs") or {}
    rows = docs.get("items") or []
    old = [x for x in rows if norm(x.get("number")) == norm(NUMBER_SOURCE)]
    out = {
        "checked_at_utc": now(), "read_only": True,
        "official_document": {"number": NUMBER_SOURCE, "source": "Legrand official certificate PDF",
                              "source_url": "https://assets.legrand.com/pim/Certif/LGNOBFKRPB.PDF",
                              "issue_date": ISSUE, "expiry_date": EXPIRY, "tnved_code": TNVED},
        "expected_identity": {"offer_id": OFFER, "product_id": PRODUCT_ID, "sku": SKU, "nmID": NMID},
        "ozon": {"offer_id": str(product.get("offer_id") or ""),
                 "product_id": str(product.get("id") or product.get("product_id") or ""),
                 "sku": str(product.get("sku") or ""), "is_archived": bool(product.get("is_archived")),
                 "name": product.get("name"), "brand_values": brands, "tnved_values": tnved_values,
                 "tnved_codes": tnved_codes},
        "wb": {"nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
               "brand": card.get("brand"), "updatedAt": card.get("updatedAt"),
               "tnved_codes": sorted(wb_tnved_codes(card)), "documents": docs, "card": card,
               "matching_document_rows": old},
    }
    out["ozon_identity_and_scope_match"] = (
        out["ozon"]["product_id"] == PRODUCT_ID and out["ozon"]["sku"] == SKU
        and not out["ozon"]["is_archived"] and brands == ["Legrand"] and tnved_codes == [TNVED])
    out["wb_identity_and_scope_match"] = (
        str(card.get("nmID") or "") == NMID and str(card.get("vendorCode") or "") == OFFER
        and card.get("brand") == "Legrand" and out["wb"]["tnved_codes"] == [TNVED]
        and docs.get("excludeDocuments") is False and len(old) == 1
        and str(old[0].get("number") or "") == NUMBER_WB
        and str(old[0].get("startDate") or "")[:10] == ISSUE
        and str(old[0].get("endDate") or "")[:10] == EXPIRY)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": out["checked_at_utc"],
                      "ozon_identity_and_scope_match": out["ozon_identity_and_scope_match"],
                      "wb_identity_and_scope_match": out["wb_identity_and_scope_match"],
                      "wb_verdict": (old[0].get("verdict") if old else None)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
