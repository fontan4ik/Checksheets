"""Read-only current-Ozon preflight for Arlight 52132/25."""
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

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
ISSUE_DATE = "2025-10-22"
EXPIRY_DATE = "2030-10-20"
FSA_RECORD_ID = 20749531
FSA_URL = f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_RECORD_ID}/product"
FSA_TNVED = {
    "9405110039", "9405110013", "9405420012", "9405420032",
    "9405110033", "9405420039",
}
FSA_SERIES = {
    "MS", "MD", "IM", "LTD", "CL", "DL", "LT", "LGD", "SP", "LTM",
    "ALT", "KT", "MAG", "CLIP", "ART", "SNAP", "FLEX", "BAR", "PIR",
    "UNIVERSE", "SPACE", "DIY", "AIR", "AR", "BR",
}
SERIES_RE = re.compile(
    r"(?<![A-Z0-9])(" + "|".join(sorted(FSA_SERIES, key=len, reverse=True)) + r")(?=-|[A-Z0-9])",
    re.I,
)
SOURCE_SHA256 = "1af35bb24d9f014ea59b14ffbd88f42b705a4f5fb285e57a683d24542c26c225"
VERIFIED_035612_TITLE = (
    "Светильник MS-BREEZE-BUILT-R104-12W Day4000 (BK, 85 deg, 230V) "
    "(Arlight, IP20 Металл, 3 года)"
)
SOURCE_FILES = [
    ROOT / "output_to_user/certificates/additional_search/brand_research/arlight/docs/supplier_035612_e5dl8we8jfanimk1dzyg6kzrd592pvxk.pdf",
    ROOT / "output_to_user/certificates/group_1/documents/arlight/94D46BAFE361664EA7621A1A4A70FD33.pdf",
]
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
WB_IDENTITY = BASE / "wb_live_refresh_20261012_1418.json"
OUT = BASE / "arlight_52132_ozon_preflight_20261012.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(payload: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def read_assignments() -> dict[str, dict]:
    if not ASSIGNMENTS.is_file():
        raise RuntimeError("Source assignment table is missing")
    result: dict[str, dict] = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256 фактический") != SOURCE_SHA256:
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in result:
                raise RuntimeError("Duplicate or empty offer in exact-source assignments")
            if row.get("Бренд подтвержденный") != "Arlight":
                raise RuntimeError(f"Confirmed brand differs for {offer}")
            evidence = str(row.get("Основание сопоставления") or "")
            verified_035612_source = (
                offer == "035612-1"
                and row.get("Название товара Ozon") == VERIFIED_035612_TITLE
                and row.get("Тип документа") == "Декларация ЕАЭС ТР 037/2016"
                and row.get("Статус покрытия артикула") == "есть официальный документ"
                and row.get("Применимость") == "Подтверждено источником"
                and evidence.startswith("Точная карточка представителя 035612 и модель MS-BREEZE.")
                and str(row.get("URL карточки/основания") or "").startswith(
                    "https://arlight.moscow/catalog/"
                )
                and str(row.get("URL карточки/основания") or "").endswith("-035612.html")
            )
            if row.get("Тип документа") != "Декларация соответствия" and not verified_035612_source:
                raise RuntimeError(f"Document type differs for {offer}")
            if (row.get("Статус покрытия артикула") != "найдены сертификаты/декларации"
                    and not verified_035612_source):
                raise RuntimeError(f"Source applicability is not proven for {offer}")
            if norm(row.get("Номер/название документа")) != norm(NUMBER):
                raise RuntimeError(f"Document number differs for {offer}")
            exact_listing = evidence.startswith(
                "Точный артикул в официальном листинге/карточке:"
            )
            # The official Arlight page maps seller aliases such as 015393-1 to the
            # displayed manufacturer article 015393. Accept only an explicit mapping
            # statement plus the matching official product URL. The one remaining
            # representative-page-only mapping is carried forward as an exclusion.
            match = re.search(
                rf"связан с артикулом {re.escape(offer)} \(вариант ([0-9]+(?:\(1\))?)\)",
                evidence,
            )
            variant = match.group(1) if match else ""
            expected_article = variant.split("(", 1)[0]
            verified_variant = (
                evidence.startswith("Документ прикреплён к официальной карточке артикула;")
                and row.get("URL карточки/основания")
                == f"https://arlight.ru/catalog/product/{expected_article}/"
                and bool(variant)
            )
            row["_source_evidence_unresolved"] = not (
                exact_listing or verified_variant or verified_035612_source
            )
            result[offer] = row
    if len(result) != 1841:
        raise RuntimeError(f"Expected 1,841 exact source-map offers, found {len(result)}")
    return result


