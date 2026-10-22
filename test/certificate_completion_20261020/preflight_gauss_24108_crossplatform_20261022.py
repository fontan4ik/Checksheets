#!/usr/bin/env python3
"""Fresh, read-only catalog preflight for Gauss declaration 24108/24."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/3dbd3e80a412e4a3795dca08.pdf"
OUT = HERE / "gauss_24108_crossplatform_preflight_20261022.json"
NUMBER = "ЕАЭС N RU Д-CN.РА10.В.24108/24"
REGISTRY_ID = "19574422"
ISSUE_DATE = "2024-11-06"
EXPIRE_DATE = "2029-11-05"
SOURCE_SHA256 = "2b2688113b066f45d6a961f3f81fa0da7fedf68515c878856164e87c42016969"
ALLOWED_ARTICLES = {
    "1050112", "1070112", "1080112", "1130112", "1170112", "1180112",
    "1200112", "1220112", "1290112", "1310112", "1320112", "1340112",
    "1350112", "1370112", "1100112", "1110112", "1190112", "1230112",
    "1250112", "1260112", "1280112", "1400112", "1470112", "1480112",
}
ALLOWED_TNVED = {"8539520001", "8539520003", "8539520009"}

sys.path.insert(0, str(PILOT))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402


def codes(values: list[object]) -> list[str]:
    return sorted({str(value).split(" - ", 1)[0].strip() for value in values if str(value).strip()})


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(ident)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def card_tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        label = re.sub(r"\s+", "", str(char.get("name") or "").casefold()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = char.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return codes(values)


def list_certificates(client: Client) -> list[dict]:
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(rows)
        if not rows or page >= int(result.get("page_count") or 0):
            return out
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_first")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_pdf_missing_or_hash_mismatch")
    source_by_offer: dict[str, dict] = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("Применимость") != "Подтверждено статусом покрытия"
                    or norm_number(row.get("Номер/название документа")) != norm_number(NUMBER)
                    or row.get("Локальный файл") != str(SOURCE.relative_to(ROOT))):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer:
                base_article = offer.rsplit("-", 1)[0]
                if base_article not in ALLOWED_ARTICLES:
                    raise RuntimeError("source_offer_not_in_official_fsa_article_scope:" + offer)
                source_by_offer[offer] = {"offer_id": offer, "article": base_article,
                                          "source_evidence": row.get("Основание сопоставления"),
                                          "source_validity": row.get("Сроки/валидность"),
                                          "source_url": row.get("URL документа")}
    if len(source_by_offer) != 63:
        raise RuntimeError("unexpected_confirmed_assignment_offer_count:" + str(len(source_by_offer)))

    client = Client()
    offers = sorted(source_by_offer)
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    pm, am = collections.defaultdict(list), collections.defaultdict(list)
    for item in products:
        pm[str(item.get("offer_id") or "")].append(item)
    for item in attrs:
        am[str(item.get("offer_id") or "")].append(item)
    certs = list_certificates(client)
    matches = [row for row in certs if norm_number(row.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) > 1:
        record_conflict = "duplicate_ozon_document_records"
        record = None
    else:
        record_conflict = None
        record = matches[0] if matches else None
    record_bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    existing_by_product = collections.defaultdict(list)
    for item in record_bindings:
        existing_by_product[str(item.get("product_id") or "")].append(item)
    ozon_rows = []
    expected_identity = {}
    for offer in offers:
        conflicts = []
        if len(pm[offer]) != 1 or len(am[offer]) != 1:
            conflicts.append("ozon_offer_or_attributes_not_unique")
            product, attr = (pm[offer][0] if pm[offer] else {}), (am[offer][0] if am[offer] else {})
        else:
            product, attr = pm[offer][0], am[offer][0]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        brand = attr_values(attr, 85)
        tnved = codes(attr_values(attr, 22232))
        article = source_by_offer[offer]["article"]
        if product.get("is_archived") is not False:
            conflicts.append("ozon_archived_or_unknown")
        if brand != ["Gauss"]:
            conflicts.append("ozon_brand_mismatch")
        if not product_id or not sku:
            conflicts.append("ozon_product_identity_missing")
        if not tnved or not set(tnved) <= ALLOWED_TNVED:
            conflicts.append("ozon_tnved_outside_fsa_scope")
        binding_rows = existing_by_product.get(product_id, [])
        if len(binding_rows) > 1:
            conflicts.append("ozon_duplicate_bindings_for_product")
        if binding_rows and str(binding_rows[0].get("sku") or "") != sku:
            conflicts.append("ozon_existing_binding_sku_conflict")
        expected_identity[offer] = {"product_id": product_id, "sku": sku}
        ozon_rows.append({**source_by_offer[offer], "product_id": product_id, "sku": sku,
                          "live_name": product.get("name"), "brand_values": brand,
                          "tnved_codes": tnved, "eligible": not conflicts,
                          "already_bound": bool(binding_rows),
                          "existing_binding_status": binding_rows[0].get("product_status_code") if len(binding_rows) == 1 else None,
                          "conflicts": conflicts})

    wb_rows = []
    for index, offer in enumerate(offers, 1):
        conflicts = []
        cards = client.wb_cards(offer)
        card = cards[0] if len(cards) == 1 else {}
        if len(cards) != 1:
            conflicts.append("wb_exact_card_count_" + str(len(cards)))
        if card and str(card.get("vendorCode") or "") != offer:
            conflicts.append("wb_vendor_code_mismatch")
        if card and str(card.get("brand") or "").strip().casefold() != "gauss":
            conflicts.append("wb_brand_mismatch")
        tnved = card_tnved(card) if card else []
        if not tnved or not set(tnved) <= ALLOWED_TNVED:
            conflicts.append("wb_tnved_outside_fsa_scope")
        items = ((card.get("documents") or {}).get("items") or []) if card else []
        same = [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if int(x.get("type") or 0) == 2
                 and str(x.get("startDate") or "")[:10] == ISSUE_DATE
                 and str(x.get("endDate") or "")[:10] == EXPIRE_DATE
                 and x.get("isEndless") is False]
        if same and (len(same) != 1 or len(exact) != 1):
            conflicts.append("wb_existing_number_metadata_conflict")
        wb_rows.append({**source_by_offer[offer], "nmID": str(card.get("nmID") or "") if card else None,
                        "vendorCode": card.get("vendorCode") if card else None,
                        "brand": card.get("brand") if card else None, "title": card.get("title") if card else None,
                        "tnved_codes": tnved, "already_exact": len(exact) == 1,
                        "exact_existing_document_count": len(exact), "eligible": not conflicts,
                        "conflicts": conflicts})
        if index % 20 == 0 or index == len(offers):
            print(json.dumps({"wb_cards_checked": index, "total": len(offers)}, ensure_ascii=False), flush=True)

    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE_DATE
                   or str(record.get("expire_date") or "")[:10] != EXPIRE_DATE
                   or record.get("status_code") not in {"approved", "under_review"}):
        record_conflict = "ozon_record_metadata_or_status_conflict"
    result = {
        "checked_at_utc": now(), "read_only": True, "brand": "Gauss", "document_number": NUMBER,
        "type": "declaration", "fsa_registry_id": REGISTRY_ID, "fsa_status": "active",
        "issue_date": ISSUE_DATE, "expire_date": EXPIRE_DATE,
        "fsa_registry_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{REGISTRY_ID}/common",
        "fsa_product_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{REGISTRY_ID}/product",
        "fsa_article_count": len(ALLOWED_ARTICLES), "allowed_tnved": sorted(ALLOWED_TNVED),
        "source_pdf": str(SOURCE.relative_to(ROOT)), "source_sha256": SOURCE_SHA256,
        "confirmed_assignment_offers": len(offers),
        "ozon_record": record, "ozon_record_conflict": record_conflict,
        "ozon_bindings_existing": len(record_bindings),
        "ozon_eligible_targets": sum(x["eligible"] for x in ozon_rows),
        "ozon_already_bound_targets": sum(x["eligible"] and x["already_bound"] for x in ozon_rows),
        "ozon_conflicts": dict(collections.Counter(c for x in ozon_rows for c in x["conflicts"])),
        "wb_eligible_targets": sum(x["eligible"] for x in wb_rows),
        "wb_already_exact_targets": sum(x["eligible"] and x["already_exact"] for x in wb_rows),
        "wb_conflicts": dict(collections.Counter(c for x in wb_rows for c in x["conflicts"])),
        "jointly_eligible_targets": sum(o["eligible"] and w["eligible"]
                                         for o, w in zip(ozon_rows, wb_rows)),
        "ozon_targets": ozon_rows, "wb_targets": wb_rows,
        "local_source_pdf_deleted": False,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "checked_at_utc", "confirmed_assignment_offers", "ozon_record", "ozon_record_conflict",
        "ozon_eligible_targets", "ozon_already_bound_targets", "wb_eligible_targets",
        "wb_already_exact_targets", "jointly_eligible_targets", "ozon_conflicts", "wb_conflicts")},
        ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
