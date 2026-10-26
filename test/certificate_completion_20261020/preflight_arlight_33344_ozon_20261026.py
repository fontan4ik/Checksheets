"""Read-only exact-scope preflight for Arlight dimmer declaration 33344/26."""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
API_BASE = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API_BASE))
from api_client import Client, digest, now  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/DCE8C157436F3C4E9898E20868978ACD.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_export_20261026.json"
OUT = HERE / "arlight_33344_ozon_preflight_20261026.json"
EXPECTED_SHA256 = ""  # Filled from the audited assignment file at runtime.
EXPECTED_TNVED = "8537109800"
ISSUE_DATE = "2026-04-13"
EXPIRE_DATE = "2031-04-09"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/21321061"
CHAR_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "Я": "R", "Д": "D",
})


def norm(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).upper().translate(CHAR_MAP)
    return re.sub(r"[^0-9A-Z]", "", value)


def list_certificates(client: Client) -> list[dict]:
    records: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is incomplete")
        records.extend(batch)
        if len(batch) < 100:
            return records
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not snapshot.get("ozon_products", {}).get("complete") or not snapshot.get("ozon_certificates", {}).get("complete"):
        raise RuntimeError("The last full Ozon snapshot is incomplete")
    products = {str(row["offer_id"]): row for row in snapshot["ozon_products"]["products"]}
    approved_ids: set[str] = set()
    for certificate in snapshot["ozon_certificates"]["certificates"]:
        if certificate.get("status_code") != "approved":
            continue
        for binding in certificate.get("live_bindings") or []:
            if binding.get("product_status_code") == "approved":
                approved_ids.add(str(binding.get("product_id")))

    assignments = list(csv.DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline="")))
    rows = [row for row in assignments if norm(row.get("Номер/название документа")) == norm(NUMBER)]
    if not rows:
        raise RuntimeError("No source assignments found for the declaration number")
    files = {str(row.get("Локальный файл") or "") for row in rows}
    hashes = {str(row.get("SHA256 фактический") or "").strip() for row in rows if row.get("SHA256 фактический")}
    if files != {str(SOURCE.relative_to(ROOT))} or len(hashes) != 1:
        raise RuntimeError("Source assignment rows disagree on local file or audited digest")
    source_hash = next(iter(hashes))
    if digest(SOURCE) != source_hash or (EXPECTED_SHA256 and source_hash != EXPECTED_SHA256):
        raise RuntimeError("Signed source PDF no longer matches its audited SHA-256")

    by_offer: dict[str, dict] = {}
    for row in rows:
        offer = str(row["Артикул продавца"])
        product = products.get(offer)
        if not product or product.get("is_archived"):
            continue
        codes = {str(value).split(" - ", 1)[0].strip() for value in product.get("tnved_values") or []}
        if EXPECTED_TNVED not in codes:
            continue
        if str(product.get("product_id")) in approved_ids:
            continue
        by_offer[offer] = {
            "offer_id": offer,
            "product_id": str(product["product_id"]),
            "sku": str(product["sku"]),
            "snapshot_brand_values": product.get("brand_values") or [],
            "snapshot_tnved_values": product.get("tnved_values") or [],
            "snapshot_name": product.get("name") or "",
        }
    targets = [by_offer[key] for key in sorted(by_offer)]
    if not targets:
        raise RuntimeError("No uncovered live products with the exact FSA TNVED code")

    client = Client()
    certificates = list_certificates(client)
    duplicates = [row for row in certificates if norm(row.get("certificate_number")) == norm(NUMBER)]
    if duplicates:
        raise RuntimeError("Ozon already has a record with this declaration number; reconcile instead of creating another")

    offers = [row["offer_id"] for row in targets]
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attribute_rows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(product_rows, list) or not isinstance(attribute_rows, list):
        raise RuntimeError("Fresh Ozon product identity read was incomplete")
    products_by_offer = {str(row.get("offer_id")): row for row in product_rows}
    attrs_by_offer = {str(row.get("offer_id")): row for row in attribute_rows}
    if set(products_by_offer) != set(offers) or set(attrs_by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon result set does not match the preflight offer list")

    fresh_targets = []
    for target in targets:
        product = products_by_offer[target["offer_id"]]
        attr_items = {str(item.get("id")): item for item in attrs_by_offer[target["offer_id"]].get("attributes") or []}
        brands = [str(value.get("value") or "").strip() for value in (attr_items.get("85") or {}).get("values") or []]
        tnveds = [str(value.get("value") or "").split(" - ", 1)[0].strip() for value in (attr_items.get("22232") or {}).get("values") or []]
        live = {
            **target,
            "live_product_id": str(product.get("id") or product.get("product_id") or ""),
            "live_sku": str(product.get("sku") or ""),
            "is_archived": product.get("is_archived"),
            "name": product.get("name") or "",
            "brand_values": brands,
            "tnved_codes": tnveds,
        }
        if live["live_product_id"] != target["product_id"] or live["live_sku"] != target["sku"] or live["is_archived"] is not False:
            raise RuntimeError("Fresh product identity or archive status changed: " + target["offer_id"])
        if EXPECTED_TNVED not in tnveds:
            raise RuntimeError("Fresh Ozon TNVED differs from FSA: " + target["offer_id"])
        if not ("DIMMER" in live["name"].upper() or "ДИММЕР" in live["name"].upper() or "MICRODIMMER" in live["name"].upper() or "МИКРОДИММЕР" in live["name"].upper()):
            raise RuntimeError("Product title does not identify a dimmer: " + target["offer_id"])
        if not any("ARLIGHT" in norm(brand) for brand in brands):
            raise RuntimeError("Live product brand is outside the declaration scope: " + target["offer_id"])
        fresh_targets.append(live)

    excluded = []
    for row in rows:
        offer = str(row["Артикул продавца"])
        product = products.get(offer)
        if product and not product.get("is_archived"):
            codes = {str(value).split(" - ", 1)[0].strip() for value in product.get("tnved_values") or []}
            if EXPECTED_TNVED not in codes:
                excluded.append({"offer_id": offer, "product_id": str(product["product_id"]), "tnved_values": product.get("tnved_values") or []})

    result = {
        "checked_at_utc": now(),
        "read_only": True,
        "upload_eligible": True,
        "platform": "Ozon",
        "document_number": NUMBER,
        "document_type": "DECLARATION",
        "issue_date": ISSUE_DATE,
        "expire_date": EXPIRE_DATE,
        "fsa_record_url": FSA_URL,
        "fsa_status": "active",
        "fsa_scope": "Arlight and Intelligent Arlight dimmers/microdimmers, TNVED 8537109800",
        "expected_tnved": EXPECTED_TNVED,
        "source_file": str(SOURCE),
        "source_sha256": source_hash,
        "ozon_certificate_count_checked": len(certificates),
        "ozon_snapshot_products_checked_at": snapshot["ozon_products"]["checked_at"],
        "ozon_snapshot_bindings_checked_at": snapshot["ozon_certificates"]["checked_at"],
        "target_count": len(fresh_targets),
        "targets": fresh_targets,
        "scope_mismatch_excluded_count": len(excluded),
        "scope_mismatch_excluded": excluded,
        "fsa_registration_day": dt.date.fromisoformat(ISSUE_DATE).isoformat(),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preflight": str(OUT), "target_count": len(fresh_targets), "excluded_scope_mismatch_count": len(excluded),
                      "source_sha256": source_hash, "duplicate_records": len(duplicates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
