#!/usr/bin/env python3
"""Read-only live eligibility check for Arlight declaration 96174/25."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SOURCE_REL = "output_to_user/certificates/group_1/documents/arlight/45D89DF9A2BEE34EB17BF3A4CF0257A3.pdf"
OUT = HERE / "arlight_96174_live_preflight_v2_20261022.json"
NUMBER = "ЕАЭС N RU Д-CN.РА08.В.96174/25"
ISSUE = "2025-10-06"
EXPIRE = "2030-10-05"
REGISTRY_ID = "20688477"
ALLOWED_TNVED = {"8537101000", "8537109100", "8537109800"}
sys.path.insert(0, str(PILOT))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents  # noqa: E402


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_tnved(values) -> list[str]:
    if not isinstance(values, list):
        values = [values]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def wb_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return parse_tnved(values)


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    source = ROOT / SOURCE_REL
    actual_hash = sha256(source)
    with ASSIGNMENTS.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = [row for row in reader if row.get("Локальный файл") == SOURCE_REL]
    if len(rows) != 87 or len({row["Артикул продавца"] for row in rows}) != 87:
        raise RuntimeError(f"assignment_source_rows_changed:{len(rows)}")
    if any(row.get("Применимость") != "Подтверждено статусом покрытия" for row in rows):
        raise RuntimeError("source_assignments_not_all_confirmed")
    targets = []
    for row in rows:
        offer = str(row["Артикул продавца"]).strip()
        article = offer[:-2] if offer.endswith("-1") else offer
        targets.append({"offer_id": offer, "article": article,
                        "source_name": row.get("Название товара Ozon"),
                        "source_evidence": row.get("Основание сопоставления"),
                        "source_url": row.get("URL карточки/основания")})

    client = Client()
    existing = [x for x in list_certificates(client)
                if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(existing) > 1:
        raise RuntimeError("duplicate_ozon_records_for_document")
    record = existing[0] if existing else None
    record_exact = None
    if record:
        record_exact = (record.get("type_code") == "declaration"
                        and str(record.get("issue_date") or "")[:10] == ISSUE
                        and str(record.get("expire_date") or "")[:10] == EXPIRE)

    offers = [x["offer_id"] for x in targets]
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    product_map = collections.defaultdict(list)
    attr_map = collections.defaultdict(list)
    for item in products:
        product_map[str(item.get("offer_id") or "")].append(item)
    for item in attrs:
        attr_map[str(item.get("offer_id") or "")].append(item)

    ozon_targets, wb_targets = [], []
    ozon_conflicts = collections.Counter()
    wb_conflicts = collections.Counter()
    for target in targets:
        offer = target["offer_id"]
        conflicts = []
        if len(product_map[offer]) != 1 or len(attr_map[offer]) != 1:
            conflicts.append("ozon_live_product_or_attributes_not_unique")
            product, attr = {}, {}
        else:
            product, attr = product_map[offer][0], attr_map[offer][0]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        values = {str(x.get("id")): [str(v.get("value") or "").strip()
                  for v in x.get("values") or [] if str(v.get("value") or "").strip()]
                  for x in attr.get("attributes") or []}
        brands = values.get("85", [])
        tnved = parse_tnved(values.get("22232", []))
        if not product_id or not sku:
            conflicts.append("ozon_product_identity_missing")
        if product.get("is_archived") is not False:
            conflicts.append("ozon_product_archived_or_state_unknown")
        if brands != ["Arlight"]:
            conflicts.append("ozon_brand_not_exact")
        live_name = str(product.get("name") or "").strip()
        source_name = str(target.get("source_name") or "").strip()
        if (target["article"] not in live_name
                and live_name.casefold() != source_name.casefold()):
            conflicts.append("ozon_live_name_not_equal_to_source_assignment")
        if not tnved or not set(tnved).issubset(ALLOWED_TNVED):
            conflicts.append("ozon_tnved_not_exactly_in_fsa_scope")
        ozon_targets.append({**target, "product_id": product_id, "sku": sku,
                             "live_name": product.get("name"),
                             "live_name_exact_source_assignment": live_name.casefold() == source_name.casefold(),
                             "brand_values": brands,
                             "tnved_codes": tnved, "eligible": not conflicts,
                             "conflicts": conflicts})
        ozon_conflicts.update(conflicts)

        cards = client.wb_cards(offer)
        wconflicts = []
        if len(cards) != 1:
            card = {}
            wconflicts.append("no_unique_exact_wb_card")
        else:
            card = cards[0]
        nm_id = str(card.get("nmID") or "")
        vendor = str(card.get("vendorCode") or "")
        brand = str(card.get("brand") or "")
        card_tnved = wb_tnved(card)
        if vendor != offer:
            wconflicts.append("wb_vendor_code_mismatch")
        if brand.casefold() != "arlight":
            wconflicts.append("wb_brand_not_exact")
        if not nm_id:
            wconflicts.append("wb_nm_id_missing")
        if not card_tnved or not set(card_tnved).issubset(ALLOWED_TNVED):
            wconflicts.append("wb_tnved_not_exactly_in_fsa_scope")
        docs = copy_documents(card) if card else []
        same_number = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same_number if int(x.get("type") or 0) == 2
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRE]
        if same_number and len(exact) != 1:
            wconflicts.append("wb_same_number_metadata_conflict")
        wb_targets.append({**target, "nmID": nm_id, "vendorCode": vendor, "brand": brand,
                           "title": card.get("title"), "tnved_codes": card_tnved,
                           "already_exact": len(exact) == 1,
                           "eligible": not wconflicts, "conflicts": wconflicts})
        wb_conflicts.update(wconflicts)

    result = {
        "checked_at_utc": now(), "read_only": True, "brand": "Arlight",
        "number": NUMBER, "fsa_registry_id": REGISTRY_ID, "fsa_status": "active",
        "issue_date": ISSUE, "expire_date": EXPIRE, "fsa_tnved": sorted(ALLOWED_TNVED),
        "fsa_scope": "LED equipment controllers, SMART, ARL, TUYA, KNX, DALI, KINETIC, SR; Arlight and Intelligent Arlight.",
        "source_file": SOURCE_REL, "source_sha256": actual_hash,
        "manufacturer_pdf_url": "https://arlight.ru/upload/certificates/45D89DF9A2BEE34EB17BF3A4CF0257A3.pdf",
        "source_assignment_count": len(targets), "ozon_record": record,
        "ozon_record_metadata_exact": record_exact,
        "ozon_targets": ozon_targets, "wb_targets": wb_targets,
        "summary": {
            "target_offer_document_pairs": len(targets),
            "ozon_eligible_pairs": sum(x["eligible"] for x in ozon_targets),
            "ozon_already_bound_pairs": 0,
            "wb_exact_cards": sum(bool(x["nmID"]) for x in wb_targets),
            "wb_eligible_pairs": sum(x["eligible"] for x in wb_targets),
            "wb_already_exact_pairs": sum(x["already_exact"] for x in wb_targets),
            "ozon_conflicts": dict(ozon_conflicts), "wb_conflicts": dict(wb_conflicts),
        },
    }
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({"output": str(OUT), "summary": result["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
