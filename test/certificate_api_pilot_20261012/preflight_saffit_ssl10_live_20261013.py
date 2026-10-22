"""Read-only exact live preflight for five Saffit SSL10 outdoor floodlights."""
from __future__ import annotations

import collections
import json
import re

from api_client import BASE, Client, now, save

OUT = "saffit_ssl10_live_preflight_20261013.json"
NUMBERS = {
    "certificate": "ЕАЭС RU C-CN.HB46.B.01893/23",
    "declaration": "ЕАЭС N RU Д-CN.РА07.В.03649/23",
}
EXPECTED = {
    "55232-1": ("1558900265", "1990336973"),
    "55233-1": ("1558900194", "1990604797"),
    "55234-1": ("1558900211", "1990338594"),
    "55235-1": ("1558900208", "1990608512"),
    "55236-1": ("1558900117", "1990602682"),
}
MODELS = {
    "55232-1": "SSL10-30",
    "55233-1": "SSL10-50",
    "55234-1": "SSL10-100",
    "55235-1": "SSL10-150",
    "55236-1": "SSL10-200",
}
FSA_SCOPE_CODES = {"9405420032", "9405110033", "9405490036"}
WB_TNVED_CHAR_ID = 15000001
CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: object) -> str:
    value = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").upper())
    value = re.sub(r"^(?:N|№)\s*", "", value)
    return "".join(ch for ch in value.translate(CHAR_MAP) if ch.isalnum())


def code_values(values: list[str]) -> list[str]:
    return sorted({re.split(r"\s+-\s+", x, maxsplit=1)[0].strip() for x in values if x.strip()})


def date_fields(rows: list[dict]) -> list[dict]:
    pattern = re.compile(r"manufact|production|date|year|год|изготов|производ", re.I)
    result = []
    for row in rows:
        label = str(row.get("name") or row.get("attribute_name") or "")
        if pattern.search(label):
            result.append({"name": label, "value": row.get("value") or row.get("values")})
    return result


