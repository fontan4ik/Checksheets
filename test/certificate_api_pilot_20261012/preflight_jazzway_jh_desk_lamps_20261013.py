"""Read-only exact Ozon/WB preflight for the seven Jazzway JH desk-lamp offers."""
from __future__ import annotations

import collections
import json
import re

from api_client import BASE, Client, now, save

OUT = "jazzway_jh_desk_lamps_live_preflight_20261013.json"
NUMBERS = {
    "certificate": "ЕАЭС RU С-HK.БЛ08.В.02292/26",
    "declaration": "ЕАЭС N RU Д-HK.РА03.В.07470/26",
}
EXPECTED = {
    "5058231-1": ("6149065464", "5632235498"),
    "5062283-1": ("6149066070", "5632236405"),
    "5062290-1": ("6149066045", "5632236234"),
    "5062320-1": ("6149065870", "5632239481"),
    "5062337-1": ("6149065890", "5632238091"),
    "5062344-1": ("6149066057", "5632234712"),
    "5062368-1": ("6149066024", "5632237050"),
}
MODEL_TERMS = {
    "5058231-1": "JH1-01-iv",
    "5062283-1": "JH2-01-gn",
    "5062290-1": "JH2-01-og",
    "5062320-1": "JH2-02-gy",
    "5062337-1": "JH2-02-pk",
    "5062344-1": "JH3-01-wh",
    "5062368-1": "JH3-01-gy",
}
FSA_SCOPE_CODES = {"9405290019", "9405290032"}
WB_TNVED_CHAR_ID = 15000001
CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: object) -> str:
    value = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").upper())
    value = re.sub(r"^(?:N|№)\s*", "", value)
    return "".join(ch for ch in value.translate(CHAR_MAP) if ch.isalnum())


