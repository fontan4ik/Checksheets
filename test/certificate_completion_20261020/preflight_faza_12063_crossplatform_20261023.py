#!/usr/bin/env python3
"""Fresh read-only preflight for Faza declaration 12063/23."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import norm_number

NUMBER = "ЕАЭС N RU Д-HK.РА02.В.12063/23"
FSA_ID = "17493213"
SOURCE = "output_to_user/certificates/additional_search/brand_research/faza/followup_2026_10_02_suppliers/docs/037_battery_12063_23_manufacturer.pdf"
SOURCE_SHA256 = "2d8f4e6125dc8a1a4fc96787d5c4a9fc3842c5b13b41ca780543415d0259fc5e"
ISSUE, EXPIRY = "2023-03-01", "2028-02-29"
TNVED = {"8513100000"}
OUT = HERE / "faza_12063_crossplatform_preflight_20261023.json"


def values(attrs, ident):
    mapping = {str(x.get("id")): x for x in attrs or []}
    return [str(v.get("value") or "").strip() for v in (mapping.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(raw):
    if not isinstance(raw, list):
        raw = [raw]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in raw if str(x).strip()})


def wb_codes(card):
    out = []
    for c in card.get("characteristics") or []:
        name = "".join(str(c.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            raw = c.get("value")
            out.extend(raw if isinstance(raw, list) else [raw])
    return codes(out)


def brand_key(value):
    value = str(value or "").casefold().replace("ё", "е")
    return value.translate(str.maketrans({"f": "ф", "a": "а", "z": "з"}))


def all_ozon_records(client):
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return out
    raise RuntimeError("ozon_certificate_page_limit")


def main():
    if OUT.exists():
        raise RuntimeError("preflight_artifact_exists_inspect_before_retry")
    source_path = ROOT / SOURCE
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path.is_file() else None
    if digest != SOURCE_SHA256:
        raise RuntimeError("source_missing_or_sha256_mismatch")
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(encoding="utf-8-sig", newline="") as f:
        assignments = [r for r in csv.DictReader(f) if r.get("Номер/название документа") == NUMBER
                       and r.get("Локальный файл") == SOURCE and r.get("Применимость") == "Подтверждено источником"]
    assignments.sort(key=lambda r: r.get("Артикул продавца") or "")
    offers = [r.get("Артикул продавца") for r in assignments]
    if len(offers) != 11 or len(set(offers)) != len(offers):
        raise RuntimeError("assignment_offer_count_or_uniqueness_conflict")
    client = Client()
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pmap, amap = collections.defaultdict(list), collections.defaultdict(list)
    for p in products: pmap[str(p.get("offer_id") or "")].append(p)
    for a in attrs: amap[str(a.get("offer_id") or "")].append(a)
    records = all_ozon_records(client)
    matches = [r for r in records if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_records_for_document")
    record = matches[0] if matches else None
    record_metadata_exact = bool(record and record.get("type_code") == "declaration"
                                  and str(record.get("issue_date") or "")[:10] == ISSUE
                                  and str(record.get("expire_date") or "")[:10] == EXPIRY)
    bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    bound_by_product = collections.defaultdict(list)
    for b in bindings: bound_by_product[str(b.get("product_id") or "")].append(b)
    targets = []
    for assignment in assignments:
        offer = assignment["Артикул продавца"]
        conflicts = []
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            product, attr = {}, {}
            conflicts.append("ozon_identity_missing_or_ambiguous")
        else:
            product, attr = pmap[offer][0], amap[offer][0]
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        oz_brand = values(attr.get("attributes"), 85)
        oz_tnved = codes(values(attr.get("attributes"), 22232))
        title = str(product.get("name") or "")
        source_name = str(assignment.get("Название товара Ozon") or "")
        if not product_id or not sku: conflicts.append("ozon_identity_missing")
        if product.get("is_archived") is not False: conflicts.append("ozon_archived_or_unknown")
        if not oz_brand or any(brand_key(x) != "фаза" for x in oz_brand): conflicts.append("ozon_brand_mismatch")
        if not oz_tnved or not set(oz_tnved).issubset(TNVED): conflicts.append("ozon_tnved_out_of_scope")
        if title.casefold() != source_name.casefold(): conflicts.append("ozon_title_changed_from_source_assignment")
        if record and (not record_metadata_exact or record.get("status_code") not in {"approved", "under_review"}):
            conflicts.append("ozon_record_metadata_or_status_conflict")
        prior = bound_by_product.get(product_id, [])
        if prior and (len(prior) != 1 or str(prior[0].get("sku") or "") != sku):
            conflicts.append("ozon_binding_conflict")

        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        card = cards[0] if len(cards) == 1 else {}
        if len(cards) != 1: conflicts.append("wb_card_missing_or_ambiguous")
        wb_brand = str(card.get("brand") or "")
        wb_tnved = wb_codes(card)
        if brand_key(wb_brand) != "фаза": conflicts.append("wb_brand_mismatch")
        if not card.get("nmID"): conflicts.append("wb_nm_id_missing")
        if not wb_tnved or not set(wb_tnved).issubset(TNVED): conflicts.append("wb_tnved_out_of_scope")
        items = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and len(exact) != 1: conflicts.append("wb_metadata_conflict")
        targets.append({
            "offer_id": offer,
            "ozon": {"product_id": product_id, "sku": sku, "title": title, "brand": oz_brand, "tnved": oz_tnved,
                     "existing_exact_bindings": sum(1 for b in prior if str(b.get("sku") or "") == sku)},
            "wb": {"nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                   "brand": wb_brand, "title": card.get("title"), "tnved": wb_tnved,
                   "existing_same_number": len(same), "existing_exact": len(exact)},
            "official_assignment_evidence": assignment.get("Основание сопоставления"),
            "eligible_both_platforms": not conflicts,
            "conflicts": conflicts,
        })
    report = {
        "checked_at_utc": now(), "read_only": True, "document": {"number": NUMBER, "type_code": "declaration",
          "issue_date": ISSUE, "expiry_date": EXPIRY, "fsa_registry_id": FSA_ID,
          "fsa_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product",
          "fsa_status_from_live_ui": "Действует", "fsa_tnved": sorted(TNVED), "sample_manufacture_date": "2023-01",
          "source": SOURCE, "source_sha256": digest, "source_assignment_count": len(assignments)},
        "ozon_record": ({k: record.get(k) for k in ["certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date"]} if record else None),
        "targets": targets,
        "summary": {"offers": len(targets), "eligible_both_platforms": sum(t["eligible_both_platforms"] for t in targets),
                     "conflict_counts": dict(collections.Counter(c for t in targets for c in t["conflicts"]))},
        "writes_performed": False, "local_file_deleted": False,
        "limitation": "FSA declaration begins for serial production from the sampled manufacture date 2023-01; individual lot dates are not available in marketplace records.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
