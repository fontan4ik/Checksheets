"""Fresh read-only exact-card preflight for the Saffit LL-980/981/982 set."""
from __future__ import annotations

import collections
import json
import re

from api_client import BASE, Client, now, save

OFFERS = ["53140-1", "53141-1", "53142-1"]
NUMBERS = {
    "certificate": "ЕАЭС RU C-CN.ПФ02.В.05931/22",
    "declaration": "ЕАЭС N RU Д-CN.РА06.В.53562/22",
}
WB_TNVED_ID = 15000001


def norm(value: object) -> str:
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                           "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                           "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def code_set(values: list[str]) -> list[str]:
    return sorted({x.split(" - ", 1)[0].strip().split(" ", 1)[0]
                   for x in values if x.strip()})


def main() -> None:
    client = Client()
    product_body = client.call("ozon", "/v3/product/info/list", {"offer_id": OFFERS})
    products = product_body.get("items") or product_body.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != len(OFFERS):
        raise RuntimeError("Ozon exact product set is incomplete")
    products_by_offer = {str(x.get("offer_id") or ""): x for x in products}
    if set(products_by_offer) != set(OFFERS):
        raise RuntimeError("Ozon exact offer set is ambiguous")
    product_ids = sorted({str(x.get("id") or x.get("product_id") or "") for x in products})
    if "" in product_ids or len(product_ids) != len(OFFERS):
        raise RuntimeError("Ozon product IDs are missing or duplicated")
    detail_body = client.call("ozon", "/v3/product/info/list",
                              {"product_id": [int(x) for x in product_ids]})
    detail_rows = detail_body.get("items") or detail_body.get("result", {}).get("items")
    if not isinstance(detail_rows, list) or len(detail_rows) != len(OFFERS):
        raise RuntimeError("Ozon product detail set is incomplete")
    details_by_id = {str(x.get("id") or x.get("product_id") or ""): x for x in detail_rows}
    if set(details_by_id) != set(product_ids):
        raise RuntimeError("Ozon product detail identity set is ambiguous")
    listed_body = client.call("ozon", "/v3/product/list", {
        "filter": {"product_id": product_ids, "visibility": "ALL"},
        "limit": 1000, "last_id": "",
    })
    listed_rows = (listed_body.get("result") or {}).get("items")
    if not isinstance(listed_rows, list):
        raise RuntimeError("Ozon targeted product-list response is malformed")
    listed_by_id = {str(x.get("product_id") or x.get("id") or ""): x for x in listed_rows}
    if len(listed_by_id) != len(listed_rows) or set(listed_by_id) != set(product_ids):
        raise RuntimeError("Ozon product-list identity set is incomplete or duplicated")

    targets = []
    for offer in OFFERS:
        product = products_by_offer[offer]
        detail = details_by_id[str(product.get("id") or product.get("product_id") or "")]
        attr_body = client.call("ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": [offer]}, "limit": 1})
        attrs_result = attr_body.get("result") or attr_body.get("items")
        if not isinstance(attrs_result, list) or len(attrs_result) != 1:
            raise RuntimeError(f"Ozon attributes missing for {offer}")
        if str(attrs_result[0].get("offer_id") or "") != offer:
            raise RuntimeError(f"Ozon attributes identity mismatch for {offer}")
        attrs = {str(x.get("id")): x for x in attrs_result[0].get("attributes") or []}
        brands = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
        tnved_values = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
        brandish_attrs = [{"id": x.get("id"), "name": x.get("name"),
                           "values": [v.get("value") for v in x.get("values") or []]}
                          for x in attrs_result[0].get("attributes") or []
                          if "бренд" in str(x.get("name") or "").lower()]
        listed = listed_by_id[str(product.get("id") or product.get("product_id") or "")]
        sku = str(detail.get("sku") or product.get("sku") or listed.get("sku") or "")
        if str(listed.get("offer_id") or "") != offer or str(detail.get("offer_id") or "") != offer:
            raise RuntimeError(f"Ozon exact offer identity not confirmed for {offer}")

        cards = client.wb_cards(offer)
        exact_cards = [x for x in cards if str(x.get("vendorCode") or "") == offer]
        wb_rows = []
        for card in exact_cards:
            chars = card.get("characteristics") or []
            tnved_values_wb = [str(v) for row in chars if str(row.get("id")) == str(WB_TNVED_ID)
                               for v in (row.get("value") or [])]
            documents = card.get("documents") or card.get("docs") or {}
            wb_rows.append({
                "vendorCode": str(card.get("vendorCode") or ""),
                "nmID": str(card.get("nmID") or ""),
                "brand": card.get("brand"),
                "title": card.get("title"),
                "tnved_values": tnved_values_wb,
                "tnved_codes": code_set(tnved_values_wb),
                "excludeDocuments": documents.get("excludeDocuments"),
                "overallVerdict": documents.get("overallVerdict"),
                "documents": [{"type": d.get("type"), "number": d.get("number"),
                               "startDate": d.get("startDate"), "endDate": d.get("endDate"),
                               "verdict": d.get("verdict")}
                              for d in documents.get("items") or []],
            })
        targets.append({
            "offer_id": offer,
            "product_id": str(product.get("id") or product.get("product_id") or ""),
            "sku": sku,
            "sku_usable": sku not in {"", "0"},
            "name": product.get("name"),
            "is_archived": detail.get("is_archived", product.get("is_archived")),
            "product_statuses": detail.get("statuses"),
            "product_errors": detail.get("errors"),
            "catalog_listing": {k: listed.get(k) for k in ("offer_id", "product_id", "sku", "archived")},
            "brand_values": brands,
            "brandish_attributes": brandish_attrs,
            "ozon_attribute_ids": sorted(attrs),
            "ozon_tnved_values": tnved_values,
            "ozon_tnved_codes": code_set(tnved_values),
            "wb_exact_card_count": len(exact_cards),
            "wb_cards": wb_rows,
        })

    certs = []
    for page in range(1, 101):
        response = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (response.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list malformed")
        certs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded 100 pages")

    matched_docs = {}
    for kind, number in NUMBERS.items():
        matches = [x for x in certs if norm(x.get("certificate_number")) == norm(number)]
        rows = []
        for cert in matches:
            bindings = client.ozon_bindings(cert["certificate_id"])
            exact_target_bindings = []
            for target in targets:
                pairs = [x for x in bindings
                         if str(x.get("product_id") or "") == target["product_id"]
                         and str(x.get("sku") or "") == target["sku"]]
                exact_target_bindings.append({"offer_id": target["offer_id"], "count": len(pairs),
                                              "statuses": [x.get("product_status_code") for x in pairs]})
            rows.append({
                **{k: v for k, v in cert.items() if k not in {"certificate_file", "file_content"}},
                "binding_count": len(bindings),
                "binding_status_counts": dict(collections.Counter(
                    str(x.get("product_status_code") or "") for x in bindings)),
                "target_bindings": exact_target_bindings,
            })
        matched_docs[kind] = rows

    state = {"checked_at_utc": now(), "read_only": True, "targets": targets,
             "ozon_matching_records": matched_docs}
    save("saffit_ll_exact_live_preflight_20261013.json", state)
    print(json.dumps({"checked_at_utc": state["checked_at_utc"],
                      "targets": [{"offer_id": x["offer_id"], "product_id": x["product_id"],
                                   "sku": x["sku"], "sku_usable": x["sku_usable"],
                                   "product_statuses": x["product_statuses"],
                                   "product_errors": x["product_errors"],
                                   "name": x["name"], "brand": x["brand_values"],
                                   "brandish_attributes": x["brandish_attributes"],
                                   "ozon_tnved": x["ozon_tnved_codes"],
                                   "wb": [{"nmID": c["nmID"], "brand": c["brand"],
                                           "tnved": c["tnved_codes"],
                                           "matching_docs": [d for d in c["documents"]
                                                             if any(norm(d.get("number")) == norm(n)
                                                                    for n in NUMBERS.values())]}
                                          for c in x["wb_cards"]]}
                                  for x in targets],
                      "ozon_matching_records": {kind: [
                          {"certificate_id": x["certificate_id"], "number": x["certificate_number"],
                           "type_code": x["type_code"], "status_code": x["status_code"],
                           "issue_date": x.get("issue_date"), "expire_date": x.get("expire_date"),
                           "binding_count": x["binding_count"],
                           "target_bindings": x["target_bindings"]}
                          for x in rows] for kind, rows in matched_docs.items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
