#!/usr/bin/env python3
"""Fresh, read-only scope preflight for uncovered Arlight 52132/25 products."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import current_catalog, code_values  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
NORMALIZED_NUMBER = norm_number(NUMBER)
SOURCE_REL = "output_to_user/certificates/group_1/documents/arlight/94D46BAFE361664EA7621A1A4A70FD33.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA256 = "1af35bb24d9f014ea59b14ffbd88f42b705a4f5fb285e57a683d24542c26c225"
RECORD_ID = 5920271
ISSUE = "2025-10-22"
EXPIRY = "2030-10-20"
ALLOWED_TNVED = {"9405110013", "9405110033", "9405110039", "9405420012", "9405420032", "9405420039"}
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "arlight_52132_uncovered_preflight_20261022.json"
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"


def unique(values: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def load_assignments() -> dict[str, dict]:
    snapshot = json.loads(SNAPSHOT.read_text())
    products = snapshot["ozon_products"]["products"]
    products_by_sku = {str(p.get("sku")): p for p in products if p.get("sku")}
    covered_ids = set()
    today = date.today().isoformat()
    for certificate in snapshot["ozon_certificates"]["certificates"]:
        issue = str(certificate.get("issue_date") or "")[:10]
        expiry = str(certificate.get("expire_date") or "")[:10]
        if (certificate.get("status_code") != "approved" or not expiry
                or issue > today or expiry < today):
            continue
        for binding in certificate.get("live_bindings") or []:
            product = products_by_sku.get(str(binding.get("sku") or ""))
            if (binding.get("product_status_code") == "approved" and product
                    and str(product.get("product_id")) == str(binding.get("product_id"))):
                covered_ids.add(str(product.get("product_id")))
    uncovered_offers = {
        str(p.get("offer_id")) for p in products if not p.get("is_archived")
        and str(p.get("product_id")) not in covered_ids
    }
    rows: dict[str, dict] = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (norm_number(row.get("Номер/название документа")) != NORMALIZED_NUMBER
                    or row.get("Локальный файл") != SOURCE_REL
                    or row.get("Бренд подтвержденный") != "Arlight"
                    or row.get("Применимость") != "Подтверждено статусом покрытия"
                    or str(row.get("Артикул продавца") or "").strip() not in uncovered_offers):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in rows:
                raise RuntimeError("missing_or_duplicate_assignment_offer:" + offer)
            rows[offer] = {
                "offer_id": offer,
                "assignment_product_name": row.get("Название товара Ozon"),
                "scope_evidence": row.get("Основание сопоставления"),
                "validity_note": row.get("Сроки/валидность"),
                "source_url": row.get("URL документа"),
            }
    if len(rows) != 443:
        raise RuntimeError(f"unexpected_confirmed_uncovered_assignment_count:{len(rows)}")
    return rows


def all_ozon_certificates(client: Client) -> list[dict]:
    records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        records.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return records
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists_inspect_before_retry")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_file_missing_or_hash_mismatch")
    assignments = load_assignments()
    offers = sorted(assignments)
    client = Client()

    products: dict[str, dict] = {}
    attributes: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        ps = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        attrs = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result")
        if not isinstance(ps, list) or not isinstance(attrs, list):
            raise RuntimeError("ozon_product_or_attributes_response_incomplete")
        for row in ps:
            offer = str(row.get("offer_id") or "")
            if offer in products:
                raise RuntimeError("duplicate_ozon_offer:" + offer)
            products[offer] = row
        for row in attrs:
            offer = str(row.get("offer_id") or "")
            if offer in attributes:
                raise RuntimeError("duplicate_ozon_attribute_offer:" + offer)
            attributes[offer] = row
    if set(products) != set(offers) or set(attributes) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_mismatch")

    records = all_ozon_certificates(client)
    exact_records = [r for r in records if norm_number(r.get("certificate_number")) == NORMALIZED_NUMBER]
    if len(exact_records) != 1 or str(exact_records[0].get("certificate_id")) != str(RECORD_ID):
        raise RuntimeError("exact_ozon_record_identity_ambiguous_or_changed")
    record = exact_records[0]
    bindings = client.ozon_bindings(RECORD_ID)
    bound_product_ids = {str(x.get("product_id")) for x in bindings}
    bound_skus = {str(x.get("sku")) for x in bindings}
    today = date.today().isoformat()
    record_current_approved = (
        record.get("status_code") == "approved"
        and str(record.get("issue_date") or "")[:10] <= today
        and str(record.get("expire_date") or "")[:10] >= today
        and str(record.get("issue_date") or "")[:10] == ISSUE
        and str(record.get("expire_date") or "")[:10] == EXPIRY
    )

    targets = []
    for offer in offers:
        product, attr = products[offer], attributes[offer]
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        brand = attr_values(attr, 85)
        tnved = unique(attr_values(attr, 22232))
        problems = []
        if product.get("is_archived") is not False:
            problems.append("product_archived_or_status_unclear")
        if brand != ["Arlight"]:
            problems.append("ozon_brand_mismatch_or_ambiguous")
        if len(tnved) != 1 or tnved[0] not in ALLOWED_TNVED:
            problems.append("ozon_tnved_out_of_document_scope_or_ambiguous")
        if not record_current_approved:
            problems.append("existing_ozon_document_not_current_and_approved")
        if not product_id or not sku:
            problems.append("missing_ozon_product_identity")
        if product_id in bound_product_ids or sku in bound_skus:
            problems.append("already_bound_or_binding_identity_conflict")
        targets.append({
            **assignments[offer], "product_id": product_id, "sku": sku,
            "live_name": product.get("name"), "brand_values": brand, "tnved_codes": tnved,
            "is_archived": product.get("is_archived"), "already_bound": product_id in bound_product_ids or sku in bound_skus,
            "eligible_ozon_bind": not problems, "ozon_problems": problems,
        })

    wanted = set(offers)
    cards_by_offer, wb_pages, wb_rows = current_catalog(client, wanted)
    wb_targets = []
    desired_meta = {"type": 2, "number": NUMBER, "startDate": "2025-10-22T00:00:00Z",
                    "endDate": "2030-10-20T00:00:00Z", "isEndless": False}
    for target in targets:
        offer = target["offer_id"]
        cards = cards_by_offer.get(offer, [])
        problems = []
        card = cards[0] if len(cards) == 1 else None
        tnved = unique(code_values(card)) if card else []
        existing = []
        already_exact = False
        if len(cards) == 0:
            problems.append("no_exact_wb_card")
        elif len(cards) != 1:
            problems.append("duplicate_exact_wb_card")
        else:
            if str(card.get("vendorCode") or "") != offer:
                problems.append("wb_vendor_code_mismatch")
            if str(card.get("brand") or "").strip().casefold() != "arlight":
                problems.append("wb_brand_mismatch_or_unclear")
            if len(tnved) != 1 or tnved[0] not in ALLOWED_TNVED:
                problems.append("wb_tnved_out_of_scope_or_ambiguous")
            existing = [d for d in copy_documents(card)
                        if norm_number(d.get("number")) == NORMALIZED_NUMBER]
            if existing:
                already_exact = (len(existing) == 1
                    and str(existing[0].get("type")) == str(desired_meta["type"])
                    and str(existing[0].get("startDate", ""))[:10] == ISSUE
                    and str(existing[0].get("endDate", ""))[:10] == EXPIRY)
                if not already_exact:
                    problems.append("same_document_number_metadata_conflict")
        wb_targets.append({
            "offer_id": offer, "nmID": str(card.get("nmID") or "") if card else "",
            "title": card.get("title") if card else None, "brand": card.get("brand") if card else None,
            "tnved_codes": tnved, "existing_exact_documents": existing,
            "already_exact": already_exact, "safe_for_update": not problems and not already_exact,
            "problems": problems, "full_card": card,
        })

    output = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_file": str(SOURCE), "source_sha256": SOURCE_SHA256,
        "confirmed_assignment_count": len(assignments), "fresh_ozon_product_count": len(products),
        "ozon_document_record": {k: record.get(k) for k in (
            "certificate_id", "certificate_number", "type_code", "status_code", "issue_date",
            "expire_date", "products_count")},
        "ozon_document_current_and_approved": record_current_approved,
        "ozon_existing_binding_count": len(bindings),
        "ozon_eligible_targets": sum(x["eligible_ozon_bind"] for x in targets),
        "ozon_problem_counts": dict(collections.Counter(p for x in targets for p in x["ozon_problems"])),
        "ozon_targets": targets,
        "wb_full_catalog_pages": wb_pages, "wb_full_catalog_rows": wb_rows,
        "wb_exact_target_card_count": sum(len(cards_by_offer.get(offer, [])) == 1 for offer in offers),
        "wb_safe_targets": sum(x["safe_for_update"] for x in wb_targets),
        "wb_already_exact_targets": sum(x["already_exact"] for x in wb_targets),
        "wb_problem_counts": dict(collections.Counter(p for x in wb_targets for p in x["problems"])),
        "wb_targets": wb_targets, "wb_review_left_pending": True,
        "local_file_deleted": False,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items() if k not in {"ozon_targets", "wb_targets"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
