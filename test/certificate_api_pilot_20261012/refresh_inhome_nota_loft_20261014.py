"""Read-only exact preflight for IN HOME NOTA/LOFT candidates."""
from __future__ import annotations

import collections
import csv
import json

from api_client import BASE, Client, now, save

ROOT = BASE.parents[1]
UNMATCHED = ROOT / "output_to_user/certificates/group_2/IN_HOME/unmatched.csv"
TARGET_NUMBERS = {
    "ЕАЭС N RU Д-CN.РА07.В.52828/26",
    "ЕАЭС N RU Д-CN.РА03.В.37790/26",
}


def norm_number(value: object) -> str:
    char_map = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                              "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                              "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(char_map) if ch.isalnum())


def main() -> None:
    with UNMATCHED.open(newline="", encoding="utf-8-sig") as stream:
        rows = [r for r in csv.DictReader(stream) if r.get("Модель/серия из названия или карточки") in {"NOTA", "LOFT"}]
    if len(rows) != 8:
        raise RuntimeError(f"Expected eight NOTA/LOFT targets, found {len(rows)}")

    client = Client()
    offers = [r["Артикул продавца"] for r in rows]
    info_response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = info_response.get("items") or info_response.get("result", {}).get("items")
    if not isinstance(products, list):
        raise RuntimeError("Ozon product info response is malformed")
    by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(by_offer) != set(offers) or len(by_offer) != len(products):
        raise RuntimeError("Ozon product info response is incomplete or duplicated")

    ozon_docs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        ozon_docs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded limit")

    target_docs = []
    for record in ozon_docs:
        if norm_number(record.get("certificate_number")) not in {norm_number(n) for n in TARGET_NUMBERS}:
            continue
        bindings = client.ozon_bindings(record["certificate_id"])
        target_docs.append({
            "record": {k: v for k, v in record.items() if k not in {"certificate_file", "file_content"}},
            "binding_count": len(bindings),
            "binding_status_counts": dict(collections.Counter(str(b.get("product_status_code") or "") for b in bindings)),
            "target_product_bindings": [{"product_id": str(b.get("product_id") or ""),
                                         "sku": str(b.get("sku") or ""),
                                         "status": b.get("product_status_code")}
                                        for b in bindings if str(b.get("product_id") or "") in
                                        {str(by_offer[o].get("id") or by_offer[o].get("product_id") or "") for o in offers}],
        })

    live = []
    for row in rows:
        offer = row["Артикул продавца"]
        attrs_response = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [offer]}, "limit": 1})
        attrs_rows = attrs_response.get("result") or attrs_response.get("items")
        if not isinstance(attrs_rows, list) or len(attrs_rows) != 1 or str(attrs_rows[0].get("offer_id")) != offer:
            raise RuntimeError(f"Ozon attributes are missing or ambiguous for {offer}")
        attrs = {str(a.get("id")): a for a in attrs_rows[0].get("attributes") or []}
        brand_values = [str(v.get("value") or "") for v in (attrs.get("85") or {}).get("values") or []]
        tnved_values = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
        card = client.wb_cards(offer)
        live.append({
            "offer_id": offer,
            "model": row.get("Модель/серия из названия или карточки"),
            "product_id": str(by_offer[offer].get("id") or by_offer[offer].get("product_id") or ""),
            "sku": str(by_offer[offer].get("sku") or ""),
            "brand_values": brand_values,
            "tnved_values": tnved_values,
            "wb_exact_cards": [{
                "vendorCode": str(c.get("vendorCode") or ""),
                "nmID": str(c.get("nmID") or ""),
                "brand": c.get("brand"),
                "documents": (c.get("documents") or c.get("docs") or {}).get("items") or [],
                "overallVerdict": (c.get("documents") or c.get("docs") or {}).get("overallVerdict"),
            } for c in card],
        })

    result = {"checked_at": now(), "read_only": True, "targets": live, "ozon_target_docs": target_docs}
    save("inhome_nota_loft_exact_preflight_20261014.json", result)
    print(json.dumps({
        "output": "inhome_nota_loft_exact_preflight_20261014.json",
        "checked_at": result["checked_at"],
        "targets": len(live),
        "ozon_products": len(by_offer),
        "ozon_document_records_found": len(target_docs),
        "ozon_target_doc_bindings": sum(len(d["target_product_bindings"]) for d in target_docs),
        "wb_cards": sum(len(t["wb_exact_cards"]) for t in live),
        "wb_doc_rows": sum(len(c["documents"]) for t in live for c in t["wb_exact_cards"]),
        "tnved_codes": sorted({x.split(" - ", 1)[0].strip() for t in live for x in t["tnved_values"] if x.strip()}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
