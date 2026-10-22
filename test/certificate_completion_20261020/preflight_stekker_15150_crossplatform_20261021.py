"""Read-only live cross-platform preflight for Stekker declaration 15150/25."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, doc_key, norm_number, wb_datetime  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА07.В.15150/25"
ISSUE = "2025-08-25"
EXPIRY = "2030-08-24"
FSA_ID = 20491822
ALLOWED_TNVED = {"8536500700", "8536691000", "8536699008", "8504405500"}
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/stekker/c3e79720d30db2f7da55a3cf.pdf"
EXPECTED_SHA256 = "33f07563a35bbdf20c64fb70816983f96d4a39064c233266ffa2970fbbe4f6fb"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
LIVE_MAP = HERE / "all_confirmed_source_assignments_live_20261021.csv"
OUT = HERE / "stekker_15150_crossplatform_preflight_live_20261021.json"
if OUT.exists():
    raise RuntimeError("output_exists")


def ozon_attr(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def parse_codes(values: list[str]) -> list[str]:
    return sorted({str(value).split(" - ", 1)[0].strip() for value in values if str(value).strip()})


def wb_codes(card: dict) -> list[str]:
    result = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        value = item.get("value")
        values = value if isinstance(value, list) else [value]
        result.extend(str(x or "").split(" - ", 1)[0].strip() for x in values if x)
    return sorted(set(result))


if not SOURCE.is_file():
    raise RuntimeError("source_pdf_missing")
source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
if EXPECTED_SHA256 and source_hash != EXPECTED_SHA256:
    raise RuntimeError("source_hash_changed")
with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
    all_assignments = [row for row in csv.DictReader(stream)
                       if norm_number(row.get("Номер/название документа")) == norm_number(NUMBER)]
assignments = [row for row in all_assignments
               if str(row.get("Применимость") or "").strip() == "Подтверждено статусом покрытия"]
offers = [str(row.get("Артикул продавца") or "").strip() for row in assignments]
if len(assignments) != 376 or len(set(offers)) != 376 or "" in offers:
    raise RuntimeError(f"assignment_count_or_offer_uniqueness:{len(assignments)}:{len(set(offers))}")
if any(str(row.get("Бренд подтвержденный") or "").strip().casefold() != "stekker" for row in assignments):
    raise RuntimeError("source_assignment_brand_conflict")
if source_hash != EXPECTED_SHA256:
    raise RuntimeError("source_hash_changed")
with LIVE_MAP.open(encoding="utf-8-sig", newline="") as stream:
    live_rows = [row for row in csv.DictReader(stream)
                 if norm_number(row.get("number")) == norm_number(NUMBER)]
live_by_offer = {str(row.get("offer_id") or ""): row for row in live_rows}
if len(live_by_offer) != 376 or set(live_by_offer) != set(offers):
    raise RuntimeError("live_source_map_target_mismatch")

client = Client()
ozon_products: dict[str, dict] = {}
for start in range(0, len(offers), 100):
    batch = offers[start:start + 100]
    result = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
    if not isinstance(result, list):
        raise RuntimeError("ozon_product_info_incomplete")
    for product in result:
        offer = str(product.get("offer_id") or "")
        if offer in ozon_products:
            raise RuntimeError("duplicate_ozon_offer_returned")
        ozon_products[offer] = product
ozon_attrs: dict[str, dict] = {}
for start in range(0, len(offers), 100):
    batch = offers[start:start + 100]
    result = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": batch}, "limit": len(batch)
    }).get("result")
    if not isinstance(result, list):
        raise RuntimeError("ozon_product_attributes_incomplete")
    for row in result:
        offer = str(row.get("offer_id") or "")
        if offer in ozon_attrs:
            raise RuntimeError("duplicate_ozon_attributes_returned")
        ozon_attrs[offer] = row
if set(ozon_products) != set(offers) or set(ozon_attrs) != set(offers):
    raise RuntimeError("ozon_live_offer_set_mismatch")

ozon_rows = []
for source_row in assignments:
    offer = str(source_row["Артикул продавца"]).strip()
    product, attrs = ozon_products[offer], ozon_attrs[offer]
    brands = ozon_attr(attrs, 85)
    raw_codes = ozon_attr(attrs, 22232)
    codes = parse_codes(raw_codes)
    p_id = str(product.get("product_id") or product.get("id") or "")
    sku = str(product.get("sku") or "")
    live_map = live_by_offer[offer]
    expected_id = str(live_map.get("ozon_product_id") or "")
    expected_sku = str(live_map.get("ozon_sku") or "")
    ozon_rows.append({
        "offer_id": offer, "product_id": p_id, "sku": sku, "name": product.get("name"),
        "archived": product.get("is_archived"), "brand_values": brands,
        "tnved_values": raw_codes, "tnved_codes": codes,
        "assigned_product_id": expected_id, "assigned_sku": expected_sku,
        "product_id_matches_assignment": not expected_id or p_id == expected_id,
        "sku_matches_assignment": not expected_sku or sku == expected_sku,
        "brand_matches": len(brands) == 1 and brands[0].casefold() == "stekker",
        "tnved_in_scope": bool(codes) and set(codes) <= ALLOWED_TNVED,
        "source_assignment": {key: source_row.get(key) for key in [
            "Основание сопоставления", "URL карточки/основания", "Локальный файл"]},
    })

records = []
page = 1
while page <= 100:
    response = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
    batch = response.get("certificates")
    if not isinstance(batch, list):
        raise RuntimeError("ozon_certificate_list_incomplete")
    records.extend(item for item in batch if norm_number(item.get("certificate_number")) == norm_number(NUMBER))
    if not batch or page >= int(response.get("page_count") or 0):
        break
    page += 1
else:
    raise RuntimeError("ozon_certificate_pages_limit")

found: dict[str, list[dict]] = collections.defaultdict(list)
cursor = {"limit": 100}
seen = set()
pages = total_cards = 0
wanted = set(offers)
while True:
    response = client.call("wb", "/content/v2/get/cards/list", {"settings": {
        "sort": {"ascending": True}, "cursor": cursor,
        "filter": {"withPhoto": -1},
    }})
    batch = response.get("cards")
    if response.get("error") or not isinstance(batch, list):
        raise RuntimeError("wb_catalog_page_invalid")
    returned = response.get("cursor") or {}
    if returned.get("total") != len(batch):
        raise RuntimeError("wb_catalog_page_count_mismatch")
    pages += 1
    total_cards += len(batch)
    for card in batch:
        offer = str(card.get("vendorCode") or "")
        if offer in wanted:
            found[offer].append(card)
    if pages % 50 == 0:
        print(json.dumps({"phase": "wb_read_only_catalog", "pages": pages,
                          "cards_read": total_cards, "targets_found": sum(map(len, found.values()))}), flush=True)
    if len(batch) < 100:
        break
    signature = (returned.get("updatedAt"), returned.get("nmID"))
    if None in signature or signature in seen:
        raise RuntimeError("wb_catalog_cursor_missing_or_repeated")
    seen.add(signature)
    cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}

desired_wb = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
wb_rows = []
ozon_by_offer = {row["offer_id"]: row for row in ozon_rows}
for offer in offers:
    cards = found.get(offer, [])
    if len(cards) != 1:
        wb_rows.append({"offer_id": offer, "card_count": len(cards), "safe_for_update": False,
                        "problem": "missing_or_duplicate_exact_wb_card"})
        continue
    card = cards[0]
    brand = str(card.get("brand") or "").strip()
    codes = wb_codes(card)
    same = [doc for doc in copy_documents(card) if norm_number(doc.get("number")) == norm_number(NUMBER)]
    exact = [doc for doc in same if doc_key(doc) == doc_key(desired_wb)
             and str(doc.get("startDate", ""))[:10] == ISSUE
             and str(doc.get("endDate", ""))[:10] == EXPIRY
             and doc.get("isEndless") is False]
    ozon = ozon_by_offer[offer]
    fallback_scope = not codes and ozon["tnved_in_scope"] and ozon["brand_matches"]
    identity = str(card.get("vendorCode") or "") == offer
    brand_ok = brand.casefold() == "stekker"
    tnved_ok = (bool(codes) and set(codes) <= ALLOWED_TNVED) or fallback_scope
    wb_rows.append({
        "offer_id": offer, "nmID": str(card.get("nmID") or ""), "brand": brand,
        "title": card.get("title"), "tnved_codes": codes, "identity_exact": identity,
        "brand_matches": brand_ok, "tnved_in_scope_or_verified_by_ozon": tnved_ok,
        "blank_tnved_fallback_to_same_ozon_offer": fallback_scope,
        "same_number_documents": same, "already_exact": len(same) == 1 and len(exact) == 1,
        "metadata_conflict": bool(same) and not (len(same) == 1 and len(exact) == 1),
        "safe_for_update": identity and brand_ok and tnved_ok and not same,
        "expected_nmID": str(live_by_offer[offer].get("wb_nmID") or ""),
        "nmID_matches_live_assignment": str(card.get("nmID") or "") == str(live_by_offer[offer].get("wb_nmID") or ""),
        "full_card": card,
    })

ozon_ok = all(row["archived"] is False and row["brand_matches"] and row["tnved_in_scope"]
              and row["product_id_matches_assignment"] and row["sku_matches_assignment"] for row in ozon_rows)
wb_ok = all(row.get("identity_exact") and row.get("brand_matches")
            and row.get("tnved_in_scope_or_verified_by_ozon") and not row.get("metadata_conflict")
            and row.get("nmID_matches_live_assignment")
            for row in wb_rows if row.get("card_count") == 1)
summary = {
    "checked_at_utc": now(), "read_only": True, "number": NUMBER,
    "official_fsa": {"record_id": FSA_ID, "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product",
                     "status": "active", "issue_date": ISSUE, "expiry_date": EXPIRY,
                     "product_scope": "Stekker switches PSW/RSW/MSW/GLS and sockets PST/RST/MST/GLS",
                     "tnved": sorted(ALLOWED_TNVED), "serial_production_sample_date_condition": True},
    "source_pdf": str(SOURCE), "source_pdf_sha256": source_hash, "assigned_target_count": len(assignments),
    "partial_coverage_assignments_skipped": len(all_assignments) - len(assignments),
    "ozon_live_product_count": len(ozon_rows), "ozon_all_identity_brand_and_tnved_in_scope": ozon_ok,
    "ozon_brand_counts": dict(collections.Counter(row["brand_values"][0] if len(row["brand_values"]) == 1 else "other" for row in ozon_rows)),
    "ozon_tnved_counts": dict(collections.Counter(";".join(row["tnved_codes"]) or "blank" for row in ozon_rows)),
    "ozon_exact_certificate_records": records, "ozon_exact_certificate_record_count": len(records),
    "wb_pages": pages, "wb_cards_read": total_cards, "wb_exact_card_count": sum(row.get("card_count") == 1 for row in wb_rows),
    "wb_safe_update_count": sum(row.get("safe_for_update") is True for row in wb_rows),
    "wb_already_exact_count": sum(row.get("already_exact") is True for row in wb_rows),
    "wb_problem_count": sum(row.get("card_count") != 1 or not row.get("identity_exact") or not row.get("brand_matches")
                             or not row.get("tnved_in_scope_or_verified_by_ozon") or row.get("metadata_conflict")
                             for row in wb_rows),
    "wb_tnved_counts": dict(collections.Counter(";".join(row.get("tnved_codes") or []) or "blank" for row in wb_rows)),
    "ozon_targets": ozon_rows, "wb_targets": wb_rows,
    "no_mutation_attempted": True, "local_file_deleted": False,
}
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(OUT)
print(json.dumps({key: value for key, value in summary.items() if key not in {"ozon_targets", "wb_targets", "ozon_exact_certificate_records"}},
                 ensure_ascii=False, indent=2))