def read_ozon_certificates(client: Client) -> tuple[list[dict], list[list[int]]]:
    previous_signature = None
    observed_page_counts: list[list[int]] = []
    for _ in range(3):
        rows: list[dict] = []
        page_counts: list[int] = []
        page = 1
        while page <= 100:
            result = client.call("ozon", "/v1/product/certificate/list", {
                "page": page, "page_size": 100,
            }).get("result", {})
            batch = result.get("certificates")
            count = result.get("page_count")
            if not isinstance(batch, list) or not isinstance(count, int):
                raise RuntimeError("Ozon certificate list pagination is incomplete")
            page_counts.append(count)
            rows.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        else:
            raise RuntimeError("Ozon certificate list exceeded the 100-page safety limit")

        ids = [str(x.get("certificate_id")) for x in rows]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Ozon certificate list contains duplicate IDs in one read")
        signature = sorted(
            (str(x.get("certificate_id")), norm(x.get("certificate_number") or x.get("number")),
             str(x.get("type_code") or ""), str(x.get("status_code") or ""))
            for x in rows
        )
        observed_page_counts.append(page_counts)
        if previous_signature is not None and signature == previous_signature:
            return rows, observed_page_counts
        previous_signature = signature
    raise RuntimeError("Ozon certificate list did not stabilize across two complete reads")