def wb_search_cards(client: Client, term: str) -> list[dict]:
    found, cursor, seen = [], {"limit": 100}, set()
    for _ in range(20):
        response = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": term}}})
        batch = response.get("cards")
        if response.get("error") or not isinstance(batch, list):
            raise RuntimeError(f"WB model search response malformed for {term}")
        found.extend(batch)
        returned = response.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError(f"WB model search page count mismatch for {term}")
        if len(batch) < 100:
            return found
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError(f"WB model search cursor incomplete/repeated for {term}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
    raise RuntimeError(f"WB model search pagination exceeded for {term}")


def main() -> None:
    client = Client()
    offers = list(EXPECTED)
    products_response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    items = products_response.get("items") or products_response.get("result", {}).get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product-info response is malformed")
    products = {str(x.get("offer_id") or ""): x for x in items}
    if set(products) != set(offers) or len(products) != len(items):
        raise RuntimeError("Ozon offer set is missing or duplicated")

    attributes = {}
    for offer in offers:
        response = client.call("ozon", "/v4/product/info/attributes",
                               {"filter": {"offer_id": [offer]}, "limit": 1})
        rows = response.get("result") or response.get("items")
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon attributes are missing or ambiguous for {offer}")
        attrs = {str(x.get("id")): x for x in rows[0].get("attributes") or []}
        brands = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
        tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
        attributes[offer] = {
            "brand_values": brands,
            "tnved_values": tnved_values,
            "tnved_codes": sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()}),
        }

    ozon_records = []
    for page in range(1, 101):
        response = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (response.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        ozon_records.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded limit")
    if len({str(x.get("certificate_id")) for x in ozon_records}) != len(ozon_records):
        raise RuntimeError("Ozon certificate list has duplicate IDs")

    docs = {}
    for key, number in NUMBERS.items():
        matches = [x for x in ozon_records if norm(x.get("certificate_number")) == norm(number)]
        docs[key] = []
        for record in matches:
            bindings = client.ozon_bindings(record["certificate_id"])
            record = {k: v for k, v in record.items() if k not in {"certificate_file", "file_content"}}
            record["binding_count_live"] = len(bindings)
            record["binding_status_counts_live"] = dict(collections.Counter(
                str(x.get("product_status_code") or "") for x in bindings))
            record["target_bindings_live"] = [
                {"offer_id": str(x.get("offer_id") or ""), "product_id": str(x.get("product_id") or ""),
                 "sku": str(x.get("sku") or ""), "status": x.get("product_status_code")}
                for x in bindings if str(x.get("offer_id") or "") in EXPECTED]
            docs[key].append(record)

    targets = []
    wb_model_search = {}
    for offer, model in MODEL_TERMS.items():
        matches = wb_search_cards(client, model)
        wb_model_search[offer] = [{
            "vendorCode": str(c.get("vendorCode") or ""), "nmID": str(c.get("nmID") or ""),
            "brand": c.get("brand"), "subjectID": c.get("subjectID"),
            "subjectName": c.get("subjectName"), "title": c.get("title"),
            "characteristics": c.get("characteristics"),
        } for c in matches]
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
            container = card.get("documents") or card.get("docs") or {}
            wb_cards.append({
                "nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                "brand": card.get("brand"), "subjectID": card.get("subjectID"),
                "subjectName": card.get("subjectName"), "tnved_values": tnved_values,
                "tnved_codes": sorted({x.split(" ", 1)[0].strip() for x in tnved_values if x.strip()}),
                "excludeDocuments": container.get("excludeDocuments"),
                "documents": [{"type": x.get("type"), "number": x.get("number"),
                               "startDate": x.get("startDate"), "endDate": x.get("endDate"),
                               "verdict": x.get("verdict")}
                              for x in container.get("items") or []],
                "overallVerdict": container.get("overallVerdict"),
                "updatedAt": card.get("updatedAt"),
            })
        ozon_codes = set(attributes[offer]["tnved_codes"])
        targets.append({
            "offer_id": offer, "expected_product_id": expected_id, "live_product_id": live_id,
            "expected_sku": expected_sku, "live_sku": live_sku,
            "ozon_identity_exact": live_id == expected_id and live_sku == expected_sku,
            "is_archived": product.get("is_archived"), "name": product.get("name"),
            "ozon_brand": attributes[offer]["brand_values"],
            "ozon_tnved_values": attributes[offer]["tnved_values"],
            "ozon_tnved_codes": sorted(ozon_codes),
            "ozon_tnved_in_scope": bool(ozon_codes & FSA_SCOPE_CODES),
            "wb_card_count": len(wb_cards), "wb_cards": wb_cards,
        })

    state = {
        "checked_at_utc": now(), "read_only": True, "expected_offers": len(EXPECTED),
        "fsa_scope_codes": sorted(FSA_SCOPE_CODES), "numbers": NUMBERS,
        "ozon_certificate_record_count": len(ozon_records), "matching_ozon_records": docs,
        "targets": targets, "wb_model_search": wb_model_search,
        "summary": {
            "ozon_exact_identities": sum(x["ozon_identity_exact"] for x in targets),
            "ozon_in_scope": sum(x["ozon_tnved_in_scope"] for x in targets),
            "wb_exact_cards": sum(sum(c["vendorCode"] == x["offer_id"] for c in x["wb_cards"])
                                   for x in targets),
            "wb_cards_with_target_docs": sum(
                sum(any(norm(row.get("number")) == norm(number)
                        for number in NUMBERS.values()) for row in card["documents"])
                for x in targets for card in x["wb_cards"]),
            "wb_model_search_matches": sum(len(v) for v in wb_model_search.values()),
        },
        "scope_note": "FSA records limit coverage to stock manufactured from the date samples were produced (2026-01); marketplace upload is not authorized without batch/manufacture-date evidence.",
    }
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": state["checked_at_utc"],
                      "summary": state["summary"], "matching_ozon_records": {
                          k: len(v) for k, v in docs.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
