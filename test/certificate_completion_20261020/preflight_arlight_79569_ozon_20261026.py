"""Read-only scope, validity, identity, duplicate, and coverage gate for Arlight 79569/26."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.79569/26"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/A71899A514D3B94EBAFC991009B65468.pdf"
SOURCE_SHA256 = "ad13ebf99dfd7db849a639f56aa343323af516ba3866b3dea49c7f80a85e79fe"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_export_20261026.json"
OUT = HERE / "arlight_79569_ozon_preflight_20261026.json"
FSA_ID = 21145052
FSA_URL = f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"
ISSUE_DATE = "2026-02-13"
EXPIRY_DATE = "2031-02-11"
TNVED = "8543708000"
TARGET_OFFER = "020956-1"
TARGET_PRODUCT_ID = "6360298780"
TARGET_SKU = "5816416802"


def norm(value: object) -> str:
    char_map = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"M", "Н":"H", "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X", "Я":"R", "Д":"D"})
    text = unicodedata.normalize("NFKC", str(value or "")).upper().translate(char_map)
    return re.sub(r"[^0-9A-Z]", "", text)


def list_certificates(client: Client) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list is incomplete")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Preflight output exists; inspect it before replacing")
    if not SNAPSHOT.is_file():
        raise RuntimeError("Complete live Ozon snapshot is missing")
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if not snapshot.get("ozon_products", {}).get("complete") or not snapshot.get("ozon_certificates", {}).get("complete"):
        raise RuntimeError("Ozon baseline snapshot is incomplete")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Signed source PDF is missing or its audited hash changed")

    assignments = list(csv.DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline="")))
    number_key = norm("RU Д-CN.РА01.В.79569/26")
    rows = [r for r in assignments if norm(r.get("Номер/название документа")).endswith(number_key)]
    targets = [r for r in rows if r.get("Артикул продавца") == TARGET_OFFER]
    if len(targets) != 1:
        raise RuntimeError(f"Expected one source assignment for {TARGET_OFFER}; got {len(targets)}")
    assignment = targets[0]
    if assignment.get("Локальный файл") != str(SOURCE.relative_to(ROOT)) or assignment.get("SHA256 фактический") != SOURCE_SHA256:
        raise RuntimeError("Assignment file path/hash does not match the audited signed document")
    if assignment.get("Бренд подтвержденный") != "Arlight" or assignment.get("Применимость") != "Подтверждено статусом покрытия":
        raise RuntimeError("The source assignment is not an exact Arlight product mapping")

    snapshot_products = {str(p.get("offer_id")): p for p in snapshot["ozon_products"]["products"]}
    baseline = snapshot_products.get(TARGET_OFFER)
    if not baseline or str(baseline.get("product_id")) != TARGET_PRODUCT_ID or str(baseline.get("sku")) != TARGET_SKU or baseline.get("is_archived"):
        raise RuntimeError("Snapshot product identity or active state does not match the audited target")

    # Refuse if the target already has an active approved certificate binding in the complete baseline.
    by_sku = {str(p.get("sku")): p for p in snapshot["ozon_products"]["products"] if p.get("sku")}
    approved_cover: list[dict] = []
    today = dt.date.today().isoformat()
    for cert in snapshot["ozon_certificates"]["certificates"]:
        if cert.get("status_code") != "approved" or str(cert.get("issue_date") or "")[:10] > today or str(cert.get("expire_date") or "")[:10] < today:
            continue
        for binding in cert.get("live_bindings") or []:
            p = by_sku.get(str(binding.get("sku") or ""))
            if (p and str(p.get("product_id")) == TARGET_PRODUCT_ID and str(binding.get("product_id")) == TARGET_PRODUCT_ID
                    and binding.get("product_status_code") == "approved"):
                approved_cover.append({"certificate_number": cert.get("certificate_number"), "certificate_id": cert.get("certificate_id")})
    if approved_cover:
        raise RuntimeError("The Ozon product already has a current approved certificate binding: " + json.dumps(approved_cover, ensure_ascii=False))

    client = Client()
    certs = list_certificates(client)
    duplicates = [r for r in certs if norm(r.get("certificate_number")) == norm(NUMBER)]
    if duplicates:
        raise RuntimeError("Ozon already contains this declaration number; reconcile instead of creating a duplicate")
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": [TARGET_OFFER]}).get("items")
    attribute_rows = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [TARGET_OFFER]}, "limit": 1}).get("result")
    if not isinstance(product_rows, list) or len(product_rows) != 1 or not isinstance(attribute_rows, list) or len(attribute_rows) != 1:
        raise RuntimeError("Fresh Ozon product and attribute reads are incomplete")
    product, attrs = product_rows[0], attribute_rows[0]
    attr_map = {str(x.get("id")): x for x in attrs.get("attributes") or []}
    brands = [str(x.get("value") or "").strip() for x in (attr_map.get("85") or {}).get("values") or []]
    tnved = [str(x.get("value") or "").split(" - ", 1)[0].strip() for x in (attr_map.get("22232") or {}).get("values") or []]
    live = {
        "offer_id": TARGET_OFFER,
        "product_id": str(product.get("id") or product.get("product_id") or ""),
        "sku": str(product.get("sku") or ""),
        "name": product.get("name") or "",
        "is_archived": product.get("is_archived"),
        "brand_values": brands,
        "tnved_codes": tnved,
    }
    if live["product_id"] != TARGET_PRODUCT_ID or live["sku"] != TARGET_SKU or live["is_archived"] is not False:
        raise RuntimeError("Fresh Ozon product identity/archive state changed")
    if brands != ["Arlight"] or tnved != [TNVED] or "ИК-СПЛИТТЕР" not in live["name"].upper() or "SR-DOOR-SWITCH" not in live["name"].upper():
        raise RuntimeError("Fresh Ozon brand, model, or TNVED is outside the official declaration scope")
    if assignment.get("Название товара Ozon") != live["name"]:
        raise RuntimeError("Current Ozon title differs from exact source assignment")

    exclusions = []
    for row in rows:
        offer = str(row.get("Артикул продавца") or "")
        if offer == TARGET_OFFER:
            continue
        p = snapshot_products.get(offer)
        codes = {str(v).split(" - ", 1)[0].strip() for v in (p or {}).get("tnved_values") or []}
        exclusions.append({"offer_id": offer, "tnved_codes": sorted(codes), "reason": "TNVED is outside declaration's 8543708000 scope"})
    if len(exclusions) != 13:
        raise RuntimeError(f"Unexpected excluded source assignment count: {len(exclusions)}")
    if any(TNVED in x["tnved_codes"] for x in exclusions):
        raise RuntimeError("At least one excluded assignment has the declaration's exact TNVED and needs review")

    output = {
        "checked_at_utc": now(),
        "read_only": True,
        "upload_eligible": True,
        "platform": "Ozon",
        "document_number": NUMBER,
        "document_type": "DECLARATION",
        "issue_date": ISSUE_DATE,
        "expire_date": EXPIRY_DATE,
        "fsa_record_id": FSA_ID,
        "fsa_record_url": FSA_URL,
        "fsa_status": "active",
        "fsa_scope": "Arlight and Intelligent Arlight amplifiers, splitters and SR-series infrared splitters",
        "fsa_tnved": TNVED,
        "fsa_source_verified_by": "FSA public registry UI, checked 2026-10-26",
        "source_file": str(SOURCE),
        "source_sha256": SOURCE_SHA256,
        "ozon_certificate_count_checked": len(certs),
        "snapshot_checked_at": snapshot["ozon_products"]["checked_at"],
        "baseline_approved_binding_count_for_target": len(approved_cover),
        "target_count": 1,
        "targets": [live],
        "scope_mismatch_excluded_count": len(exclusions),
        "scope_mismatch_excluded": exclusions,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preflight": str(OUT), "upload_eligible": True, "target_count": 1,
                      "excluded_scope_mismatch_count": len(exclusions), "source_sha256": SOURCE_SHA256,
                      "duplicate_records": len(duplicates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
