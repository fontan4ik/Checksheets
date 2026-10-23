#!/usr/bin/env python3
"""Fresh, read-only preflight for Navigator 14159 family docs."""
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

OFFERS = [
    "14159-1", "14243-1", "14272-1", "61634-1", "71920-1", "71922-1",
    "94822-1", "94829-1", "94839-1", "94841-1", "94827-1",
]
DOCS = [
    {
        "number": "ЕАЭС N RU Д-RU.РА08.В.46013/25",
        "type_code": "declaration",
        "wb_type": 2,
        "issue": "2025-09-22",
        "expiry": "2030-09-21",
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/20602391/common",
        "tnved": ["9405110013", "9405110033"],
        "source": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14159_3ffb334b638a.pdf",
        "sha256": "3ffb334b638ae6ae6cd31e70cb792ffd0948787ee05dd4fa558b0d594345888f",
        "assignment_type": "Декларация соответствия заявленным требованиям",
    },
    {
        "number": "ЕАЭС RU С-RU.НВ28.В.00220/25",
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "issue": "2025-09-08",
        "expiry": "2030-09-07",
        "fsa_url": "https://pub.fsa.gov.ru/rss/certificate/view/3604245/baseInfo",
        "tnved": ["9405110013", "9405110033"],
        "source": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14159_55159978bdf1.pdf",
        "sha256": "55159978bdf1b0a0ac1bb08558c16ad1790bdbaaaa7a707cc3d4f426f03ffed0",
        "assignment_type": "Сертификат соответствия требованиям техрегламента",
    },
]
OUT = HERE / "navigator_46013_00220_14159_fresh_preflight_20261023.json"