def read_products(client: Client, offers: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in result:
                raise RuntimeError("Ozon product read returned an unexpected or duplicate offer")
            result[offer] = row
    if set(result) != set(offers):
        raise RuntimeError(f"Ozon product read returned {len(result)}/{len(offers)} offers")
    return result


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
                raise RuntimeError("Ozon attribute read returned an unexpected or duplicate offer")
            result[offer] = row
    if set(result) != set(offers):
        raise RuntimeError(f"Ozon attribute read returned {len(result)}/{len(offers)} offers")
    return result


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Preflight output already exists; inspect it instead of overwriting")
    file_checks = []
    for path in SOURCE_FILES:
        if not path.is_file():
            raise RuntimeError(f"A local source copy is missing: {path}")
        file_checks.append({"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)})
        if file_checks[-1]["sha256"] != SOURCE_SHA256:
            raise RuntimeError(f"A source copy hash changed: {path}")

    assignments = read_assignments()
    offers = sorted(assignments)
    wb = json.loads(WB_IDENTITY.read_text())
    if not wb.get("complete") or wb.get("duplicate_nmids") != 0 or wb.get("unique_cards") != 19962:
        raise RuntimeError("Same-day full WB identity snapshot is incomplete")
    wb_by_offer: dict[str, str] = {}
    for card in wb.get("cards") or []:
        offer = str(card.get("vendorCode") or "")
        if offer in wb_by_offer:
            raise RuntimeError(f"Duplicate WB vendorCode in snapshot: {offer}")
        wb_by_offer[offer] = str(card.get("nmID") or "")

    client = Client()
    certificate_rows, certificate_page_counts = read_ozon_certificates(client)
    matching = [x for x in certificate_rows if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if len(matching) > 1:
        raise RuntimeError("Multiple normalized 52132/25 records already exist on Ozon")
    info_lookup = None
    if matching:
        info = client.call("ozon", "/v1/product/certificate/info", {
            "certificate_number": NUMBER,
        }).get("result")
        raise RuntimeError(f"Ozon already has a matching 52132/25 record: {info}")
    response = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        json={"certificate_number": NUMBER}, headers=client.ozon_headers, timeout=(15, 60),
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    info_lookup = {"http_status": response.status_code, "error_code": body.get("code")}
    if response.status_code != 404 or body.get("code") != 5:
        raise RuntimeError("Ozon exact-number lookup did not confirm that 52132/25 is absent")

    products = read_products(client, offers)
    attributes = read_attributes(client, offers)
    targets = []
    issues = []
    tnved_exclusions = []
    counts = {"brands": Counter(), "tnved": Counter(), "families": Counter(), "visibility": Counter()}
    for offer in offers:
        assignment = assignments[offer]
        product = products[offer]
        attrs = {str(x.get("id")): x for x in attributes[offer].get("attributes") or []}

        def values(attr_id: str) -> list[str]:
            return [str(x.get("value") or "") for x in (attrs.get(attr_id) or {}).get("values") or []]

        brand = values("85")
        raw_tnved = values("22232")
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in raw_tnved if x.strip()})
        name = str(product.get("name") or "")
        families = sorted({x.upper() for x in SERIES_RE.findall(name)})
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        is_archived = product.get("is_archived")
        counts["brands"].update(brand or ["<missing>"])
        counts["tnved"].update(tnved or ["<missing>"])
        counts["families"].update(families or ["<unmatched>"])
        counts["visibility"].update([str(product.get("visibility"))])

        problems = []
        if assignment.get("_source_evidence_unresolved"):
            problems.append("manufacturer_article_mapping_requires_manual_review")
        if not product_id or not sku or product.get("offer_id") != offer:
            problems.append("live_product_identity_missing_or_mismatched")
        if is_archived is not False:
            problems.append("not_currently_active")
        if brand != ["Arlight"]:
            problems.append("brand_not_exactly_Arlight")
        if not families or not set(families).issubset(FSA_SERIES):
            problems.append("model_family_not_proven_in_FSA_scope")
        if len(tnved) != 1:
            problems.append("TN_VED_missing_or_ambiguous")
        outside = sorted(set(tnved) - FSA_TNVED)
        wb_nm_id = wb_by_offer.get(offer)
        target = {
            "offer_id": offer, "product_id": product_id, "sku": sku,
            "wb_nmID": wb_nm_id or None, "product_name": name,
            "brand": brand, "tnved_values": raw_tnved, "tnved_codes": tnved,
            "tnved_in_scope": len(tnved) == 1 and not outside,
            "model_families": families, "manufacturer_article_proof": assignment.get("Основание сопоставления"),
            "manufacturer_proof_url": assignment.get("URL карточки/основания"),
            "is_archived": is_archived, "preflight_issues": problems,
        }
        targets.append(target)
        if problems:
            issues.append({"offer_id": offer, "problems": problems, "target": target})
        if outside:
            tnved_exclusions.append({"offer_id": offer, "product_id": product_id, "sku": sku,
                                     "wb_nmID": wb_nm_id or None, "tnved_values": raw_tnved,
                                     "outside_codes": outside,
                                     "reason": "Ozon TN VED is not listed on the official FSA declaration"})

    eligible = [x for x in targets if not x["preflight_issues"] and x["tnved_in_scope"]]
    payload = {
        "checked_at_utc": now(), "read_only": True,
        "number": NUMBER, "document_type": "declaration", "accordance_type": "EAEU",
        "issue_date": ISSUE_DATE, "expiry_date": EXPIRY_DATE,
        "fsa_record_id": FSA_RECORD_ID, "fsa_official_url": FSA_URL,
        "fsa_status_from_official_UI": "Действует",
        "fsa_product_scope_from_official_UI": "Стационарные светодиодные светильники Arlight; named series in FSA record 20749531",
        "fsa_tnved_codes": sorted(FSA_TNVED), "fsa_series": sorted(FSA_SERIES),
        "local_source_sha256": SOURCE_SHA256, "local_source_files": file_checks,
        "source_assignment_count": len(assignments),
        "source_evidence_unresolved_offers": sorted(
            offer for offer, row in assignments.items() if row.get("_source_evidence_unresolved")
        ),
        "source_assignment_document_urls": sorted({x.get("URL карточки/основания") or "" for x in assignments.values()}),
        "wb_identity_snapshot_checked_at": wb.get("checked_at"),
        "wb_identity_snapshot_catalog_cards": wb.get("unique_cards"),
        "ozon_certificate_list_records": len(certificate_rows),
        "ozon_certificate_list_page_counts_per_pass": certificate_page_counts,
        "ozon_exact_number_lookup": info_lookup,
        "ozon_products_read": len(products), "ozon_attributes_read": len(attributes),
        "ozon_brand_counts": dict(counts["brands"]),
        "ozon_tnved_counts": dict(counts["tnved"]),
        "ozon_model_family_counts": dict(counts["families"]),
        "ozon_visibility_counts": dict(counts["visibility"]),
        "wb_target_cards_found": sum(bool(x.get("wb_nmID")) for x in targets),
        "wb_target_cards_missing": sum(not x.get("wb_nmID") for x in targets),
        "target_count": len(targets), "eligible_target_count": len(eligible),
        "tnved_scope_exclusion_count": len(tnved_exclusions),
        "tnved_scope_exclusions": tnved_exclusions,
        "issue_count": len(issues), "issues": issues,
        "targets": targets,
        "ready_for_fresh_WB_fullcard_read_and_separate_Ozon_upload_bind": bool(eligible) and not issues,
    }
    save(payload)
    print(json.dumps({k: payload[k] for k in (
        "checked_at_utc", "number", "fsa_status_from_official_UI", "source_assignment_count",
        "ozon_products_read", "ozon_attributes_read", "ozon_brand_counts", "ozon_tnved_counts",
        "ozon_model_family_counts", "wb_target_cards_found", "wb_target_cards_missing",
        "target_count", "eligible_target_count", "tnved_scope_exclusion_count", "issue_count",
        "ozon_exact_number_lookup", "ready_for_fresh_WB_fullcard_read_and_separate_Ozon_upload_bind",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
