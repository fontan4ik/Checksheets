"""Fresh read-only preflight for the four IN HOME SIMPLE products under declaration 45373/25."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now

ROOT = BASE.parents[1]
GROUP = ROOT / "output_to_user/certificates/group_2/IN_HOME"
MANIFEST = GROUP / "manifest.csv"
NUMBER = "ЕАЭС N RU Д-CN.PA09.В.45373/25"
CANONICAL_NUMBER = "ЕАЭС N RU Д-CN.PA09.B.45373/25"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/20742159"
FSA_CODES = {"9405210012", "9405210032", "9405420022"}
OUT = BASE / "inhome_45373_upload_preflight_20261013_1828Z.json"

CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                          "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                          "Ё": "E", "Э": "E", "Д": "D", "П": "P"})


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    with MANIFEST.open(newline="", encoding="utf-8-sig") as stream:
        rows = [r for r in csv.DictReader(stream)
                if norm(r.get("Номер документа")) == norm(CANONICAL_NUMBER)]
    if len(rows) != 4 or {r.get("Модель/серия сопоставления") for r in rows} != {"SIMPLE"}:
        raise RuntimeError("Manifest does not resolve to exactly four SIMPLE targets")
    offers = [str(r["Артикул продавца"]) for r in rows]
    if len(set(offers)) != 4:
        raise RuntimeError("Duplicate offer in local manifest")
    file_paths = {GROUP / r["Локальный файл"] for r in rows}
    if len(file_paths) != 1:
        raise RuntimeError("Document group does not resolve to one source PDF")
    pdf = next(iter(file_paths))
    if not pdf.is_file():
        raise RuntimeError("Official source PDF is missing")

    client = Client()
    product_body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = product_body.get("items") or product_body.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != 4:
        raise RuntimeError("Fresh Ozon product read is incomplete")
    by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon product list contains a missing/extra offer")

    attr_body = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)})
    attr_rows = attr_body.get("result") or attr_body.get("items")
    if not isinstance(attr_rows, list) or len(attr_rows) != 4:
        raise RuntimeError("Fresh Ozon attributes read is incomplete")
    by_attr_offer = {str(x.get("offer_id") or ""): x for x in attr_rows}
    if set(by_attr_offer) != set(offers):
        raise RuntimeError("Fresh Ozon attributes contain a missing/extra offer")

    certs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response is malformed")
        certs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate list exceeded pagination limit")
    matching_records = [c for c in certs if norm(c.get("certificate_number")) == norm(CANONICAL_NUMBER)]

    targets = []
    wb_all = []
    local_by_offer = {str(r["Артикул продавца"]): r for r in rows}
    for offer in offers:
        local = local_by_offer[offer]
        p = by_offer[offer]
        attrs = {str(a.get("id")): a for a in (by_attr_offer[offer].get("attributes") or [])}
        brands = [str(v.get("value") or "") for v in (attrs.get("85") or {}).get("values") or []]
        tnved_values = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
        tnved_codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
        current_product_id = str(p.get("id") or p.get("product_id") or "")
        current_sku = str(p.get("sku") or "")
        wb_cards = client.wb_cards(offer)
        wb_all.extend(wb_cards)
        targets.append({
            "offer_id": offer,
            "expected_product_id": str(local.get("Ozon Product ID") or ""),
            "live_product_id": current_product_id,
            "expected_sku": str(local.get("Ozon SKU") or ""),
            "live_sku": current_sku,
            "is_archived": p.get("is_archived"),
            "name": p.get("name"),
            "brand_values": brands,
            "tnved_values": tnved_values,
            "tnved_codes": tnved_codes,
            "wb_cards": [{"vendorCode": c.get("vendorCode"), "nmID": c.get("nmID"),
                          "brand": c.get("brand"), "documents": c.get("documents")}
                         for c in wb_cards],
        })

    identities_exact = all(t["live_product_id"] == t["expected_product_id"]
                           and t["live_sku"] == t["expected_sku"]
                           and t["is_archived"] is False for t in targets)
    model_exact = all("SIMPLE" in str(t["name"]).upper() for t in targets)
    brands_exact = all(t["brand_values"] == ["IN HOME"] for t in targets)
    codes_in_scope = all(t["tnved_codes"] and set(t["tnved_codes"]).issubset(FSA_CODES)
                         for t in targets)
    wb_exact = all(len(t["wb_cards"]) == 1 and t["wb_cards"][0]["vendorCode"] == t["offer_id"]
                   for t in targets)
    state = {
        "checked_at_utc": now(), "read_only": True, "complete": True,
        "official_fsa_record": {"record_id": 20742159, "url": FSA_URL,
            "status": "Действует", "registration_date": "2025-10-22", "expiry_date": "2030-10-19",
            "number": CANONICAL_NUMBER,
            "scope": "IN HOME portable LED luminaires; table models PLUS, SIMPLE, CRAFT; floor models THO/TCO",
            "tnved_codes_from_signed_declaration": sorted(FSA_CODES),
            "verified_in_official_fsa_ui_at": "2026-10-13", "pdf_page_visually_checked": True},
        "source_pdf": {"path": str(pdf), "sha256": sha256(pdf), "bytes": pdf.stat().st_size,
                       "source_url": rows[0].get("URL документа")},
        "ozon_certificate_list_count": len(certs),
        "matching_ozon_records": [{k: v for k, v in c.items() if k not in {"certificate_file", "file_content"}}
                                   for c in matching_records],
        "targets": targets,
        "checks": {"four_targets_exact": len(targets) == 4, "ozon_identities_exact": identities_exact,
                   "model_exact": model_exact, "brand_exact": brands_exact,
                   "tnved_within_official_scope": codes_in_scope,
                   "no_duplicate_ozon_number": len(matching_records) == 0,
                   "wb_exact_cards_all_found": wb_exact,
                   "wb_cards_found": sum(len(t["wb_cards"]) for t in targets)},
    }
    state["ozon_upload_eligible"] = all(state["checks"][k] for k in (
        "four_targets_exact", "ozon_identities_exact", "model_exact", "brand_exact",
        "tnved_within_official_scope", "no_duplicate_ozon_number"))
    state["wb_fully_mappable"] = wb_exact
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "ozon_upload_eligible": state["ozon_upload_eligible"],
                      "wb_fully_mappable": wb_exact, "matching_ozon_records": len(matching_records),
                      "targets": [{"offer_id": t["offer_id"], "product_id": t["live_product_id"],
                                   "sku": t["live_sku"], "tnved_codes": t["tnved_codes"],
                                   "wb_cards": len(t["wb_cards"])} for t in targets]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