def main() -> None:
    client = Client()
    offers = list(EXPECTED)
    response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    items = response.get("items") or response.get("result", {}).get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product-info response is malformed")
    products = {str(x.get("offer_id") or ""): x for x in items}
    if set(products) != set(offers) or len(products) != len(items):
        raise RuntimeError("Ozon offer set is missing or duplicated")

    attrs_live = {}
    for offer in offers:
        body = client.call("ozon", "/v4/product/info/attributes",
                           {"filter": {"offer_id": [offer]}, "limit": 1})
        rows = body.get("result") or body.get("items")
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon attributes are missing or ambiguous for {offer}")
        attrs = rows[0].get("attributes") or []
        by_id = {str(x.get("id")): x for x in attrs}
        brands = [str(x.get("value") or "") for x in (by_id.get("85") or {}).get("values") or []]
        tnved = [str(x.get("value") or "") for x in (by_id.get("22232") or {}).get("values") or []]
        attrs_live[offer] = {"brand_values": brands, "tnved_values": tnved,
                             "tnved_codes": code_values(tnved),
                             "manufacture_date_attributes": date_fields(attrs)}

    certs = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (body.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        certs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded limit")
    if len({str(x.get("certificate_id")) for x in certs}) != len(certs):
        raise RuntimeError("Ozon certificate list contains duplicate IDs")

    matched_docs = {}
    for kind, number in NUMBERS.items():
        matched_docs[kind] = []
        for record in certs:
            if norm(record.get("certificate_number")) != norm(number):
                continue
            bindings = client.ozon_bindings(record["certificate_id"])
            clean = {k: v for k, v in record.items() if k not in {"certificate_file", "file_content"}}
            clean["binding_count_live"] = len(bindings)
            clean["binding_status_counts_live"] = dict(collections.Counter(
                str(x.get("product_status_code") or "") for x in bindings))
            clean["target_bindings_live"] = [
                {"offer_id": str(x.get("offer_id") or ""), "product_id": str(x.get("product_id") or ""),
                 "sku": str(x.get("sku") or ""), "status": x.get("product_status_code")}
                for x in bindings if str(x.get("offer_id") or "") in EXPECTED]
            matched_docs[kind].append(clean)

    products_out = []
    for offer, (expected_id, expected_sku) in EXPECTED.items():
        product = products[offer]
        live_id = str(product.get("id") or product.get("product_id") or "")
        live_sku = str(product.get("sku") or "")
        cards = client.wb_cards(offer)
        wb_cards = []
        for card in cards:
            chars = card.get("characteristics") or []
            tnved_values = [str(v) for row in chars if int(row.get("id", -1)) == WB_TNVED_CHAR_ID
                            for v in (row.get("value") or [])]
            docs = card.get("documents") or card.get("docs") or {}
            wb_cards.append({
                "nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                "brand": card.get("brand"), "title": card.get("title"),
                "tnved_values": tnved_values, "tnved_codes": code_values(tnved_values),
                "manufacture_date_characteristics": date_fields(chars),
                "documents": [{"type": x.get("type"), "number": x.get("number"),
                               "startDate": x.get("startDate"), "endDate": x.get("endDate"),
                               "verdict": x.get("verdict")}
                              for x in docs.get("items") or []],
                "overallVerdict": docs.get("overallVerdict"), "updatedAt": card.get("updatedAt"),
            })
        products_out.append({
            "offer_id": offer, "model": MODELS[offer],
            "expected_ozon_product_id": expected_id, "live_ozon_product_id": live_id,
            "expected_ozon_sku": expected_sku, "live_ozon_sku": live_sku,
            "ozon_identity_exact": live_id == expected_id and live_sku == expected_sku,
            "name": product.get("name"), "is_archived": product.get("is_archived"),
            "ozon_brand": attrs_live[offer]["brand_values"],
            "ozon_tnved_values": attrs_live[offer]["tnved_values"],
            "ozon_tnved_codes": attrs_live[offer]["tnved_codes"],
            "ozon_tnved_in_scope": bool(set(attrs_live[offer]["tnved_codes"]) & FSA_SCOPE_CODES),
            "ozon_manufacture_date_attributes": attrs_live[offer]["manufacture_date_attributes"],
            "wb_exact_cards": [x for x in wb_cards if x["vendorCode"] == offer],
            "wb_all_cards_for_offer": wb_cards,
        })

    summary = {
        "ozon_exact_identities": sum(x["ozon_identity_exact"] for x in products_out),
        "ozon_in_scope_codes": sum(x["ozon_tnved_in_scope"] for x in products_out),
        "ozon_manufacture_date_fields": sum(bool(x["ozon_manufacture_date_attributes"])
                                             for x in products_out),
        "exact_wb_cards": sum(bool(x["wb_exact_cards"]) for x in products_out),
        "wb_manufacture_date_fields": sum(bool(card.get("manufacture_date_characteristics"))
                                            for x in products_out for card in x["wb_exact_cards"]),
        "ozon_matching_certificate_records": len(matched_docs["certificate"]),
        "ozon_matching_declaration_records": len(matched_docs["declaration"]),
    }
    state = {
        "checked_at_utc": now(), "read_only": True, "expected_offers": len(EXPECTED),
        "fsa_scope_codes": sorted(FSA_SCOPE_CODES), "numbers": NUMBERS,
        "ozon_certificate_record_count": len(certs), "matching_ozon_records": matched_docs,
        "targets": products_out, "summary": summary,
        "scope_note": "Official scope is Saffit/Feron outdoor lighting series SSL; certificate record states samples dated 06.2023. Do not infer manufacture date from listing metadata; no marketplace mutation unless batch manufacture date is evidenced.",
    }
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": state["checked_at_utc"],
                      "summary": summary, "ozon_records": {
                          k: len(v) for k, v in matched_docs.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
