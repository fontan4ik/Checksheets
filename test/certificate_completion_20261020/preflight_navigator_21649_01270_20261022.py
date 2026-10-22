#!/usr/bin/env python3
"""Read-only cross-platform preflight for Navigator NI incandescent lamps."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
OUT = HERE / "navigator_21649_01270_live_preflight_20261022.json"

DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА07.В.21649/22",
        "type_code": "declaration",
        "wb_type": 2,
        "issue_date": "2022-10-07",
        "expire_date": "2027-10-06",
        "source_file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_61203_54241efe4dfe.pdf",
        "sha256": "54241efe4dfe5a2f99da7f73874bf911c9f0a4035a761621d21ad02fa8f96dbf",
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/17096314/common",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.АД47.В.01270/24",
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "issue_date": "2024-09-05",
        "expire_date": "2029-09-04",
        "source_file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_61203_ea2971514733.pdf",
        "sha256": "ea29715147336b29e3401bd86253c7e54c3e7e32a65560ba2c8379c1aebbca45",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3491666/baseInfo",
    },
}
ALLOWED_TNVED = {"8539229000", "8539221000"}


def norm_number(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def code_values(values: list[object]) -> list[str]:
    return sorted({str(value).split(" - ", 1)[0].strip() for value in values if str(value).strip()})


def norm_text(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def attr_values(row: dict, ident: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip() for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def wb_tnved(card: dict) -> list[str]:
    values = []
    for characteristic in card.get("characteristics") or []:
        name = "".join(str(characteristic.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            value = characteristic.get("value")
            values.extend(value if isinstance(value, list) else [value])
    return code_values(values)


def is_current_approved(record: dict, today: str) -> bool:
    return (record.get("status_code") == "approved"
            and str(record.get("issue_date") or "")[:10] <= today
            and today <= str(record.get("expire_date") or "")[:10]
            and bool(str(record.get("expire_date") or "")[:10]))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists_inspect_first")
    if not SNAPSHOT.exists() or not ADDENDUM.exists():
        raise RuntimeError("baseline_or_postwrite_addendum_missing")
    for doc in DOCS.values():
        if hashlib.sha256(doc["source_file"].read_bytes()).hexdigest() != doc["sha256"]:
            raise RuntimeError("source_hash_mismatch:" + doc["number"])

    assignments: dict[str, dict[str, dict]] = {key: {} for key in DOCS}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            for key, spec in DOCS.items():
                if (row.get("Номер/название документа") != spec["number"]
                        or row.get("Применимость") != "Подтверждено источником"
                        or row.get("Статус покрытия артикула") != "Есть официальный документ"):
                    continue
                raw = json.loads(row.get("Исходная запись JSON") or "{}")
                if (raw.get("document_status") != "Действует"
                        or raw.get("official_fsa_registry_url", "").rstrip("/") != spec["registry_url"].removesuffix("/common").removesuffix("/baseInfo")):
                    raise RuntimeError("source_assignment_status_or_registry_conflict:" + str(row.get("Артикул продавца")))
                offer = str(row.get("Артикул продавца") or "").strip()
                if not offer or offer in assignments[key]:
                    raise RuntimeError("duplicate_or_empty_offer_assignment:" + key)
                assignments[key][offer] = {"row": row, "source": raw}

    if not assignments["declaration"] or set(assignments["declaration"]) != set(assignments["certificate"]):
        raise RuntimeError("document_target_sets_do_not_match")
    offers = sorted(assignments["declaration"])
    if len(offers) != 24:
        raise RuntimeError("unexpected_target_count:" + str(len(offers)))

    snapshot = json.loads(SNAPSHOT.read_text())
    if not snapshot.get("complete") or not all(snapshot.get(k, {}).get("complete") is True for k in
                                                   ("ozon_products", "ozon_certificates", "wb_catalog", "wb_trash")):
        raise RuntimeError("baseline_snapshot_incomplete")
    postwrite = json.loads(ADDENDUM.read_text())
    covered_before: set[str] = set()
    product_by_identity = {(str(p.get("product_id")), str(p.get("sku"))): p
                           for p in snapshot["ozon_products"]["products"]}
    for record in snapshot["ozon_certificates"]["certificates"]:
        if not is_current_approved(record, "2026-10-22"):
            continue
        for binding in record.get("live_bindings") or []:
            if binding.get("product_status_code") == "approved":
                product = product_by_identity.get((str(binding.get("product_id")), str(binding.get("sku"))))
                if product:
                    covered_before.add(str(product.get("offer_id")))
    overlap = {}
    for item in postwrite.get("post_snapshot_writes", []):
        serialized = json.dumps(item, ensure_ascii=False)
        matched = sorted(offer for offer in offers if offer in serialized)
        if matched:
            overlap[str(item.get("document_number") or item.get("source_group") or "unknown")] = matched

    sys.path.insert(0, str(API))
    from api_client import Client, now

    client = Client()
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    pmap: dict[str, list[dict]] = collections.defaultdict(list)
    amap: dict[str, list[dict]] = collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id"))].append(row)
    for row in attrs:
        amap[str(row.get("offer_id"))].append(row)
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("fresh_ozon_target_set_incomplete")

    all_records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        all_records.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_list_page_limit")

    target_rows = []
    offer_to_product: dict[str, tuple[str, str]] = {}
    for offer in offers:
        p, a = pmap[offer][0], amap[offer][0]
        product_id, sku = str(p.get("product_id") or p.get("id")), str(p.get("sku"))
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            conflicts = ["ozon_identity_not_unique"]
        else:
            conflicts = []
        brand = attr_values(a, "85")
        tnved = code_values(attr_values(a, "22232"))
        article = offer.split("-", 1)[0]
        source = assignments["declaration"][offer]["source"]
        official_heading = str(source.get("provider_exact_product_heading") or "")
        if p.get("is_archived") is not False:
            conflicts.append("ozon_archived_or_unknown")
        if brand != ["Navigator"]:
            conflicts.append("ozon_brand_mismatch")
        if article not in official_heading.replace(" ", ""):
            conflicts.append("official_product_article_not_exact")
        tnved_in_fsa_scope = bool(tnved and set(tnved) <= ALLOWED_TNVED)
        if not (article in norm_text(p.get("name"))):
            conflicts.append("ozon_product_article_not_visible_in_live_name")
        if offer in covered_before:
            conflicts.append("already_current_approved_covered_in_baseline")
        if overlap:
            conflicts.append("post_snapshot_write_overlap_requires_review")
        offer_to_product[offer] = (product_id, sku)
        target_rows.append({"offer_id": offer, "product_id": product_id, "sku": sku,
                            "live_name": p.get("name"), "brand_values": brand, "tnved": tnved,
                            "tnved_in_fsa_scope": tnved_in_fsa_scope,
                            "baseline_current_approved_coverage": offer in covered_before,
                            "official_product_heading": official_heading,
                            "eligible": not conflicts, "conflicts": conflicts})

    ozon_records: dict[str, list[dict]] = {}
    for key, spec in DOCS.items():
        matches = [r for r in all_records if norm_number(r.get("certificate_number")) == norm_number(spec["number"])]
        if len(matches) > 1:
            raise RuntimeError("duplicate_ozon_document_records:" + spec["number"])
        ozon_records[key] = matches
    ozon_targets_by_doc = {}
    for key, spec in DOCS.items():
        rec = ozon_records[key][0] if ozon_records[key] else None
        if rec and (rec.get("type_code") != spec["type_code"]
                    or str(rec.get("issue_date") or "")[:10] != spec["issue_date"]
                    or str(rec.get("expire_date") or "")[:10] != spec["expire_date"]):
            raise RuntimeError("existing_ozon_record_metadata_conflict:" + spec["number"])
        existing = client.ozon_bindings(rec["certificate_id"]) if rec else []
        by_product = collections.defaultdict(list)
        for binding in existing:
            by_product[(str(binding.get("product_id") or ""), str(binding.get("sku") or ""))].append(binding)
        details = []
        for offer in offers:
            product_id, sku = offer_to_product[offer]
            found = by_product[(product_id, sku)]
            details.append({"offer_id": offer, "exact_binding_count": len(found),
                            "binding_statuses": [b.get("product_status_code") for b in found]})
        ozon_targets_by_doc[key] = {"certificate_id": rec.get("certificate_id") if rec else None,
                                    "record_status": rec.get("status_code") if rec else None,
                                    "exact_bindings": sum(x["exact_binding_count"] == 1 for x in details),
                                    "targets": details}

    wb_targets = []
    for offer in offers:
        cards = client.wb_cards(offer)
        exact_cards = [card for card in cards if str(card.get("vendorCode") or "") == offer]
        conflicts = []
        if len(exact_cards) != 1:
            conflicts.append("wb_exact_card_count_" + str(len(exact_cards)))
            card = exact_cards[0] if len(exact_cards) == 1 else {}
        else:
            card = exact_cards[0]
        brand = str(card.get("brand") or "")
        tnved = wb_tnved(card)
        if card and brand.casefold() != "navigator":
            conflicts.append("wb_brand_mismatch")
        tnved_in_fsa_scope = bool(tnved and set(tnved) <= ALLOWED_TNVED)
        if card and not (offer.split("-", 1)[0] in norm_text(card.get("title"))):
            conflicts.append("wb_product_article_not_visible_in_live_title")
        documents = ((card.get("documents") or {}).get("items") or []) if card else []
        doc_status = {}
        for key, spec in DOCS.items():
            same = [d for d in documents if norm_number(d.get("number")) == norm_number(spec["number"])]
            exact = [d for d in same if str(d.get("type")) == str(spec["wb_type"])
                     and str(d.get("startDate") or "")[:10] == spec["issue_date"]
                     and str(d.get("endDate") or "")[:10] == spec["expire_date"]
                     and d.get("isEndless") is False]
            if same and len(exact) != 1:
                conflicts.append("wb_existing_metadata_conflict:" + key)
            doc_status[key] = {"exact_count": len(exact), "verdict": (exact[0].get("verdict") if exact else None)}
        wb_targets.append({"offer_id": offer, "nmID": str(card.get("nmID")) if card else None,
                           "brand": brand, "title": card.get("title") if card else None,
                           "tnved": tnved, "tnved_in_fsa_scope": tnved_in_fsa_scope,
                           "documents": doc_status, "eligible": not conflicts,
                           "conflicts": conflicts})

    result = {
        "checked_at_utc": now(), "read_only": True, "brand": "Navigator", "target_count": len(offers),
        "documents": {key: {k: str(v) if isinstance(v, pathlib.Path) else v
                            for k, v in spec.items() if k != "source_file"}
                      | {"source_file": str(spec["source_file"]),
                         "source_sha256_matches": True,
                         "ozon_existing_record": ozon_records[key][0] if ozon_records[key] else None,
                         "ozon_readback": ozon_targets_by_doc[key]}
                      for key, spec in DOCS.items()},
        "official_registry_verification": {
            "declaration": {"status": "Действует", "issue_date": "2022-10-07", "expiry_date": "2027-10-06",
                            "product_scope": "Лампы накаливания, цоколи E14/E27, Navigator, серия NI; ТР ЕАЭС 037/2016.",
                            "url": DOCS["declaration"]["registry_url"]},
            "certificate": {"status": "Действует", "issue_date": "2024-09-05", "expiry_date": "2029-09-04",
                            "product_scope": "Navigator NI incandescent models; certificate product tab lists model codes from exact offer/article mappings; TN VED 8539229000 and 8539221000; TR CU 004/2011.",
                            "url": DOCS["certificate"]["registry_url"]},
        },
        "baseline_snapshot_checked_at": snapshot["updated_at"],
        "post_snapshot_write_overlap": overlap,
        "ozon_target_summary": {"eligible": sum(x["eligible"] for x in target_rows),
                                "already_current_approved_baseline": sum(x["baseline_current_approved_coverage"] for x in target_rows),
                                "tnved_mismatch_count": sum(not x["tnved_in_fsa_scope"] for x in target_rows),
                                "tnved_distribution": dict(collections.Counter(code for x in target_rows for code in x["tnved"]))},
        "ozon_targets": target_rows,
        "wb_target_summary": {"eligible": sum(x["eligible"] for x in wb_targets),
                              "tnved_mismatch_count": sum(not x["tnved_in_fsa_scope"] for x in wb_targets),
                              "tnved_distribution": dict(collections.Counter(code for x in wb_targets for code in x["tnved"]))},
        "wb_targets": wb_targets,
        "local_source_deleted": False,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"checked_at_utc": result["checked_at_utc"], "target_count": result["target_count"],
                      "ozon_target_summary": result["ozon_target_summary"],
                      "wb_target_summary": result["wb_target_summary"],
                      "ozon_records": {k: {x: v for x, v in r.items() if x != "targets"}
                                       for k, r in ozon_targets_by_doc.items()},
                      "post_snapshot_write_overlap": overlap,
                      "ozon_conflict_counts": dict(collections.Counter(c for x in target_rows for c in x["conflicts"])),
                      "wb_conflict_counts": dict(collections.Counter(c for x in wb_targets for c in x["conflicts"]))},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
