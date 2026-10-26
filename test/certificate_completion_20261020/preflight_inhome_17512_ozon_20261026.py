"""Read-only preflight for IN HOME declaration 17512/24 on Ozon."""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "certificate_api_pilot_20261012"
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now  # noqa: E402

ROOT = BASE.parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "inhome_17512_ozon_preflight_20261026.json"
SOURCE = ROOT / "output_to_user/certificates/additional_search/brand_research/in_home/followup_2026_10_02/manufacturer_lamps_037_17512_24.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА06.В.17512/24"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/19120885/product"
ISSUE_DATE = date(2024, 7, 26)
EXPIRY_DATE = date(2029, 7, 17)
TNVED = "8539520009"
CHAR_MAP = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"M", "Н":"H", "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X", "Я":"R", "Д":"D"})
TARGETS = [
    {"offer_id": "4690612030777-10", "product_id": "407500333", "sku": "784791143"},
    {"offer_id": "4690612030814-10", "product_id": "407500353", "sku": "784791389"},
]


def norm(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).upper().translate(CHAR_MAP)
    return re.sub(r"[^0-9A-Z]", "", value)


def list_certs(client: Client) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response incomplete")
        out.extend(batch)
        if len(batch) < 100:
            return out
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def main() -> None:
    if not SOURCE.is_file():
        raise RuntimeError("Signed source PDF is missing")
    source_hash = digest(SOURCE)
    with (ROOT / "output_to_user/certificates/document_catalog_master.csv").open(encoding="utf-8-sig", newline="") as stream:
        matches = [row for row in csv.DictReader(stream) if norm(NUMBER) in norm(row.get("Номера/названия документов", ""))]
    if len(matches) != 1 or matches[0].get("SHA256") != source_hash:
        raise RuntimeError("Signed source PDF hash differs from the document catalog")

    client = Client()
    certificates = list_certs(client)
    duplicates = [row for row in certificates if norm(row.get("certificate_number")) == norm(NUMBER)]
    if duplicates:
        raise RuntimeError("Matching Ozon declaration appeared; reconcile it instead of creating another")

    offers = [row["offer_id"] for row in TARGETS]
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attribute_rows = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result")
    if not isinstance(product_rows, list) or not isinstance(attribute_rows, list):
        raise RuntimeError("Fresh Ozon product read incomplete")
    products = {str(row.get("offer_id")): row for row in product_rows}
    attrs = {str(row.get("offer_id")): row for row in attribute_rows}
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("Fresh Ozon product identity set differs from target set")

    checked = []
    for target in TARGETS:
        product = products[target["offer_id"]]
        attr_row = attrs[target["offer_id"]]
        by_id = {str(item.get("id")): item for item in attr_row.get("attributes") or []}
        brands = [str(value.get("value") or "").strip() for value in (by_id.get("85") or {}).get("values") or []]
        tnved = [str(value.get("value") or "").split(" - ", 1)[0].strip() for value in (by_id.get("22232") or {}).get("values") or []]
        name = str(product.get("name") or "")
        row = {
            **target,
            "live_product_id": str(product.get("id") or product.get("product_id") or ""),
            "live_sku": str(product.get("sku") or ""),
            "is_archived": product.get("is_archived"),
            "name": name,
            "brand_values": brands,
            "tnved_codes": tnved,
        }
        if row["live_product_id"] != target["product_id"] or row["live_sku"] != target["sku"] or row["is_archived"] is not False:
            raise RuntimeError("Target identity/archive changed: " + target["offer_id"])
        if brands != ["IN HOME"] or tnved != [TNVED] or "GX53" not in name.upper():
            raise RuntimeError("Live brand, model, or TNVED is outside FSA scope: " + target["offer_id"])
        checked.append(row)

    snapshot = json.loads((HERE / "live_marketplaces_snapshot_export_20261026.json").read_text(encoding="utf-8"))
    approved_bound_product_ids = {
        str(binding.get("product_id"))
        for record in snapshot["ozon_certificates"]["certificates"]
        if record.get("status_code") == "approved"
        for binding in record.get("live_bindings", [])
        if binding.get("product_status_code") == "approved"
    }
    if any(row["product_id"] in approved_bound_product_ids for row in checked):
        raise RuntimeError("An Ozon target already had approved coverage in the latest complete snapshot")
    if not ISSUE_DATE <= date.today() <= EXPIRY_DATE:
        raise RuntimeError("FSA declaration is outside its active date range")

    result = {
        "checked_at_utc": now(),
        "read_only": True,
        "upload_eligible": True,
        "platform": "Ozon",
        "document_number": NUMBER,
        "document_type": "declaration",
        "issue_date": ISSUE_DATE.isoformat(),
        "expire_date": EXPIRY_DATE.isoformat(),
        "source_file": str(SOURCE),
        "source_sha256": source_hash,
        "source_catalog_sha256_match": True,
        "fsa_record_url": FSA_URL,
        "fsa_status": "Действует",
        "fsa_registration_date": "2024-07-26",
        "fsa_tnved": ["8539520002", "8539520003", "8539520009", "8539520001"],
        "fsa_scope": "IN HOME LED lamps; series includes LED-GX53-VC; TR EAEU 037/2016",
        "snapshot_checked_at": snapshot["ozon_products"].get("checked_at"),
        "target_count": len(checked),
        "targets": checked,
        "all_targets_uncovered_in_latest_complete_snapshot": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preflight": str(OUT), "upload_eligible": True, "targets": len(checked), "source_sha256": source_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()
