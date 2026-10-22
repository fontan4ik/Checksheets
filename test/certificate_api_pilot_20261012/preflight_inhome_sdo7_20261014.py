"""Read-only live reconciliation for IN HOME SDO-7 offers on Ozon and WB."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from api_client import BASE, Client, now

SNAPSHOT = BASE / "ozon_brand_tnved_inventory_recheck_20261013_1828Z.json"
OUT = BASE / "inhome_sdo7_live_preflight_20261014.json"
TARGET_NUMBERS = ("ЕАЭС N RU Д-CN.РА03.В.37790/26",
                  "ЕАЭС N RU Д-CN.РА07.В.05689/26",
                  "ЕАЭС N RU Д-CN.РА07.В.68205/26",
                  "ЕАЭС N RU Д-CN.РА07.В.67935/26")
CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def ozon_certificates(client: Client) -> list[dict]:
    records = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = body.get("result", {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response is malformed")
        records.extend(batch)
        if len(batch) < 100:
            if len({str(row.get("certificate_id")) for row in records}) != len(records):
                raise RuntimeError("Ozon certificate list contains duplicate IDs")
            return records
    raise RuntimeError("Ozon certificate pagination exceeded limit")


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not snapshot.get("complete"):
        raise RuntimeError("A complete Ozon inventory snapshot is required")
    targets = [row for row in snapshot.get("products", [])
               if row.get("is_archived") is False
               and str(row.get("brand") or "").strip().upper() == "IN HOME"
               and "9405420012" in (row.get("tnved_codes") or [])
               and re.search(r"СДО\s*[-–]?\s*7", str(row.get("name") or ""), re.I)]
    targets.sort(key=lambda row: str(row.get("offer_id") or ""))
    offers = [str(row.get("offer_id") or "") for row in targets]
    if len(offers) != 41 or "" in offers or len(set(offers)) != len(offers):
        raise RuntimeError(f"Expected 41 unique active SDO-7 offers; found {len(offers)}")

    client = Client()
    result = {"checked_at_utc": now(), "read_only": True,
              "source_inventory_checked_at": snapshot.get("checked_at"),
              "target_count": len(targets), "targets": [], "ozon_documents": []}
    products_body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = products_body.get("items") or products_body.get("result", {}).get("items")
    if not isinstance(products, list):
        raise RuntimeError("Ozon product-info response is malformed")
    products_by_offer = {str(item.get("offer_id") or ""): item for item in products}
    if set(products_by_offer) != set(offers) or len(products_by_offer) != len(products):
        raise RuntimeError("Live Ozon product-info offer set is incomplete or duplicated")

    attributes_body = client.call("ozon", "/v4/product/info/attributes",
                                  {"filter": {"offer_id": offers}, "limit": len(offers)})
    attribute_rows = attributes_body.get("result") or attributes_body.get("items")
    if not isinstance(attribute_rows, list):
        raise RuntimeError("Ozon product attributes response is malformed")
    attrs_by_offer = {str(item.get("offer_id") or ""): item for item in attribute_rows}
    if set(attrs_by_offer) != set(offers) or len(attrs_by_offer) != len(attribute_rows):
        raise RuntimeError("Live Ozon attributes offer set is incomplete or duplicated")

    for source in targets:
        offer = str(source["offer_id"])
        product = products_by_offer[offer]
        attrs = attrs_by_offer[offer]
        brand_values, tnved_values = [], []
        for attr in attrs.get("attributes") or []:
            values = [str(v.get("value")) for v in attr.get("values") or []
                      if v.get("value") not in (None, "")]
            if str(attr.get("id")) == "85":
                brand_values = values
            elif str(attr.get("id")) == "22232":
                tnved_values = values
        result["targets"].append({
            "offer_id": offer,
            "product_id": str(product.get("id") or product.get("product_id") or ""),
            "sku": str(product.get("sku") or ""),
            "is_archived": bool(product.get("is_archived")),
            "brand_values": brand_values,
            "tnved_values": tnved_values,
            "name": str(attrs.get("name") or product.get("name") or source.get("name") or ""),
            "wb_exact_cards": [],
        })

    out_by_offer = {row["offer_id"]: row for row in result["targets"]}
    for index, offer in enumerate(offers, start=1):
        cards = client.wb_cards(offer)
        for card in cards:
            if str(card.get("vendorCode") or "") != offer:
                raise RuntimeError(f"WB exact lookup returned a non-exact vendorCode for {offer}")
            document_block = card.get("documents") or card.get("docs") or {}
            out_by_offer[offer]["wb_exact_cards"].append({
                "vendorCode": str(card.get("vendorCode") or ""),
                "nmID": str(card.get("nmID") or ""),
                "brand": card.get("brand"),
                "subjectName": card.get("subjectName"),
                "documents": document_block.get("items") or [],
                "overallVerdict": document_block.get("overallVerdict"),
            })
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"wb_checked": index, "wb_total": len(offers),
                          "offer_id": offer, "exact_cards": len(cards)}, ensure_ascii=False), flush=True)

    number_norms = {norm(number): number for number in TARGET_NUMBERS}
    for record in ozon_certificates(client):
        number = str(record.get("certificate_number") or "")
        if norm(number) not in number_norms:
            continue
        bindings = client.ozon_bindings(record["certificate_id"])
        target_product_ids = {row["product_id"] for row in result["targets"]}
        target_bindings = [{"product_id": str(row.get("product_id") or ""),
                            "sku": str(row.get("sku") or ""),
                            "status": row.get("product_status_code")}
                           for row in bindings if str(row.get("product_id") or "") in target_product_ids]
        result["ozon_documents"].append({
            "certificate_id": str(record.get("certificate_id") or ""),
            "certificate_number": number,
            "status_code": record.get("status_code"),
            "type_code": record.get("type_code"),
            "issue_date": record.get("issue_date"),
            "expire_date": record.get("expire_date"),
            "binding_count": len(bindings),
            "binding_status_counts": dict(collections.Counter(str(row.get("product_status_code") or "MISSING")
                                                                for row in bindings)),
            "exact_target_bindings": target_bindings,
        })
    result["summary"] = {
        "ozon_active_exact_targets": sum(row["is_archived"] is False for row in result["targets"]),
        "ozon_identity_mismatches_to_snapshot": sum(
            row["product_id"] != str(next(src.get("product_id") or "" for src in targets
                                           if str(src.get("offer_id") or "") == row["offer_id"]))
            for row in result["targets"]),
        "wb_exact_cards": sum(len(row["wb_exact_cards"]) for row in result["targets"]),
        "wb_missing_cards": sum(not row["wb_exact_cards"] for row in result["targets"]),
        "wb_ambiguous_offers": sum(len(row["wb_exact_cards"]) != 1 for row in result["targets"]),
        "ozon_target_document_records_found": len(result["ozon_documents"]),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "checked_at_utc": result["checked_at_utc"],
                      "summary": result["summary"], "ozon_documents": result["ozon_documents"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
