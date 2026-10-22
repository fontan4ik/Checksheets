"""Read-only source and live Ozon preflight for Arlight declaration 46569/26."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.46569/26"
FSA_RECORD_ID = 21106549
FSA_URL = f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_RECORD_ID}/product"
FSA_TNVED = {"8539519009"}
FSA_SAMPLE_PROTOCOL_DATE = "2026-01-12"
SOURCE_SHA256 = "f5129cee3e2e0db750042781ca096411d1186d6cbdfe6f6603a10219e5ec7038"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
WB_IDENTITY = BASE / "wb_live_refresh_20261012_1418.json"
OUT = BASE / "arlight_46569_candidate_preflight_20261012.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(data: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def read_assignments() -> tuple[dict[str, dict], list[dict], list[dict]]:
    if not ASSIGNMENTS.is_file():
        raise RuntimeError("Local assignment map is missing")
    all_matches: list[dict] = []
    exact_source: dict[str, dict] = {}
    excluded_source_rows: list[dict] = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256 фактический") != SOURCE_SHA256:
                continue
            if not row.get("Номер/название документа", "").strip() or "46569/26" not in row["Номер/название документа"]:
                continue
            all_matches.append(row)
            if row.get("Статус покрытия артикула") != "найдены сертификаты/декларации":
                excluded_source_rows.append({
                    "offer_id": str(row.get("Артикул продавца") or ""),
                    "coverage_status": row.get("Статус покрытия артикула"),
                    "document_type": row.get("Тип документа"),
                    "evidence": row.get("Основание сопоставления"),
                })
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in exact_source:
                raise RuntimeError(f"Duplicate or empty source-mapped offer: {offer}")
            if row.get("Бренд подтвержденный") != "Arlight":
                raise RuntimeError(f"Confirmed brand mismatch for {offer}")
            document_type = str(row.get("Тип документа") or "")
            if document_type != "Декларация соответствия" and not document_type.startswith(
                "Декларация ЕАЭС ТР 037/2016"
            ):
                raise RuntimeError(f"Document type mismatch for {offer}")
            if norm(row.get("Номер/название документа")) != norm(NUMBER):
                raise RuntimeError(f"Document number mismatch for {offer}")
            if row.get("SHA256 заявленный") != SOURCE_SHA256:
                raise RuntimeError(f"Declared source hash mismatch for {offer}")
            evidence = str(row.get("Основание сопоставления") or "")
            exact_source[offer] = {**row, "_source_evidence_exact_article": (
                evidence.startswith("Точный артикул в официальном листинге/карточке:")
                or evidence.startswith("Документ прикреплён к официальной карточке артикула;")
            )}
    if not exact_source:
        raise RuntimeError("No exact source assignments for 46569/26 were found")
    return exact_source, all_matches, excluded_source_rows


def read_certificates(client: Client) -> tuple[list[dict], list[int]]:
    previous = None
    passes: list[int] = []
    for _ in range(3):
        rows: list[dict] = []
        page = 1
        while page <= 100:
            result = client.call("ozon", "/v1/product/certificate/list", {
                "page": page, "page_size": 100,
            }).get("result", {})
            batch = result.get("certificates")
            if not isinstance(batch, list):
                raise RuntimeError("Ozon certificate list page is incomplete")
            rows.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        else:
            raise RuntimeError("Ozon certificate list exceeded page limit")
        ids = [str(x.get("certificate_id")) for x in rows]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Duplicate Ozon certificate ID during full list read")
        signature = sorted((str(x.get("certificate_id")), norm(x.get("certificate_number") or x.get("number")),
                            str(x.get("status_code") or ""), str(x.get("type_code") or "")) for x in rows)
        passes.append(len(rows))
        if previous is not None and signature == previous:
            return rows, passes
        previous = signature
    raise RuntimeError("Ozon certificate list did not stabilize")


def read_products(client: Client, offers: list[str]) -> dict[str, dict]:
    products: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in products:
                raise RuntimeError("Ozon product info returned unexpected/duplicate offer")
            products[offer] = row
    if set(products) != set(offers):
        raise RuntimeError(f"Ozon identity read incomplete: {len(products)}/{len(offers)}")
    return products


def read_attributes(client: Client, offers: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for start in range(0, len(offers), 50):
        batch = offers[start:start + 50]
        rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": 100,
        }).get("result") or []
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in result:
                raise RuntimeError("Ozon attributes returned unexpected/duplicate offer")
            result[offer] = row
    if set(result) != set(offers):
        raise RuntimeError(f"Ozon attributes read incomplete: {len(result)}/{len(offers)}")
    return result


def values_by_id(row: dict, attr_id: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "") for x in (attrs.get(attr_id) or {}).get("values") or []]


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Output already exists; inspect it instead of overwriting")
    assignments, matching_rows, excluded_source_rows = read_assignments()
    offers = sorted(assignments)
    if len(offers) != 857:
        raise RuntimeError(f"Expected 857 exact Arlight assignments, found {len(offers)}")

    local_paths = sorted({str(row.get("Локальный файл") or "") for row in matching_rows if row.get("Локальный файл")})
    if not local_paths:
        raise RuntimeError("No source PDF path is recorded")
    file_checks = []
    for raw in local_paths:
        path = ROOT / raw
        if not path.is_file():
            raise RuntimeError(f"Mapped source PDF is missing: {path}")
        actual = digest(path)
        if actual != SOURCE_SHA256:
            raise RuntimeError(f"Mapped source PDF hash mismatch: {path}")
        file_checks.append({"path": str(path), "bytes": path.stat().st_size, "sha256": actual})

    wb = json.loads(WB_IDENTITY.read_text())
    if not wb.get("complete") or wb.get("unique_cards") != 19962 or wb.get("duplicate_nmids") != 0:
        raise RuntimeError("Complete WB identity snapshot is missing")
    wb_by_offer: dict[str, str] = {}
    for card in wb.get("cards") or []:
        offer = str(card.get("vendorCode") or "")
        if offer in wb_by_offer:
            raise RuntimeError(f"Duplicate WB vendorCode in identity snapshot: {offer}")
        wb_by_offer[offer] = str(card.get("nmID") or "")

    client = Client()
    certificates, cert_passes = read_certificates(client)
    exact = [x for x in certificates if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    suffix = [x for x in certificates if norm(x.get("certificate_number") or x.get("number")).endswith("4656926")]
    if exact or suffix:
        raise RuntimeError("A 46569/26 or same-suffix certificate already exists on Ozon; reconcile before any write")
    lookup = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        json={"certificate_number": NUMBER}, headers=client.ozon_headers, timeout=(15, 60),
    )
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    exact_lookup = {"http_status": lookup.status_code, "error_code": lookup_body.get("code")}
    if lookup.status_code != 404 or lookup_body.get("code") != 5:
        raise RuntimeError("Ozon exact-number lookup did not confirm absence")

    products = read_products(client, offers)
    attributes = read_attributes(client, offers)
    targets = []
    counts = {"tnved": Counter(), "brand": Counter(), "active": Counter()}
    issues = []
    for offer in offers:
        product = products[offer]
        attr = attributes[offer]
        brand_values = values_by_id(attr, "85")
        raw_codes = values_by_id(attr, "22232")
        codes = sorted({x.split(" - ", 1)[0].strip() for x in raw_codes if x.strip()})
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        active = product.get("is_archived") is False
        wb_nm_id = wb_by_offer.get(offer)
        problems = []
        if not product_id or not sku or str(product.get("offer_id") or "") != offer:
            problems.append("live_product_identity_missing_or_mismatched")
        if not active:
            problems.append("offer_not_active")
        if brand_values != ["Arlight"]:
            problems.append("brand_not_exactly_Arlight")
        if len(codes) != 1:
            problems.append("TN_VED_missing_or_ambiguous")
        if codes and not set(codes).issubset(FSA_TNVED):
            problems.append("TN_VED_outside_FSA_scope")
        if not wb_nm_id:
            problems.append("exact_WB_card_missing")
        counts["brand"].update(brand_values or ["<missing>"])
        counts["tnved"].update(codes or ["<missing>"])
        counts["active"].update([str(active)])
        target = {
            "offer_id": offer, "product_id": product_id, "sku": sku,
            "wb_nmID_from_full_catalog": wb_nm_id or None,
            "product_name": str(product.get("name") or ""),
            "brand_values": brand_values, "tnved_values": raw_codes, "tnved_codes": codes,
            "tnved_in_fsa_scope": len(codes) == 1 and set(codes).issubset(FSA_TNVED),
            "is_archived": product.get("is_archived"),
            "source_article_evidence": assignments[offer].get("Основание сопоставления"),
            "source_product_url": assignments[offer].get("URL карточки/основания"),
            "preflight_issues": problems,
        }
        targets.append(target)
        if problems:
            issues.append({"offer_id": offer, "problems": problems})

    eligible = [x for x in targets if not x["preflight_issues"]]
    payload = {
        "checked_at_utc": now(), "read_only": True, "marketplace_mutation_allowed": False,
        "mutation_blocker": "FSA scope explicitly limits the declaration to products manufactured from sampled products; the official protocol date is 2026-01-12, but current lot manufacturing dates are unknown.",
        "number": NUMBER, "document_type": "declaration", "accordance_type": "EAEU",
        "issue_date": "2026-01-30", "expiry_date": "2031-01-29",
        "fsa_record_id": FSA_RECORD_ID, "fsa_official_url": FSA_URL,
        "fsa_status_from_official_UI": "Действует",
        "fsa_applicant": "ООО \"ТРАНЗИСТОР.РУ\"",
        "fsa_manufacturer": "Heilongjiang Arlight Trade Company Limited",
        "fsa_product_scope_from_official_UI": "Arlight LED strips (RT, RTW, COB, FC, UL, ULTRA, TWIST, MICROLED, CSP, SPI, DMX, RZ, LENS, FLT, DOT, SOB, S2, MINI, IC, RS, VELA, LUNA, XRT, SHOP, FITOLUX, CC, NT, DOB, HP, HLT, MOSQUIT, HS, XP, SRT, ST, WCOB, MCOB, WLT, WST, TNT, EXT, FS, FST, FSS, ART, UGR, FT, MOONLIGHT, QUAZAR, GALAXY, ASTREY, ORBITAL, LUNAR, NEBULA, PHOBOS); LX LED sheets; SL/ARL LED bars; RT LED mesh; ARL flexible neon",
        "fsa_tnved_codes": sorted(FSA_TNVED),
        "fsa_test_protocol": {"number": "00012; 00015", "date": FSA_SAMPLE_PROTOCOL_DATE,
                              "laboratory": "Heilongjiang Arlight Trade Company Limited (manufacturer laboratory)"},
        "sample_date_scope_clause": True,
        "local_source_sha256": SOURCE_SHA256, "local_source_files": file_checks,
        "source_assignment_count": len(assignments),
        "source_assignment_excluded_count": len(excluded_source_rows),
        "source_assignment_exclusions": excluded_source_rows,
        "source_assignment_evidence_unresolved": sum(not x.get("_source_evidence_exact_article") for x in assignments.values()),
        "ozon_certificate_list_count": len(certificates), "ozon_certificate_list_pass_counts": cert_passes,
        "ozon_exact_number_lookup": exact_lookup,
        "ozon_products_read": len(products), "ozon_attributes_read": len(attributes),
        "ozon_brand_counts": dict(counts["brand"]), "ozon_tnved_counts": dict(counts["tnved"]),
        "ozon_active_counts": dict(counts["active"]),
        "wb_identity_snapshot_checked_at": wb.get("checked_at"),
        "wb_catalog_cards": wb.get("unique_cards"), "wb_target_cards_found": sum(bool(x.get("wb_nmID_from_full_catalog")) for x in targets),
        "wb_target_cards_missing": sum(not x.get("wb_nmID_from_full_catalog") for x in targets),
        "target_count": len(targets), "preflight_clean_count": len(eligible),
        "tnved_in_scope_count": sum(x["tnved_in_fsa_scope"] for x in targets),
        "issue_count": len(issues), "issues": issues, "targets": targets,
        "ready_for_full_WB_card_read": bool(targets),
    }
    save(payload)
    print(json.dumps({k: payload[k] for k in (
        "checked_at_utc", "number", "fsa_status_from_official_UI", "source_assignment_count",
        "ozon_products_read", "ozon_attributes_read", "ozon_brand_counts", "ozon_tnved_counts",
        "wb_target_cards_found", "wb_target_cards_missing", "target_count", "preflight_clean_count",
        "tnved_in_scope_count", "issue_count", "ozon_exact_number_lookup", "marketplace_mutation_allowed",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
