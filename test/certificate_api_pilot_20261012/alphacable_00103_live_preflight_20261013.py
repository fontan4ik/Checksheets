"""Read-only cross-platform preflight for AlphaCable certificate 00103/25."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PDF = ROOT / "output_to_user/certificates/alphacable/ЕАЭС_RU_С-RU.АД38.В.00103-25.pdf"
OUT = BASE / "alphacable_00103_live_preflight_20261013.json"
NUMBER = "ЕАЭС RU С-RU.АД38.В.00103/25"
WB_NUMBER = NUMBER
OLD_NUMBER = "ЕАЭС RU С-RU.НА39.В.01186/22"
EXPECTED = [
    {"offer_id": "4237264-1", "product_id": "6503121195", "sku": "5938248994", "nmID": "1862722026"},
    {"offer_id": "7699117-1", "product_id": "6503121209", "sku": "5938247255", "nmID": "1862721281"},
    {"offer_id": "3137562-1", "product_id": "6503121299", "sku": "5938248851", "nmID": "1862720826"},
    {"offer_id": "4269981-1", "product_id": "6503121325", "sku": "5938247495", "nmID": "1862720902"},
    {"offer_id": "7188787-1", "product_id": "6503121326", "sku": "5938249419", "nmID": "1862721368"},
    {"offer_id": "8966341-1", "product_id": "6503121361", "sku": "5938247259", "nmID": "1862721043"},
    {"offer_id": "1743162-1", "product_id": "6503121363", "sku": "5938246904", "nmID": "1862721485"},
]
CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})

sys.path.insert(0, str(BASE))
from api_client import Client, now, save, digest  # noqa: E402


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def list_ozon_certificates(client: Client) -> list[dict]:
    out = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate-list response")
        out.extend(batch)
        if len(batch) < 100:
            if len({str(x.get("certificate_id")) for x in out}) != len(out):
                raise RuntimeError("Duplicate Ozon certificate IDs")
            return out
        page += 1
    raise RuntimeError("Ozon certificate-list pagination limit exceeded")


def read_ozon_products(client: Client) -> dict[str, dict]:
    offers = [x["offer_id"] for x in EXPECTED]
    result = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    items = result.get("items") or result.get("result", {}).get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product info omitted items")
    out = {}
    for item in items:
        offer = str(item.get("offer_id") or "")
        if not offer or offer in out:
            raise RuntimeError("Ozon returned a missing/duplicate offer")
        out[offer] = item
    if set(out) != set(offers):
        raise RuntimeError(f"Ozon offer set mismatch: missing={sorted(set(offers)-set(out))}")
    return out


def read_ozon_attributes(client: Client) -> dict[str, dict]:
    offers = [x["offer_id"] for x in EXPECTED]
    body = client.call("ozon", "/v4/product/info/attributes",
                       {"filter": {"offer_id": offers}, "limit": 100})
    items = body.get("result") or body.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon attributes omitted result items")
    out = {}
    for item in items:
        offer = str(item.get("offer_id") or "")
        if not offer or offer in out:
            raise RuntimeError("Ozon attributes returned a missing/duplicate offer")
        attrs = {str(x.get("id")): x for x in item.get("attributes") or []}
        brand = [str(v.get("value") or "") for v in (attrs.get("85") or {}).get("values") or []]
        tnved = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
        codes = sorted({v.split(" - ", 1)[0].strip() for v in tnved if v.strip()})
        out[offer] = {"brand_values": brand, "tnved_values": tnved, "tnved_codes": codes}
    if set(out) != set(offers):
        raise RuntimeError(f"Ozon attribute set mismatch: missing={sorted(set(offers)-set(out))}")
    return out


def main() -> None:
    if not PDF.is_file():
        raise RuntimeError(f"Official PDF not found: {PDF}")
    file_hash = digest(PDF)
    client = Client()
    products = read_ozon_products(client)
    attributes = read_ozon_attributes(client)
    target_by_offer = {x["offer_id"]: x for x in EXPECTED}
    ozon_rows = []
    for offer, expected in target_by_offer.items():
        item = products[offer]
        actual = {"offer_id": offer,
                  "product_id": str(item.get("id") or item.get("product_id") or ""),
                  "sku": str(item.get("sku") or ""),
                  "is_archived": bool(item.get("is_archived")),
                  "name": item.get("name"),
                  **attributes[offer]}
        actual["identity_match"] = (actual["product_id"] == expected["product_id"]
                                     and actual["sku"] == expected["sku"]
                                     and not actual["is_archived"])
        actual["scope_match"] = (actual["brand_values"] == ["АЛЬФАКАБЕЛЬ"]
                                 and actual["tnved_codes"] == ["8544499509"]
                                 and "мкэш" in str(actual["name"] or "").casefold())
        ozon_rows.append(actual)

    records = list_ozon_certificates(client)
    matching_records = [x for x in records
                        if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    if lookup.status_code not in (200, 404):
        raise RuntimeError(f"Ozon exact-number lookup inconclusive: HTTP {lookup.status_code}")

    wb_rows = []
    for target in EXPECTED:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) != 1:
            wb_rows.append({"offer_id": target["offer_id"], "card_count": len(cards),
                            "expected_nmID": target["nmID"], "identity_match": False})
            continue
        card = cards[0]
        docs = card.get("documents") or card.get("docs") or {}
        items = docs.get("items") or []
        new_matches = [x for x in items if norm(x.get("number")) == norm(WB_NUMBER)]
        old_matches = [x for x in items if norm(x.get("number")) == norm(OLD_NUMBER)]
        tnved = []
        for char in card.get("characteristics") or []:
            if int(char.get("id", -1)) == 15000001:
                values = char.get("value") or []
                tnved = [str(x).strip().split(" ", 1)[0] for x in values if str(x).strip()]
        wb_rows.append({
            "offer_id": target["offer_id"], "expected_nmID": target["nmID"],
            "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
            "subjectName": card.get("subjectName"), "updatedAt": card.get("updatedAt"),
            "identity_match": str(card.get("nmID") or "") == target["nmID"]
                              and str(card.get("vendorCode") or "") == target["offer_id"],
            "tnved_codes": sorted(set(tnved)), "documents": docs,
            "new_document_rows": new_matches, "old_invalid_document_rows": old_matches,
            "card": card,
        })

    status = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "file_path": str(PDF), "file_sha256": file_hash, "file_bytes": PDF.stat().st_size,
        "target_count": len(EXPECTED), "targets": EXPECTED,
        "ozon": {"certificate_count": len(records), "matching_number_records": matching_records,
                 "exact_number_lookup": {"http_status": lookup.status_code, "body": lookup_body},
                 "products": ozon_rows,
                 "all_identities_exact": len(ozon_rows) == len(EXPECTED) and all(x["identity_match"] for x in ozon_rows),
                 "all_in_scope": len(ozon_rows) == len(EXPECTED) and all(x["scope_match"] for x in ozon_rows)},
        "wb": {"products": wb_rows,
               "all_identities_exact": len(wb_rows) == len(EXPECTED) and all(x.get("identity_match") for x in wb_rows),
               "all_tnved_in_scope": len(wb_rows) == len(EXPECTED) and all(x.get("tnved_codes") == ["8544499509"] for x in wb_rows),
               "all_old_document_rows_present": len(wb_rows) == len(EXPECTED) and all(x.get("old_invalid_document_rows") for x in wb_rows),
               "new_document_rows_already_present": sum(bool(x.get("new_document_rows")) for x in wb_rows)},
    }
    save(OUT.name, status)
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": status["checked_at_utc"],
                      "ozon_all_identities_exact": status["ozon"]["all_identities_exact"],
                      "ozon_all_in_scope": status["ozon"]["all_in_scope"],
                      "matching_ozon_records": len(matching_records),
                      "wb_all_identities_exact": status["wb"]["all_identities_exact"],
                      "wb_all_tnved_in_scope": status["wb"]["all_tnved_in_scope"],
                      "wb_all_old_document_rows_present": status["wb"]["all_old_document_rows_present"],
                      "wb_new_document_rows_already_present": status["wb"]["new_document_rows_already_present"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
