"""Read-only source, identity, scope, and marketplace preflight for Arlight 69060/25."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))
from api_client import Client  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402
from network_bypass import SourceAddressAdapter  # noqa: E402

LOCAL_MAP = ROOT / "test/certificate_cleanup_20261006/local_map.json"
PRODUCTS = BASE / "ozon_products_live.json"
OZON = BASE / "ozon_live.json"
WB = BASE / "wb_live_refresh_20261012_1418.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/F6522803E046324C87BC430F67671163.pdf"
SOURCE_URL = "https://arlight.ru/upload/certificates/F6522803E046324C87BC430F67671163.pdf"
REGISTRY_URL = "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product"
DOC_NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
SOURCE_SHA256 = "baeb142abdd28d42ae6cbbe4993134f3726364e94ca66c3b09d913d52b81db04"
OUT = BASE / "arlight_69060_preflight_20261012.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def current_source_download() -> dict:
    session = requests.Session()
    session.trust_env = False
    for iface in ("en1", "en0"):
        state = subprocess.run(["ifconfig", iface], capture_output=True, text=True)
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", state.stdout)
        if match and "status: active" in state.stdout:
            session.mount("https://", SourceAddressAdapter(match.group(1), interface_name=iface))
            break
    else:
        raise RuntimeError("No active physical interface for official manufacturer source check")
    response = session.get(SOURCE_URL, timeout=(15, 60), headers={"Accept": "application/pdf"})
    response.raise_for_status()
    payload = response.content
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("Official manufacturer URL did not return a PDF")
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "url": SOURCE_URL,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "last_modified": response.headers.get("Last-Modified"),
        "size_bytes": len(payload),
        "sha256": digest,
        "matches_local_source": digest == SOURCE_SHA256,
    }


def official_article_evidence(row: dict[str, str]) -> bool:
    basis = row.get("Основание сопоставления", "")
    if "Точный артикул в официальном листинге/карточке:" in basis:
        return True
    # Arlight's own product card can explicitly show the exact article and attach
    # its declaration. Accept that direct primary-source evidence too.
    match = re.fullmatch(r"https://arlight\.ru/catalog/product/(\d+)/?", row.get("URL карточки/основания", ""))
    offer_stem = str(row.get("Артикул продавца") or "").split("-", 1)[0]
    offer_stem = re.sub(r"\(.*?\)", "", offer_stem)
    return bool(match and match.group(1) == offer_stem and
                "Документ прикреплён к официальной карточке артикула;" in basis)


def main() -> None:
    local = read_json(LOCAL_MAP)
    products = read_json(PRODUCTS)
    ozon = read_json(OZON)
    wb = read_json(WB)
    if not all(x.get("complete") for x in (products, ozon, wb)):
        raise RuntimeError("Complete current Ozon product/certificate and WB catalog snapshots required")

    groups = [x for x in local.get("groups", []) if x.get("sha256") == SOURCE_SHA256]
    if len(groups) != 1:
        raise RuntimeError(f"Expected one exact local source-map group; got {len(groups)}")
    group = groups[0]
    if (not group.get("eligible_for_live_comparison") or group.get("issues")
            or {norm(x) for x in group.get("document_numbers", []) if x} != {norm(DOC_NUMBER)}):
        raise RuntimeError("Source-map group has ambiguous number or blocking issue")
    source_proof = []
    for item in group.get("files", []):
        path = Path(item["path"])
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Local source missing or symlink: {path}")
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != SOURCE_SHA256 or path.stat().st_size != item.get("size"):
            raise RuntimeError(f"Local source changed: {path}")
        source_proof.append({"path": str(path), "size_bytes": path.stat().st_size, "sha256": observed})
    if len(source_proof) != 1:
        raise RuntimeError("The exact source group should resolve to one local file")

    assignments = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256 фактический") == SOURCE_SHA256:
                assignments.append(row)
    if len(assignments) != 550:
        raise RuntimeError(f"Expected 550 assignment rows sharing the exact source file; got {len(assignments)}")
    for row in assignments:
        if (row.get("Бренд подтвержденный") != "Arlight"
                or row.get("Бренд Ozon") != "Arlight"
                or row.get("Тип документа") != "Декларация соответствия"
                or norm(row.get("Номер/название документа")) != norm(DOC_NUMBER)
                or row.get("URL документа") != SOURCE_URL
                or row.get("SHA256 фактический") != row.get("SHA256 заявленный")
                or not official_article_evidence(row)):
            raise RuntimeError(f"Manufacturer assignment evidence changed for {row.get('Артикул продавца')}")

    products_by_offer = {str(x.get("offer_id")): x for x in products.get("products", [])}
    wb_by_offer: dict[str, list[dict]] = defaultdict(list)
    for card in wb.get("cards", []):
        wb_by_offer[str(card.get("vendorCode") or "")].append(card)

    targets = []
    for row in assignments:
        offer = str(row.get("Артикул продавца") or "")
        current = products_by_offer.get(offer)
        expected_pid = str(current.get("product_id")) if current else ""
        expected_sku = str(current.get("sku")) if current else ""
        if not current or current.get("is_archived") is not False:
            raise RuntimeError(f"Current active Ozon offer missing: {offer}")
        cards = wb_by_offer.get(offer, [])
        if len(cards) > 1:
            raise RuntimeError(f"Duplicate exact WB vendorCode {offer}")
        card = cards[0] if cards else None
        existing = []
        if card:
            docs = (card.get("documents") or {}).get("items") or []
            existing = [x for x in docs if norm(x.get("number")) == norm(DOC_NUMBER)]
        targets.append({
            "offer_id": offer,
            "product_id": expected_pid,
            "sku": expected_sku,
            "name": str(current.get("name") or ""),
            "brand_from_assignment": row.get("Бренд подтвержденный"),
            "type_from_assignment": row.get("Тип товара Ozon"),
            "official_article": row.get("Основание сопоставления"),
            "wb_nmID": card.get("nmID") if card else None,
            "wb_exact_card_count": len(cards),
            "wb_exact_document_rows": existing,
        })

    exact_records = [x for x in ozon.get("certificates", [])
                     if norm(x.get("certificate_number")) == norm(DOC_NUMBER)]
    if exact_records:
        raise RuntimeError("Ozon certificate number already exists; reconcile instead of creating a duplicate")

    client = Client()
    attributes = {}
    offers = [x["offer_id"] for x in targets]
    for start in range(0, len(offers), 500):
        batch = offers[start:start + 500]
        body = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch),
        })
        result = body.get("result")
        if not isinstance(result, list):
            raise RuntimeError("Ozon attributes response omitted result")
        for item in result:
            offer = str(item.get("offer_id") or "")
            if offer not in batch or offer in attributes:
                raise RuntimeError("Ozon returned an unknown or duplicate offer in attributes")
            current = products_by_offer[offer]
            if str(item.get("id") or item.get("product_id") or "") != str(current.get("product_id")):
                raise RuntimeError(f"Ozon product ID changed during attributes read: {offer}")
            by_id = {str(a.get("id")): a for a in item.get("attributes") or []}
            def values(attribute_id: str) -> list[str]:
                attr = by_id.get(attribute_id) or {}
                return [str(v.get("value")) for v in attr.get("values") or []
                        if v.get("value") not in (None, "")]
            attributes[offer] = {
                "brand": values("85"),
                "tnved": values("22232"),
                "product_name": str(item.get("name") or current.get("name") or ""),
            }
        if {str(x.get("offer_id") or "") for x in result} != set(batch):
            raise RuntimeError("Ozon attributes batch was incomplete")
    if set(attributes) != set(offers):
        raise RuntimeError("Ozon attributes missing one or more target offers")

    brand_counts = Counter(tuple(x["brand"]) for x in attributes.values())
    tnved_counts = Counter(tuple(x["tnved"]) for x in attributes.values())
    attr_mismatches = []
    tnved_scope_exclusions = []
    for row in targets:
        attr = attributes[row["offer_id"]]
        codes = [value.split(" - ", 1)[0].strip() for value in attr["tnved"]]
        if attr["brand"] != ["Arlight"]:
            attr_mismatches.append({"offer_id": row["offer_id"], **attr})
        elif "8504408300" not in codes:
            tnved_scope_exclusions.append({"offer_id": row["offer_id"], "product_id": row["product_id"],
                                           "sku": row["sku"], "wb_nmID": row["wb_nmID"], **attr})
        row["ozon_attributes"] = attr
    scoped_targets = [x for x in targets if x["offer_id"] not in {y["offer_id"] for y in tnved_scope_exclusions}]
    wb_counts = Counter("exact_card" if x["wb_exact_card_count"] == 1 else "missing_card"
                        for x in scoped_targets)
    wb_doc_counts = Counter("present" if x["wb_exact_document_rows"] else "missing"
                            for x in scoped_targets if x["wb_exact_card_count"] == 1)
    downloaded = current_source_download()
    if not downloaded["matches_local_source"]:
        raise RuntimeError("Current official Arlight PDF differs from the local file; stopped")

    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "fsa_registry_url": REGISTRY_URL,
        "fsa_registry_status_seen_in_ui": "Действует",
        "fsa_registry_issue_date": "2025-03-10",
        "fsa_registry_expiry_date": "2030-03-09",
        "fsa_registry_tnved_scope": ["8504408300"],
        "fsa_registry_product_scope": ["ARPV", "ARDV", "HTS", "ARV", "ARS", "JTS", "HTPS", "ARJ", "ARPJ", "KNX", "DALI", "SMART"],
        "ozon_products_checked_at": products.get("checked_at"),
        "ozon_certificates_checked_at": ozon.get("checked_at"),
        "wb_catalog_checked_at": wb.get("checked_at"),
        "source_sha256": SOURCE_SHA256,
        "source_files": source_proof,
        "official_manufacturer_download": downloaded,
        "source_map_group": {"document_numbers": group.get("document_numbers"),
                             "target_bindings": len(group.get("bindings") or []),
                             "issues": group.get("issues"),
                             "local_map_sha256": hashlib.sha256(LOCAL_MAP.read_bytes()).hexdigest()},
        "assignment_summary": {
            "rows": len(assignments),
            "unique_offers": len({x["offer_id"] for x in targets}),
            "eligible_exact_tnved_offers": len(scoped_targets),
            "excluded_tnved_mismatch_offers": len(tnved_scope_exclusions),
            "brand_confirmed_counts": dict(Counter(x.get("Бренд подтвержденный", "") for x in assignments)),
            "ozon_brand_counts": dict(Counter(x.get("Бренд Ozon", "") for x in assignments)),
            "document_type_counts": dict(Counter(x.get("Тип документа", "") for x in assignments)),
            "exact_article_basis_rows": sum("Точный артикул в официальном листинге/карточке:" in x.get("Основание сопоставления", "") for x in assignments),
        },
        "ozon_existing_exact_document_records": exact_records,
        "ozon_attribute_brand_counts": {"|".join(k): v for k, v in brand_counts.items()},
        "ozon_attribute_tnved_counts": {"|".join(k): v for k, v in tnved_counts.items()},
        "ozon_attribute_mismatch_count": len(attr_mismatches),
        "ozon_attribute_mismatches": attr_mismatches,
        "tnved_scope_exclusions": tnved_scope_exclusions,
        "wb_exact_card_counts": dict(wb_counts),
        "wb_exact_document_row_counts": dict(wb_doc_counts),
        "targets": scoped_targets,
    }
    result["ready_for_ozon_create_and_binding"] = (
        len(assignments) == 550 and len(targets) == 550 and len(scoped_targets) == 549
        and len(tnved_scope_exclusions) == 1 and not attr_mismatches
        and downloaded["matches_local_source"] and not exact_records
        and wb_counts == {"exact_card": 549} and wb_doc_counts.get("present", 0) == 0
    )
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: result[k] for k in (
        "created_at", "source_sha256", "official_manufacturer_download", "assignment_summary",
        "ozon_existing_exact_document_records", "ozon_attribute_brand_counts", "ozon_attribute_tnved_counts",
        "ozon_attribute_mismatch_count", "tnved_scope_exclusions", "wb_exact_card_counts", "wb_exact_document_row_counts",
        "ready_for_ozon_create_and_binding")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
