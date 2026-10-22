"""Read-only exact live reconciliation for selected IN HOME declaration groups."""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

from api_client import BASE, Client, now, save

ROOT = BASE.parents[1]
COVERAGE = ROOT / "output_to_user/certificates/group_2/IN_HOME/coverage.csv"
MANIFEST = ROOT / "output_to_user/certificates/group_2/IN_HOME/manifest.csv"
OUT = "inhome_37790_live_recheck_20261014.json"
DOCS = {
    "ЕАЭС N RU Д-CN.PA03.B.37790/26": "ЕАЭС N RU Д-CN.РА03.В.37790/26",
}
CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm_number(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    manifest = read_csv(MANIFEST)
    assigned: dict[str, dict[str, dict[str, str]]] = {number: {} for number in DOCS}
    for row in manifest:
        number = row.get("Номер документа", "")
        if number in assigned:
            assigned[number][row["Артикул продавца"]] = row

    client = Client()
    offers = sorted({offer for rows in assigned.values() for offer in rows})
    product_id_to_offer = {}
    for rows in assigned.values():
        for offer, row in rows.items():
            product_id = str(row.get("Ozon Product ID", ""))
            if product_id in product_id_to_offer and product_id_to_offer[product_id] != offer:
                raise RuntimeError(f"Local manifest has duplicate Ozon product ID {product_id}")
            product_id_to_offer[product_id] = offer
    products_response = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = products_response.get("items") or products_response.get("result", {}).get("items")
    if not isinstance(products, list):
        raise RuntimeError("Ozon product info response is malformed")
    products_by_offer = {str(item.get("offer_id") or ""): item for item in products}
    if set(products_by_offer) != set(offers) or len(products_by_offer) != len(products):
        raise RuntimeError("Ozon product info response has missing or duplicate offers")

    ozon_records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is malformed")
        ozon_records.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded the safe limit")

    documents: dict[str, list[dict]] = {}
    target_ids: dict[str, dict[str, dict]] = {}
    for local_number, ozon_number in DOCS.items():
        matches = [r for r in ozon_records if norm_number(r.get("certificate_number")) == norm_number(ozon_number)]
        documents[local_number] = []
        target_ids[local_number] = {}
        for record in matches:
            bindings = client.ozon_bindings(record["certificate_id"])
            summary = {k: v for k, v in record.items() if k not in {"certificate_file", "file_content"}}
            summary["binding_count_live"] = len(bindings)
            summary["binding_status_counts_live"] = dict(collections.Counter(
                str(b.get("product_status_code") or "") for b in bindings))
            matched = []
            for b in bindings:
                product_id = str(b.get("product_id") or "")
                offer = product_id_to_offer.get(product_id, "")
                if offer in assigned[local_number]:
                    expected_sku = str(assigned[local_number][offer].get("Ozon SKU", ""))
                    target_ids[local_number][offer] = b
                    matched.append({"offer_id": offer, "product_id": str(b.get("product_id") or ""),
                                    "sku": str(b.get("sku") or ""), "expected_sku": expected_sku,
                                    "sku_matches": str(b.get("sku") or "") == expected_sku,
                                    "status": b.get("product_status_code")})
            summary["exact_target_bindings"] = sorted(matched, key=lambda x: x["offer_id"])
            documents[local_number].append(summary)

    wb_targets = {}
    for number, rows in assigned.items():
        wb_targets[number] = []
        for offer, row in sorted(rows.items()):
            cards = client.wb_cards(offer)
            for card in cards:
                docs = card.get("documents") or card.get("docs") or {}
                items = docs.get("items") or []
                target_docs = [item for item in items if norm_number(item.get("number")) in
                               {norm_number(number), norm_number(DOCS[number])}]
                wb_targets[number].append({
                    "offer_id": offer,
                    "expected_product_id": str(row.get("Ozon Product ID", "")),
                    "expected_sku": str(row.get("Ozon SKU", "")),
                    "nmID": str(card.get("nmID") or ""),
                    "vendorCode": str(card.get("vendorCode") or ""),
                    "brand": card.get("brand"),
                    "document_matches": target_docs,
                    "overallVerdict": docs.get("overallVerdict"),
                })

    result = {
        "checked_at": now(),
        "read_only": True,
        "coverage_offers": offers,
        "local_manifest_offer_counts": {n: len(rows) for n, rows in assigned.items()},
        "ozon_live_products": {
            offer: {"product_id": str(products_by_offer[offer].get("id") or products_by_offer[offer].get("product_id") or ""),
                    "expected_product_id": next(rows[offer].get("Ozon Product ID", "") for rows in assigned.values() if offer in rows),
                    "sku": str(products_by_offer[offer].get("sku") or ""),
                    "expected_sku": next(rows[offer].get("Ozon SKU", "") for rows in assigned.values() if offer in rows)}
            for offer in offers
        },
        "ozon_documents": documents,
        "wb_exact_cards": wb_targets,
    }
    save(OUT, result)
    print(json.dumps({
        "output": OUT,
        "checked_at": result["checked_at"],
        "offer_counts": result["local_manifest_offer_counts"],
        "ozon_records": {n: [{"id": r.get("certificate_id"), "status": r.get("status_code"),
                              "bindings": r.get("binding_count_live"), "target_bindings": len(r.get("exact_target_bindings", [])),
                              "target_statuses": dict(collections.Counter(x.get("status") for x in r.get("exact_target_bindings", []))),
                              "sku_mismatches": sum(not x.get("sku_matches") for x in r.get("exact_target_bindings", []))}
                             for r in records] for n, records in documents.items()},
        "wb": {n: {
            "target_cards": len(rows),
            "exact_vendor_code_cards": sum(r["vendorCode"] == r["offer_id"] for r in rows),
            "document_rows": sum(bool(r["document_matches"]) for r in rows),
            "document_verdicts": dict(collections.Counter(str(item.get("verdict", {}).get("reason") or item.get("verdict", {}).get("status"))
                                                            for r in rows for item in r["document_matches"])),
            "overall_reasons": dict(collections.Counter(str((r.get("overallVerdict") or {}).get("reason") or "") for r in rows)),
        } for n, rows in wb_targets.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
