#!/usr/bin/env python3
"""Live read-only preflight for STEKKER BGS declaration 24659/26."""
from __future__ import annotations

import base64
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.24659/26"
ISSUE = "2026-01-22"
EXPIRY = "2031-01-21"
SOURCE_PDF = ROOT / "output_to_user/certificates/additional_search/brand_research/stekker/residual_2026_10_02/docs/declaration_24659_26_fsa_official_extract.pdf"
SOURCE_SIGNED_JPG = ROOT / "output_to_user/certificates/additional_search/brand_research/stekker/residual_2026_10_02/docs/declaration_24659_26_feron_official.jpg"
EXPECTED_OFFERS = {"50282-1", "50283-1", "50284-1"}


def attr_values(attributes, ident):
    by_id = {str(item.get("id")): item for item in (attributes or [])}
    return [str(v.get("value") or "").strip() for v in (by_id.get(str(ident)) or {}).get("values") or [] if str(v.get("value") or "").strip()]


def ozon_records(client):
    result = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        listing = body.get("result") or {}
        values = listing.get("certificates")
        if not isinstance(values, list):
            raise RuntimeError("invalid_ozon_certificate_list")
        result.extend(values)
        if not values or page >= int(listing.get("page_count") or 0):
            return result
    raise RuntimeError("ozon_certificate_page_limit")


def main():
    expected_sha = "4ce605742413da9171d1b758ff6a4552ff12ea852fb207d64f0b569b46700cd2"
    actual_sha = hashlib.sha256(SOURCE_PDF.read_bytes()).hexdigest()
    signed_sha = hashlib.sha256(SOURCE_SIGNED_JPG.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError("official_fsa_extract_sha_mismatch")
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(newline="", encoding="utf-8-sig") as stream:
        assignments = [r for r in csv.DictReader(stream) if r.get("Номер/название документа") == NUMBER]
    offers = {r.get("Артикул продавца") for r in assignments}
    if offers != EXPECTED_OFFERS or len(assignments) != 3:
        raise RuntimeError(f"assignment_scope_mismatch:{sorted(str(x) for x in offers)}")
    for row in assignments:
        if row.get("Тип документа") != "Декларация соответствия" or row.get("Применимость") != "Подтверждено источником":
            raise RuntimeError("assignment_applicability_mismatch:" + str(row.get("Артикул продавца")))

    client = Client()
    products, attrs = {}, {}
    offer_list = sorted(EXPECTED_OFFERS)
    for start in range(0, len(offer_list), 100):
        batch = offer_list[start:start + 100]
        for item in client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []:
            products.setdefault(str(item.get("offer_id") or ""), []).append(item)
        for item in client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or []:
            attrs.setdefault(str(item.get("offer_id") or ""), []).append(item)

    records = ozon_records(client)
    number_key = norm_number(NUMBER)
    exact_ozon_records = [r for r in records if norm_number(r.get("certificate_number")) == number_key]
    targets = []
    for offer in offer_list:
        pp, aa = products.get(offer, []), attrs.get(offer, [])
        blockers = []
        product = pp[0] if len(pp) == 1 else {}
        attribute = aa[0] if len(aa) == 1 else {}
        if len(pp) != 1 or len(aa) != 1:
            blockers.append("ozon_product_or_attributes_missing_or_ambiguous")
        brand = attr_values(attribute.get("attributes"), 85)
        tnved = attr_values(attribute.get("attributes"), 22232)
        if product.get("is_archived") is not False:
            blockers.append("ozon_product_not_active")
        if [x.casefold() for x in brand] != ["stekker"]:
            blockers.append("ozon_brand_mismatch:" + ",".join(brand))
        expected_model = offer[:-2]
        product_name = str(product.get("name") or "")
        if expected_model.casefold() not in product_name.casefold() and "BGS" not in product_name.upper():
            blockers.append("ozon_model_not_visible")
        normalized_tnved = [x.split(" - ", 1)[0].strip() for x in tnved]
        if normalized_tnved and "4202929800" not in normalized_tnved:
            blockers.append("ozon_tnved_out_of_scope:" + ",".join(normalized_tnved))
        targets.append({
            "offer_id": offer,
            "ozon_product_id": str(product.get("product_id") or product.get("id") or ""),
            "ozon_sku": str(product.get("sku") or ""),
            "ozon_name": product_name,
            "ozon_archived": product.get("is_archived"),
            "ozon_brand": brand,
            "ozon_tnved": normalized_tnved,
            "ozon_blockers": blockers,
            "wb_nmID": None,
            "wb_brand": None,
            "wb_title": None,
            "wb_tnved": None,
            "wb_exact_document": None,
            "wb_blockers": [],
        })

    for target in targets:
        cards = client.wb_cards(target["offer_id"])
        if len(cards) != 1:
            target["wb_blockers"].append("wb_card_missing_or_ambiguous")
            continue
        card = cards[0]
        target["wb_nmID"] = str(card.get("nmID") or "")
        target["wb_brand"] = str(card.get("brand") or "")
        target["wb_title"] = str(card.get("title") or card.get("subject") or "")
        target["wb_tnved"] = str(card.get("tnved") or "")
        if target["wb_brand"].strip().casefold() != "stekker":
            target["wb_blockers"].append("wb_brand_mismatch")
        if not target["wb_nmID"]:
            target["wb_blockers"].append("wb_nmid_missing")
        if target["wb_tnved"] and "4202929800" not in target["wb_tnved"]:
            target["wb_blockers"].append("wb_tnved_out_of_scope")
        same = [x for x in ((card.get("documents") or {}).get("items") or []) if norm_number(x.get("number")) == number_key]
        exact = [x for x in same if str(x.get("type") or "") == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and (len(same) != 1 or len(exact) != 1):
            target["wb_blockers"].append("wb_existing_number_conflict")
        target["wb_exact_document"] = len(exact) == 1

    report = {
        "checked_at_utc": now(),
        "read_only": True,
        "number": NUMBER,
        "type": "declaration",
        "issue_date": ISSUE,
        "expiry_date": EXPIRY,
        "source_fsa_extract": str(SOURCE_PDF.relative_to(ROOT)),
        "source_fsa_extract_sha256": actual_sha,
        "source_signed_declaration_jpg": str(SOURCE_SIGNED_JPG.relative_to(ROOT)),
        "source_signed_declaration_jpg_sha256": signed_sha,
        "assignment_count": len(assignments),
        "ozon_existing_number_records": [{k: r.get(k) for k in ("certificate_id", "certificate_number", "type_code", "accordance_type_code", "status_code", "issue_date", "expire_date")} for r in exact_ozon_records],
        "targets": targets,
        "ozon_ready_count": sum(not t["ozon_blockers"] for t in targets),
        "wb_ready_count": sum(not t["wb_blockers"] for t in targets),
        "sample_date_clause": "signed declaration refers to date in sampling act; act date was not visible in the declaration image or FSA extract",
        "sample_date_applicability_confirmed_for_current_lots": False,
        "writes_performed": False,
        "local_files_deleted": False,
    }
    destination = HERE / "stekker_24659_crossplatform_preflight_20261023.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
