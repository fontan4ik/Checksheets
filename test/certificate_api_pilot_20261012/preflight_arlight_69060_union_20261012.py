"""Read-only canonical preflight for the Arlight 69060/25 declaration."""
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
GROUPS = {
    "baeb142abdd28d42ae6cbbe4993134f3726364e94ca66c3b09d913d52b81db04": {
        "url": "https://arlight.ru/upload/certificates/F6522803E046324C87BC430F67671163.pdf",
        "local_expected_files": 1,
    },
    "283c1f57322d9244c0bcc0420500f27d6ede0c41603da00db51865326c550a44": {
        "url": "https://arlight.ru/upload/certificates/7031843907082840B66DC829354CBC46.pdf",
        "local_expected_files": 5,
    },
}
DOC_NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
REGISTRY_URL = "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product"
OUT = BASE / "arlight_69060_union_preflight_20261012.json"
HASH_CLEAN = "baeb142abdd28d42ae6cbbe4993134f3726364e94ca66c3b09d913d52b81db04"
HASH_OCR_VARIANT = "283c1f57322d9244c0bcc0420500f27d6ede0c41603da00db51865326c550a44"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def official_article_evidence(row: dict[str, str]) -> bool:
    basis = row.get("Основание сопоставления", "")
    if "Точный артикул в официальном листинге/карточке:" in basis:
        return True
    # Some Arlight SKUs are documented as variants on the manufacturer's exact
    # product card. The official card URL slug must match the seller article stem.
    match = re.fullmatch(r"https://arlight\.ru/catalog/product/(\d+)/?", row.get("URL карточки/основания", ""))
    offer_stem = str(row.get("Артикул продавца") or "").split("-", 1)[0]
    offer_stem = re.sub(r"\(.*?\)", "", offer_stem)
    return bool(match and match.group(1) == offer_stem and
                "Документ прикреплён к официальной карточке артикула;" in basis)


def download_official(url: str, expected_sha: str) -> dict:
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
    response = session.get(url, timeout=(15, 60), headers={"Accept": "application/pdf"})
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if not response.content.startswith(b"%PDF-"):
        raise RuntimeError(f"Official source did not return PDF bytes: {url}")
    return {"url": url, "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "last_modified": response.headers.get("Last-Modified"),
            "size_bytes": len(response.content), "sha256": digest,
            "matches_local_source": digest == expected_sha}


