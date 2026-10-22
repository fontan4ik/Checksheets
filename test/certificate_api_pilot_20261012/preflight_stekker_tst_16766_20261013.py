"""Read-only exact live preflight for four STEKKER TST voltage testers."""
from __future__ import annotations

import collections
import json
import re

from api_client import BASE, Client, now, save

OUT = "stekker_tst_16766_live_preflight_20261013.json"
NUMBER = "ЕАЭС N RU Д-CN.РА04.В.16766/22"
FSA_ID = "16786866"
FSA_SCOPE_CODES = {"9030331000"}
WB_TNVED_CHAR_ID = 15000001
EXPECTED = {
    "32861-1": {"model": "TST500-1"},
    "32862-1": {"model": "TST1000-1"},
    "32863-1": {"model": "TST500-2"},
    "50528-1": {"model": "TST500-4"},
}
CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: object) -> str:
    value = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").upper())
    value = re.sub(r"^(?:N|№)\s*", "", value)
    return "".join(ch for ch in value.translate(CHAR_MAP) if ch.isalnum())


def codes(values: list[str]) -> list[str]:
    return sorted({re.split(r"\s+-\s+", x, maxsplit=1)[0].strip() for x in values if x.strip()})


def main() -> None:
    client = Client()
    offers = list(EXPECTED)
    body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    items = body.get("items") or body.get("result", {}).get("items")
    if not isinstance(items, list):
        raise RuntimeError("Ozon product-info response is malformed")
    products = {str(x.get("offer_id") or ""): x for x in items}
    if set(products) != set(offers) or len(products) != len(items):
        raise RuntimeError("Ozon offer set is missing or duplicated")

    attributes = {}
    for offer in offers:
        data = client.call("ozon", "/v4/product/info/attributes",
                           {"filter": {"offer_id": [offer]}, "limit": 1})
        rows = data.get("result") or data.get("items")
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon attributes are missing or ambiguous for {offer}")
        attrs = rows[0].get("attributes") or []
        by_id = {str(x.get("id")): x for x in attrs}
        brands = [str(x.get("value") or "") for x in (by_id.get("85") or {}).get("values") or []]
        tnved = [str(x.get("value") or "") for x in (by_id.get("22232") or {}).get("values") or []]
        attributes[offer] = {"brands": brands, "tnved_values": tnved, "tnved_codes": codes(tnved)}

    all_docs = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (data.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        all_docs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded limit")
    if len({str(x.get("certificate_id")) for x in all_docs}) != len(all_docs):
        raise RuntimeError("Ozon certificate list has duplicate IDs")

    matches = [x for x in all_docs if norm(x.get("certificate_number")) == norm(NUMBER)]
    for record in matches:
        bindings = client.ozon_bindings(record["certificate_id"])
        record["binding_count_live"] = len(bindings)
        record["binding_status_counts_live"] = dict(collections.Counter(
            str(x.get("product_status_code") or "") for x in bindings))
        record["target_bindings_live"] = [
            {"offer_id": str(x.get("offer_id") or ""), "product_id": str(x.get("product_id") or ""),
             "sku": str(x.get("sku") or ""), "status": x.get("product_status_code")}
            for x in bindings if str(x.get("offer_id") or "") in EXPECTED]
        for key in ("certificate_file", "file_content"):
            record.pop(key, None)

    targets = []
    for offer, meta in EXPECTED.items():
        product = products[offer]
        ozon_id = str(product.get("id") or product.get("product_id") or "")
        ozon_sku = str(product.get("sku") or "")
        cards = client.wb_cards(offer)
        wb_rows = []
        for card in cards:
            ch = card.get("characteristics") or []
            vals = [str(v) for row in ch if int(row.get("id", -1)) == WB_TNVED_CHAR_ID
                    for v in (row.get("value") or [])]
            docs = card.get("documents") or card.get("docs") or {}
            wb_rows.append({
                "vendorCode": str(card.get("vendorCode") or ""), "nmID": str(card.get("nmID") or ""),
                "brand": card.get("brand"), "title": card.get("title"),
                "tnved_values": vals, "tnved_codes": codes(vals),
                "documents": [{"type": d.get("type"), "number": d.get("number"),
                               "startDate": d.get("startDate"), "endDate": d.get("endDate"),
                               "verdict": d.get("verdict")}
                              for d in docs.get("items") or []],
                "overallVerdict": docs.get("overallVerdict"), "excludeDocuments": docs.get("excludeDocuments"),
                "updatedAt": card.get("updatedAt"),
            })
        targets.append({
            "offer_id": offer, "model": meta["model"], "ozon_product_id": ozon_id,
            "ozon_sku": ozon_sku, "name": product.get("name"), "is_archived": product.get("is_archived"),
            "ozon_brand": attributes[offer]["brands"], "ozon_tnved_values": attributes[offer]["tnved_values"],
            "ozon_tnved_codes": attributes[offer]["tnved_codes"],
            "ozon_in_fsa_scope": bool(set(attributes[offer]["tnved_codes"]) & FSA_SCOPE_CODES),
            "wb_cards": wb_rows,
            "wb_exact_cards": [x for x in wb_rows if x["vendorCode"] == offer],
        })

    state = {
        "checked_at_utc": now(), "read_only": True,
        "document": {"number": NUMBER, "fsa_id": FSA_ID,
                     "fsa_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product",
                     "fsa_live_status": "Действует", "validity": "2022-06-10—2027-06-09",
                     "scope": "Stekker voltage testers series TST; declaration for TR CU 004/2011 and 020/2011; TN VED 9030331000; serial production."},
        "ozon_certificate_count": len(all_docs), "ozon_matching_records": matches,
        "targets": targets,
        "summary": {
            "exact_ozon_products": len(targets),
            "ozon_codes_in_scope": sum(x["ozon_in_fsa_scope"] for x in targets),
            "exact_wb_cards": sum(bool(x["wb_exact_cards"]) for x in targets),
            "ozon_matching_document_records": len(matches),
            "wb_matching_document_rows": sum(
                sum(norm(d.get("number")) == norm(NUMBER) for d in c["documents"])
                for x in targets for c in x["wb_exact_cards"]),
        },
    }
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": state["checked_at_utc"],
                      "summary": state["summary"], "products": [
                          {"offer_id": x["offer_id"], "product_id": x["ozon_product_id"], "sku": x["ozon_sku"],
                           "wb_nmids": [c["nmID"] for c in x["wb_exact_cards"]],
                           "ozon_tnved_codes": x["ozon_tnved_codes"],
                           "wb_tnved_codes": [c["tnved_codes"] for c in x["wb_exact_cards"]]}
                          for x in targets]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
