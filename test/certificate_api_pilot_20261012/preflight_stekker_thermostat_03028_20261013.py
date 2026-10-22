"""Read-only exact live preflight for STEKKER RSW00-5120-09 thermostat."""
from __future__ import annotations

import collections
import json
import re

from api_client import BASE, Client, now, save

OUT = "stekker_thermostat_03028_live_preflight_20261013.json"
OFFER = "50714-1"
NUMBER = "ЕАЭС RU C-CN.НВ85.В.03028/24"
FSA_CODES = {"9032102000", "9032108900", "9032890000"}
WB_TNVED_ID = 15000001


def norm(value: object) -> str:
    value = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").upper())
    value = re.sub(r"^(?:N|№)\s*", "", value)
    mapping = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                            "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X"})
    return "".join(ch for ch in value.translate(mapping) if ch.isalnum())


def code_set(values: list[str]) -> list[str]:
    return sorted({re.split(r"\s+-\s+", x, maxsplit=1)[0].strip() for x in values if x.strip()})


def main() -> None:
    client = Client()
    body = client.call("ozon", "/v3/product/info/list", {"offer_id": [OFFER]})
    rows = body.get("items") or body.get("result", {}).get("items")
    if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("offer_id")) != OFFER:
        raise RuntimeError("Ozon product identity is missing or ambiguous")
    product = rows[0]
    attrs_body = client.call("ozon", "/v4/product/info/attributes",
                             {"filter": {"offer_id": [OFFER]}, "limit": 1})
    attr_rows = attrs_body.get("result") or attrs_body.get("items")
    if not isinstance(attr_rows, list) or len(attr_rows) != 1 or str(attr_rows[0].get("offer_id")) != OFFER:
        raise RuntimeError("Ozon attributes are missing or ambiguous")
    attrs = {str(x.get("id")): x for x in (attr_rows[0].get("attributes") or [])}
    brands = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
    tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
    tnved_codes = code_set(tnved_values)

    certs = []
    for page in range(1, 101):
        response = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (response.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        certs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded 100 pages")
    matches = []
    for record in certs:
        if norm(record.get("certificate_number")) == norm(NUMBER):
            bindings = client.ozon_bindings(record["certificate_id"])
            clean = {k: v for k, v in record.items() if k not in {"certificate_file", "file_content"}}
            clean["binding_count_live"] = len(bindings)
            clean["binding_status_counts_live"] = dict(collections.Counter(
                str(x.get("product_status_code") or "") for x in bindings))
            clean["exact_target_bindings_live"] = [
                {"product_id": str(x.get("product_id") or ""), "sku": str(x.get("sku") or ""),
                 "status": x.get("product_status_code")}
                for x in bindings
                if str(x.get("product_id") or "") == str(product.get("id") or product.get("product_id") or "")
                and str(x.get("sku") or "") == str(product.get("sku") or "")]
            matches.append(clean)

    cards = []
    for card in client.wb_cards(OFFER):
        chars = card.get("characteristics") or []
        vals = [str(v) for row in chars if int(row.get("id", -1)) == WB_TNVED_ID
                for v in (row.get("value") or [])]
        docs = card.get("documents") or card.get("docs") or {}
        cards.append({"vendorCode": str(card.get("vendorCode") or ""), "nmID": str(card.get("nmID") or ""),
                      "brand": card.get("brand"), "title": card.get("title"),
                      "tnved_values": vals, "tnved_codes": code_set(vals),
                      "documents": [{"type": d.get("type"), "number": d.get("number"),
                                     "startDate": d.get("startDate"), "endDate": d.get("endDate"),
                                     "verdict": d.get("verdict")}
                                    for d in docs.get("items") or []],
                      "excludeDocuments": docs.get("excludeDocuments"),
                      "overallVerdict": docs.get("overallVerdict"), "updatedAt": card.get("updatedAt")})
    exact_wb = [c for c in cards if c["vendorCode"] == OFFER]
    result = {"checked_at_utc": now(), "read_only": True,
              "document": {"number": NUMBER, "validity": "2024-01-18—2029-01-17",
                           "source": "official STEKKER/Feron certificate; series RSW; exact product model RSW00-5120-09"},
              "ozon_product": {"product_id": str(product.get("id") or product.get("product_id") or ""),
                               "sku": str(product.get("sku") or ""), "name": product.get("name"),
                               "is_archived": product.get("is_archived"), "brand": brands,
                               "tnved_values": tnved_values, "tnved_codes": tnved_codes,
                               "tnved_in_fsa_scope": bool(set(tnved_codes) & FSA_CODES)},
              "ozon_matching_records": matches, "wb_cards": cards,
              "summary": {"ozon_identity_exact": True, "ozon_tnved_in_scope": bool(set(tnved_codes) & FSA_CODES),
                          "ozon_record_count_for_number": len(matches), "exact_wb_card_count": len(exact_wb),
                          "ozon_exact_target_binding": any(
                              any(x.get("status") == "approved" for x in m.get("exact_target_bindings_live", []))
                              for m in matches),
                          "wb_document_rows": sum(norm(d.get("number")) == norm(NUMBER)
                                                   for c in exact_wb for d in c["documents"])}}
    save(OUT, result)
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": result["checked_at_utc"],
                      "summary": result["summary"], "ozon_product": result["ozon_product"],
                      "wb": [{"nmID": c["nmID"], "tnved_codes": c["tnved_codes"],
                              "documents": [(d["number"], (d.get("verdict") or {}).get("reason"))
                                            for d in c["documents"]]} for c in exact_wb]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