def main() -> None:
    local = read_json(LOCAL_MAP)
    products = read_json(PRODUCTS)
    ozon = read_json(OZON)
    wb = read_json(WB)
    if not all(x.get("complete") for x in (products, ozon, wb)):
        raise RuntimeError("Current complete Ozon and WB snapshots are required")

    groups_by_hash = {x.get("sha256"): x for x in local.get("groups", [])}
    selected = {}
    file_proof = []
    for digest, config in GROUPS.items():
        group = groups_by_hash.get(digest)
        if not group or len(group.get("files", [])) != config["local_expected_files"]:
            raise RuntimeError(f"Missing or changed source-map group {digest}")
        group_files = []
        for file in group["files"]:
            path = Path(file["path"])
            if not path.is_file() or path.is_symlink() or sha256(path) != digest:
                raise RuntimeError(f"Local source is missing or changed: {path}")
            group_files.append({"path": str(path), "size_bytes": path.stat().st_size,
                                "sha256": digest})
        file_proof.extend(group_files)
        if norm(DOC_NUMBER) not in {norm(x) for x in group.get("document_numbers", [])}:
            raise RuntimeError("OCR/source map number does not resolve to the manually verified FSA number")
        selected[digest] = group

    # Both distinct PDFs were visually checked and their QR codes resolve to this exact
    # active FSA declaration. The mixed OCR spelling on the second hash is resolved by
    # that authoritative registry record; it is not a second declaration.
    rows_by_offer = {}
    assignment_rows_by_hash = Counter()
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            digest = row.get("SHA256 фактический")
            if digest not in GROUPS:
                continue
            assignment_rows_by_hash[digest] += 1
            if (row.get("Бренд подтвержденный") != "Arlight"
                    or row.get("Бренд Ozon") != "Arlight"
                    or row.get("Тип документа") != "Декларация соответствия"
                    or norm(row.get("Номер/название документа")) != norm(DOC_NUMBER)
                    or row.get("SHA256 заявленный") != digest
                    or row.get("URL документа") != GROUPS[digest]["url"]
                    or not official_article_evidence(row)):
                raise RuntimeError(f"Manufacturer article evidence changed: {row.get('Артикул продавца')}")
            offer = str(row.get("Артикул продавца") or "")
            if not offer:
                raise RuntimeError("Source assignment has empty offer ID")
            previous = rows_by_offer.get(offer)
            if previous and (previous.get("Бренд подтвержденный") != row.get("Бренд подтвержденный")
                             or previous.get("Основание сопоставления") != row.get("Основание сопоставления")):
                raise RuntimeError(f"Duplicate source groups disagree on article identity: {offer}")
            rows_by_offer.setdefault(offer, row)
    if assignment_rows_by_hash != {HASH_CLEAN: 550, HASH_OCR_VARIANT: 554}:
        raise RuntimeError(f"Unexpected assignment row counts: {assignment_rows_by_hash}")

    map_bindings_by_hash = {}
    for digest, group in selected.items():
        mapping = {}
        for binding in group.get("bindings", []):
            offer = str(binding.get("offer_id") or "")
            if not offer or offer in mapping:
                raise RuntimeError(f"Duplicate/empty source-map offer for {digest}: {offer}")
            skus = [str(x) for x in binding.get("ozon_skus", [])]
            pids = [str(x) for x in binding.get("ozon_product_ids", [])]
            if len(skus) != 1 or len(pids) != 1:
                raise RuntimeError(f"Non-one-to-one offer identity in source map: {offer}")
            mapping[offer] = {"sku": skus[0], "product_id": pids[0]}
        map_bindings_by_hash[digest] = mapping
        if len(mapping) != assignment_rows_by_hash[digest]:
            raise RuntimeError(f"Source map and assignment row count differ for {digest}")
        for offer, identity in mapping.items():
            if offer not in rows_by_offer:
                raise RuntimeError(f"No exact manufacturer article proof for mapped offer {offer}")

    products_by_offer = {str(x.get("offer_id")): x for x in products.get("products", [])}
    wb_by_offer = defaultdict(list)
    for card in wb.get("cards", []):
        wb_by_offer[str(card.get("vendorCode") or "")].append(card)
    targets = []
    identities = {}
    for offer in sorted(rows_by_offer):
        current = products_by_offer.get(offer)
        if not current or current.get("is_archived") is not False:
            raise RuntimeError(f"Current active Ozon offer missing: {offer}")
        pid, sku = str(current.get("product_id")), str(current.get("sku"))
        matching_sources = [m[offer] for m in map_bindings_by_hash.values() if offer in m]
        if not matching_sources or any(x != {"product_id": pid, "sku": sku} for x in matching_sources):
            raise RuntimeError(f"Source crosswalk does not match current Ozon product ID/SKU: {offer}")
        identities[offer] = {"product_id": pid, "sku": sku}
        cards = wb_by_offer.get(offer, [])
        if len(cards) != 1:
            raise RuntimeError(f"Expected one exact WB card for {offer}; found {len(cards)}")
        docs = (cards[0].get("documents") or {}).get("items") or []
        existing = [x for x in docs if norm(x.get("number")) == norm(DOC_NUMBER)]
        targets.append({"offer_id": offer, "product_id": pid, "sku": sku,
                        "name": str(current.get("name") or ""),
                        "official_article_basis": rows_by_offer[offer].get("Основание сопоставления"),
                        "wb_nmID": cards[0].get("nmID"),
                        "wb_exact_document_rows": existing})

    # Check completeness and consistency for every shared offer across both source groups.
    for digest, mapping in map_bindings_by_hash.items():
        for offer, identity in mapping.items():
            if identities.get(offer) != identity:
                raise RuntimeError(f"Source group {digest} has stale ID/SKU for {offer}")

    exact_records = [x for x in ozon.get("certificates", [])
                     if norm(x.get("certificate_number")) == norm(DOC_NUMBER)]
    if exact_records:
        raise RuntimeError("Ozon record already exists; reconcile instead of creating a duplicate")

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
                raise RuntimeError("Ozon returned unknown or duplicate offer in attributes")
            if str(item.get("id") or item.get("product_id") or "") != identities[offer]["product_id"]:
                raise RuntimeError(f"Ozon product ID changed during attributes read: {offer}")
            by_id = {str(a.get("id")): a for a in item.get("attributes") or []}
            def values(attribute_id: str) -> list[str]:
                attr = by_id.get(attribute_id) or {}
                return [str(v.get("value")) for v in attr.get("values") or []
                        if v.get("value") not in (None, "")]
            attributes[offer] = {"brand": values("85"), "tnved": values("22232"),
                                 "product_name": str(item.get("name") or products_by_offer[offer].get("name") or "")}
        if {str(x.get("offer_id") or "") for x in result} != set(batch):
            raise RuntimeError("Ozon attributes response incomplete")
    if set(attributes) != set(offers):
        raise RuntimeError("Ozon attributes missing target offers")

    attr_mismatches = [{"offer_id": offer, **attr} for offer, attr in attributes.items()
                       if attr["brand"] != ["Arlight"] or "8504408300" not in attr["tnved"]]
    for target in targets:
        target["ozon_attributes"] = attributes[target["offer_id"]]
    source_checks = [download_official(GROUPS[digest]["url"], digest) for digest in GROUPS]
    if any(not x["matches_local_source"] for x in source_checks):
        raise RuntimeError("Live official manufacturer PDF differs from its local copy")

    brands = Counter(tuple(x["brand"]) for x in attributes.values())
    tnveds = Counter(tuple(x["tnved"]) for x in attributes.values())
    wb_docs = Counter("present" if x["wb_exact_document_rows"] else "missing" for x in targets)
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(), "read_only": True,
        "canonical_document_number": DOC_NUMBER, "document_type": "declaration",
        "fsa_registry_url": REGISTRY_URL, "fsa_registry_status_seen_in_ui": "Действует",
        "fsa_registry_issue_date": "2025-03-10", "fsa_registry_expiry_date": "2030-03-09",
        "fsa_registry_tnved_scope": ["8504408300"],
        "fsa_registry_product_scope": ["ARPV", "ARDV", "HTS", "ARV", "ARS", "JTS", "HTPS", "ARJ", "ARPJ", "KNX", "DALI", "SMART"],
        "qr_resolution": "Both visually checked PDF hashes resolve to FSA record 19978046; OCR variant is therefore the same declaration.",
        "local_map_sha256": sha256(LOCAL_MAP), "source_files": file_proof,
        "official_manufacturer_downloads": source_checks,
        "source_groups": {digest: {"assignments": assignment_rows_by_hash[digest],
                                   "bindings": len(map_bindings_by_hash[digest]),
                                   "ocr_document_numbers": selected[digest].get("document_numbers"),
                                   "issues": selected[digest].get("issues"),
                                   "source_url": GROUPS[digest]["url"]} for digest in GROUPS},
        "target_count": len(targets), "ozon_products_checked_at": products.get("checked_at"),
        "ozon_certificates_checked_at": ozon.get("checked_at"), "wb_catalog_checked_at": wb.get("checked_at"),
        "ozon_attribute_brand_counts": {"|".join(k): v for k, v in brands.items()},
        "ozon_attribute_tnved_counts": {"|".join(k): v for k, v in tnveds.items()},
        "ozon_attribute_mismatch_count": len(attr_mismatches), "ozon_attribute_mismatches": attr_mismatches,
        "wb_exact_card_count": len(targets), "wb_existing_exact_document_row_count": sum(bool(x["wb_exact_document_rows"]) for x in targets),
        "ozon_existing_exact_document_records": exact_records, "targets": targets,
    }
    result["ready_for_ozon_create_and_binding"] = (
        len(targets) == 554 and not attr_mismatches and all(x["matches_local_source"] for x in source_checks)
        and not exact_records and len(wb_by_offer) >= len(targets)
        and not any(x["wb_exact_document_rows"] for x in targets)
    )
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: result[k] for k in (
        "created_at", "canonical_document_number", "target_count", "source_groups",
        "official_manufacturer_downloads", "ozon_attribute_brand_counts", "ozon_attribute_tnved_counts",
        "ozon_attribute_mismatch_count", "wb_exact_card_count", "wb_existing_exact_document_row_count",
        "ozon_existing_exact_document_records", "ready_for_ozon_create_and_binding")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
