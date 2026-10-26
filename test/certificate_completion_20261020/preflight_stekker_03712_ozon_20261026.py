"""Read-only preflight for Stekker certificate 03712/22 on Ozon."""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now  # noqa: E402

ROOT = BASE.parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "stekker_03712_ozon_preflight_20261026.json"
SOURCE = ROOT / "output_to_user/certificates/additional_search/docs/stekker/feron_store/03712_Водонепроницаемые_распределительные_коробки_тм_Stekker_серия_LD_1.jpg"
NUMBER = "ЕАЭС RU C-CN.FA05.B.03712/22"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3132759/baseInfo"
ISSUE_DATE = date(2022, 8, 22)
EXPIRY_DATE = date(2027, 8, 21)
TNVED = "8536901000"
TARGETS = [
    {"offer_id": "49115-1", "product_id": "6126388296", "sku": "5612489920"},
    {"offer_id": "49121-1", "product_id": "6126388287", "sku": "5612492810"},
    {"offer_id": "49122-1", "product_id": "6126388286", "sku": "5612491233"},
    {"offer_id": "49124-1", "product_id": "6126388304", "sku": "5612489266"},
    {"offer_id": "49189-1", "product_id": "6126388314", "sku": "5612491847"},
    {"offer_id": "50128-1", "product_id": "6126388269", "sku": "5612493847"},
    {"offer_id": "50130-1", "product_id": "6126388331", "sku": "5612492404"},
    {"offer_id": "50552-1", "product_id": "6126388351", "sku": "5612492037"},
    {"offer_id": "50553-1", "product_id": "6126388343", "sku": "5612493131"},
    {"offer_id": "50554-1", "product_id": "6126388377", "sku": "5612494372"},
    {"offer_id": "50555-1", "product_id": "6126388347", "sku": "5612492665"},
    {"offer_id": "50556-1", "product_id": "6126388306", "sku": "5612491527"},
]


def norm(text: object) -> str:
    return re.sub(r"[^0-9A-ZА-ЯЁ]", "", unicodedata.normalize("NFKC", str(text or "")).upper())


def list_certs(client: Client) -> list[dict]:
    records: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response incomplete")
        records.extend(batch)
        if len(batch) < 100:
            return records
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def main() -> None:
    if not SOURCE.is_file():
        raise RuntimeError("Source image is missing")
    actual_hash = digest(SOURCE)
    with (ROOT / "output_to_user/certificates/document_catalog_master.csv").open(encoding="utf-8-sig", newline="") as stream:
        matching = [row for row in csv.DictReader(stream) if NUMBER in row.get("Номера/названия документов", "")]
    if len(matching) != 1 or matching[0].get("SHA256") != actual_hash:
        raise RuntimeError("Source image hash does not match the document catalog")

    client = Client()
    certificates = list_certs(client)
    duplicates = [row for row in certificates if norm(row.get("certificate_number")) == norm(NUMBER)]
    if duplicates:
        raise RuntimeError("Matching Ozon certificate appeared; reconcile it instead of creating another")

    offers = [row["offer_id"] for row in TARGETS]
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attribute_rows = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result")
    if not isinstance(product_rows, list) or not isinstance(attribute_rows, list):
        raise RuntimeError("Fresh Ozon product read incomplete")
    product_by_offer = {str(row.get("offer_id")): row for row in product_rows}
    attributes_by_offer = {str(row.get("offer_id")): row for row in attribute_rows}
    if set(product_by_offer) != set(offers) or set(attributes_by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon product identity set differs from the requested targets")

    checked: list[dict] = []
    for target in TARGETS:
        product = product_by_offer[target["offer_id"]]
        attribute_row = attributes_by_offer[target["offer_id"]]
        values = {str(row.get("id")): row for row in attribute_row.get("attributes") or []}
        brands = [str(value.get("value") or "").strip() for value in (values.get("85") or {}).get("values") or []]
        tnved = [str(value.get("value") or "").split(" - ", 1)[0].strip() for value in (values.get("22232") or {}).get("values") or []]
        row = {
            **target,
            "live_product_id": str(product.get("id") or product.get("product_id") or ""),
            "live_sku": str(product.get("sku") or ""),
            "is_archived": product.get("is_archived"),
            "name": product.get("name"),
            "brand_values": brands,
            "tnved_codes": tnved,
        }
        if row["live_product_id"] != target["product_id"] or row["live_sku"] != target["sku"] or row["is_archived"] is not False:
            raise RuntimeError("Ozon target identity/archive changed: " + target["offer_id"])
        if brands != ["Stekker"] or tnved != [TNVED]:
            raise RuntimeError("Ozon brand or TNVED is outside the FSA scope: " + target["offer_id"])
        if "LD" not in str(row["name"]).upper() and "РАСПРЕДЕЛИТЕЛЬНАЯ КОРОБКА" not in str(row["name"]).upper():
            raise RuntimeError("Ozon product name no longer matches certificate scope: " + target["offer_id"])
        checked.append(row)

    snapshot = json.loads((HERE / "live_marketplaces_snapshot_export_20261026.json").read_text(encoding="utf-8"))
    approved_bound_product_ids = {
        str(binding.get("product_id"))
        for record in snapshot["ozon_certificates"]["certificates"]
        if record.get("status_code") == "approved"
        for binding in record.get("live_bindings", [])
        if binding.get("product_status_code") == "approved"
    }
    targets_without_approved_snapshot_coverage = [
        row["offer_id"] for row in checked if row["product_id"] not in approved_bound_product_ids
    ]
    if targets_without_approved_snapshot_coverage != offers:
        raise RuntimeError("At least one target had an approved Ozon document in the latest complete snapshot")
    if date.today() < ISSUE_DATE or date.today() > EXPIRY_DATE:
        raise RuntimeError("FSA certificate is outside its active date range")

    result = {
        "checked_at_utc": now(),
        "read_only": True,
        "upload_eligible": True,
        "platform": "Ozon",
        "document_number": NUMBER,
        "document_type": "certificate_of_conformity",
        "issue_date": ISSUE_DATE.isoformat(),
        "expire_date": EXPIRY_DATE.isoformat(),
        "source_file": str(SOURCE),
        "source_sha256": actual_hash,
        "source_catalog_sha256_match": True,
        "fsa_record_url": FSA_URL,
        "fsa_status": "Действует",
        "fsa_tnved": TNVED,
        "fsa_scope": "Соединители электрические: водонепроницаемые распределительные коробки, торговая марка Stekker, серия LD",
        "snapshot_checked_at": snapshot["ozon_products"].get("checked_at"),
        "target_count": len(checked),
        "targets": checked,
        "all_targets_uncovered_in_latest_complete_snapshot": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preflight": str(OUT), "upload_eligible": True, "targets": len(checked), "source_sha256": actual_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()