def attr_values(attrs, ident):
    mapping = {str(x.get("id")): x for x in attrs or []}
    return [str(v.get("value") or "").strip() for v in (mapping.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def normalized_codes(values):
    if not isinstance(values, list):
        values = [values]
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def wb_codes(card):
    vals = []
    for characteristic in card.get("characteristics") or []:
        label = "".join(str(characteristic.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = characteristic.get("value")
            vals.extend(raw if isinstance(raw, list) else [raw])
    return normalized_codes(vals)


def ozon_records(client):
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def main():
    if OUT.exists():
        raise RuntimeError("preflight_artifact_exists_inspect_before_retry")
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(encoding="utf-8-sig", newline="") as stream:
        assignments = list(csv.DictReader(stream))
    assignment_map = {}
    for offer in OFFERS:
        rows = [r for r in assignments if r.get("Артикул продавца") == offer
                and any(r.get("Номер/название документа") == d["number"] for d in DOCS)]
        if len(rows) != len(DOCS):
            raise RuntimeError(f"assignment_count_mismatch:{offer}:{len(rows)}")
        assignment_map[offer] = rows
    source_checks = []
    for doc in DOCS:
        path = ROOT / doc["source"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if digest != doc["sha256"]:
            raise RuntimeError("source_missing_or_hash_mismatch:" + doc["number"])
        for row in [r for rr in assignment_map.values() for r in rr if r.get("Номер/название документа") == doc["number"]]:
            if row.get("Применимость") != "Подтверждено источником" or row.get("SHA256 фактический") != doc["sha256"]:
                raise RuntimeError("assignment_source_evidence_mismatch:" + doc["number"])
        source_checks.append({"number": doc["number"], "sha256": digest, "path": doc["source"]})

    client = Client()
    products, attrs = [], []
    for start in range(0, len(OFFERS), 100):
        batch = OFFERS[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap, amap = collections.defaultdict(list), collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id") or "")].append(row)
    for row in attrs:
        amap[str(row.get("offer_id") or "")].append(row)
    records = ozon_records(client)

    report = {
        "checked_at_utc": now(),
        "read_only": True,
        "sources": source_checks,
        "documents": [{k: d[k] for k in ("number", "type_code", "issue", "expiry", "fsa_url", "tnved")} for d in DOCS],
        "targets": [],
        "summary": {},
        "writes_performed": False,
        "local_files_deleted": False,
        "wb_review_left_to_marketplace": True,
        "limitations": ["The sampled-product date on the FSA records is earlier than the current date; marketplace data does not confirm individual production-lot dates."],
    }
    for offer in OFFERS:
        conflicts = []
        product_rows, attr_rows = pmap[offer], amap[offer]
        if len(product_rows) != 1 or len(attr_rows) != 1:
            product, attr = {}, {}
            conflicts.append("ozon_product_or_attributes_not_unique")
        else:
            product, attr = product_rows[0], attr_rows[0]
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        brand = attr_values(attr.get("attributes"), 85)
        codes = normalized_codes(attr_values(attr.get("attributes"), 22232))
        title = str(product.get("name") or "")
        if not product_id or not sku:
            conflicts.append("ozon_identity_missing")
        if product.get("is_archived") is not False:
            conflicts.append("ozon_archived_or_unknown")
        if [x.casefold() for x in brand] != ["navigator"]:
            conflicts.append("ozon_brand_mismatch")
        if not codes or not set(codes).issubset(set(DOCS[0]["tnved"])):
            conflicts.append("ozon_tnved_out_of_scope")
        row_by_doc = {r.get("Номер/название документа"): r for r in assignment_map[offer]}
        for doc in DOCS:
            row = row_by_doc[doc["number"]]
            if offer not in str(row.get("Основание сопоставления") or "") and "exact per-product" not in str(row.get("Основание сопоставления") or ""):
                conflicts.append("assignment_model_evidence_missing:" + doc["number"])
            matches = [r for r in records if norm_number(r.get("certificate_number")) == norm_number(doc["number"])]
            if len(matches) > 1:
                conflicts.append("duplicate_ozon_records:" + doc["number"])
            elif matches and (matches[0].get("type_code") != doc["type_code"]
                    or str(matches[0].get("issue_date") or "")[:10] != doc["issue"]
                    or str(matches[0].get("expire_date") or "")[:10] != doc["expiry"]):
                conflicts.append("ozon_record_metadata_conflict:" + doc["number"])
        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            conflicts.append("wb_card_missing_or_ambiguous")
            card = {}
        else:
            card = cards[0]
        wb_brand = str(card.get("brand") or "")
        wb_code_list = wb_codes(card)
        if not card.get("nmID"):
            conflicts.append("wb_nm_id_missing")
        if wb_brand.casefold() != "navigator":
            conflicts.append("wb_brand_mismatch")
        if not wb_code_list or not set(wb_code_list).issubset(set(DOCS[0]["tnved"])):
            conflicts.append("wb_tnved_out_of_scope")
        wb_docs = ((card.get("documents") or {}).get("items") or [])
        doc_checks = []
        for doc in DOCS:
            same = [x for x in wb_docs if norm_number(x.get("number")) == norm_number(doc["number"])]
            exact = [x for x in same if str(x.get("type")) == str(doc["wb_type"])
                     and str(x.get("startDate") or "")[:10] == doc["issue"]
                     and str(x.get("endDate") or "")[:10] == doc["expiry"]
                     and x.get("isEndless") is False]
            if same and len(exact) != 1:
                conflicts.append("wb_metadata_conflict:" + doc["number"])
            doc_checks.append({"number": doc["number"], "same_number_count": len(same), "exact_count": len(exact)})
        report["targets"].append({
            "offer_id": offer,
            "ozon": {"product_id": product_id, "sku": sku, "title": title, "brand": brand, "tnved": codes,
                     "exact_records": {d["number"]: sum(1 for r in records if norm_number(r.get("certificate_number")) == norm_number(d["number"])) for d in DOCS}},
            "wb": {"nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                   "brand": wb_brand, "title": card.get("title"), "tnved": wb_code_list, "document_checks": doc_checks},
            "eligible_both_platforms": not conflicts,
            "conflicts": conflicts,
            "assignment_evidence": {d["number"]: row_by_doc[d["number"]].get("Основание сопоставления") for d in DOCS},
        })
    report["summary"] = {
        "offers": len(report["targets"]),
        "eligible_both_platforms": sum(t["eligible_both_platforms"] for t in report["targets"]),
        "eligible_ozon_identity_tnved": sum(not any(c.startswith(("ozon_", "duplicate_ozon", "ozon_record")) for c in t["conflicts"]) for t in report["targets"]),
        "eligible_wb_identity_tnved": sum(not any(c.startswith(("wb_",)) for c in t["conflicts"]) for t in report["targets"]),
        "conflict_counts": dict(collections.Counter(c for t in report["targets"] for c in t["conflicts"])),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
