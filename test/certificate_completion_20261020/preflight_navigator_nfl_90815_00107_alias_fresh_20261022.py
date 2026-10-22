#!/usr/bin/env python3
"""Fresh read-only cross-platform preflight for Navigator NFL docs 90815/24 and 00107/24."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "navigator_nfl_90815_00107_alias_fresh_preflight_20261022.json"
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-RU.РА11.В.90815/24",
        "type_code": "declaration",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14150_fb47c7e7dab0.pdf",
        "sha256": "fb47c7e7dab06d12e4560432589f86a8303cca3431ada97a4c0e00aea0763fc5",
        "issue_date": "2024-12-27",
        "expire_date": "2029-12-25",
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/19764839/common",
        "allowed_tnved": {"9405420012"},
        "provider_url": "http://www.batteryteam.ru/sert/1556.pdf",
    },
    "certificate": {
        "number": "ЕАЭС RU С-RU.НВ28.В.00107/24",
        "type_code": "certificate_of_conformity",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf",
        "sha256": "f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e",
        "issue_date": "2024-12-24",
        "expire_date": "2029-12-23",
        "fsa_url": "https://pub.fsa.gov.ru/rss/certificate/view/3544212/baseInfo",
        "allowed_tnved": {"9405420012"},
        "provider_url": "http://www.batteryteam.ru/sert/1555.pdf",
    },
}


def codes(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def card_codes(card: dict) -> list[str]:
    values = []
    for c in card.get("characteristics") or []:
        label = "".join(str(c.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = c.get("value")
        values.extend(raw if isinstance(raw, list) else [raw])
    return codes(values)


def date_matches(doc: dict, info: dict) -> bool:
    return (str(doc.get("startDate", ""))[:10] == info["issue_date"]
            and str(doc.get("endDate", ""))[:10] == info["expire_date"])


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_first")
    if not SNAPSHOT.is_file() or not ASSIGNMENTS.is_file():
        raise RuntimeError("snapshot_or_assignments_missing")
    for key, info in DOCS.items():
        if not info["file"].is_file() or hashlib.sha256(info["file"].read_bytes()).hexdigest() != info["sha256"]:
            raise RuntimeError(f"official_pdf_missing_or_hash_mismatch:{key}")

    source_rows = {key: {} for key in DOCS}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("Применимость") != "Подтверждено источником" or row.get("Статус покрытия артикула") != "Есть официальный документ":
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer:
                continue
            for key, info in DOCS.items():
                if norm_number(row.get("Номер/название документа")) == norm_number(info["number"]):
                    parsed = json.loads(row.get("Исходная запись JSON") or "{}")
                    registry_url = info["fsa_url"].replace("/common", "").replace("/baseInfo", "")
                    if (parsed.get("document_number") != info["number"]
                            or parsed.get("document_status") != "Действует"
                            or parsed.get("sha256") != info["sha256"]
                            or parsed.get("official_fsa_registry_url") != registry_url
                            or parsed.get("provider_exact_product_heading") is None):
                        raise RuntimeError(f"source_assignment_evidence_conflict:{key}:{offer}")
                    prior = source_rows[key].get(offer)
                    if prior and prior.get("sha256") != parsed.get("sha256"):
                        raise RuntimeError(f"duplicate_assignment_file_conflict:{key}:{offer}")
                    source_rows[key][offer] = {
                        "offer_id": offer,
                        "provider_exact_product_heading": parsed["provider_exact_product_heading"],
                        "official_search_result": parsed.get("official_search_result"),
                        "official_product_page_url": parsed.get("official_product_page_url"),
                        "source_pdf_url": parsed.get("pdf_source_url"),
                        "sha256": parsed.get("sha256"),
                    }

    common_offers = set(source_rows["declaration"]) & set(source_rows["certificate"])
    declaration_only = sorted(set(source_rows["declaration"]) - common_offers)
    certificate_only = sorted(set(source_rows["certificate"]) - common_offers)
    if len(common_offers) != 11 or declaration_only or certificate_only:
        raise RuntimeError(f"source_offer_set_changed:common={len(common_offers)},declaration_only={len(declaration_only)},certificate_only={len(certificate_only)}")
    targets = sorted(common_offers)

    snapshot = json.loads(SNAPSHOT.read_text())
    if not all(snapshot.get(k, {}).get("complete") is True for k in
               ("ozon_products", "ozon_certificates", "wb_catalog", "wb_trash")):
        raise RuntimeError("marketplace_snapshot_incomplete")
    products_by_sku = {str(p.get("sku")): p for p in snapshot["ozon_products"]["products"] if p.get("sku")}
    covered_product_ids = set()
    for record in snapshot["ozon_certificates"]["certificates"]:
        if record.get("status_code") != "approved" or not str(record.get("expire_date") or "")[:10]:
            continue
        if str(record.get("expire_date") or "")[:10] < "2026-10-22":
            continue
        for b in record.get("live_bindings") or []:
            p = products_by_sku.get(str(b.get("sku") or ""))
            if b.get("product_status_code") == "approved" and p and str(p.get("product_id")) == str(b.get("product_id")):
                covered_product_ids.add(str(p.get("product_id")))
    ozon_snapshot_by_offer = collections.defaultdict(list)
    for p in snapshot["ozon_products"]["products"]:
        if str(p.get("offer_id") or "") in common_offers:
            ozon_snapshot_by_offer[str(p.get("offer_id"))].append(p)
    wb_by_offer = collections.defaultdict(list)

    c = Client()
    for index, offer in enumerate(targets, start=1):
        wb_by_offer[offer].extend(c.wb_cards(offer))
        if index % 10 == 0 or index == len(targets):
            print(json.dumps({"live_wb_cards_checked": index, "total": len(targets)}, ensure_ascii=False), flush=True)
    fresh_products, fresh_attrs = [], []
    for start in range(0, len(targets), 100):
        batch = targets[start:start + 100]
        fresh_products.extend(c.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        fresh_attrs.extend(c.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    products_map = collections.defaultdict(list)
    attrs_map = collections.defaultdict(list)
    for p in fresh_products:
        products_map[str(p.get("offer_id"))].append(p)
    for a in fresh_attrs:
        attrs_map[str(a.get("offer_id"))].append(a)
    if set(products_map) != common_offers or set(attrs_map) != common_offers:
        raise RuntimeError("fresh_ozon_offer_response_set_incomplete")

    certificates = []
    for page in range(1, 101):
        response = c.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = response.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("fresh_ozon_certificate_list_incomplete")
        certificates.extend(batch)
        if page >= int(response.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_page_limit")
    records = {}
    for key, info in DOCS.items():
        matches = [r for r in certificates if norm_number(r.get("certificate_number")) == norm_number(info["number"])]
        records[key] = [{k: r.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")} for r in matches]

    rows = []
    for offer in targets:
        if len(products_map[offer]) != 1 or len(attrs_map[offer]) != 1 or len(ozon_snapshot_by_offer[offer]) != 1:
            rows.append({"offer_id": offer, "ozon_eligible": False, "ozon_conflicts": ["product_or_snapshot_duplicate"],
                         "wb_eligible": False, "wb_conflicts": ["not_checked_due_to_ozon_identity_conflict"],
                         "source_assignment_declaration": source_rows["declaration"][offer],
                         "source_assignment_certificate": source_rows["certificate"][offer]})
            continue
        p, attrrow = products_map[offer][0], attrs_map[offer][0]
        snap_product = ozon_snapshot_by_offer[offer][0]
        attrs = {str(x.get("id")): x for x in attrrow.get("attributes") or []}
        attrvals = {k: [str(v.get("value") or "").strip() for v in (attrs.get(k) or {}).get("values") or []
                        if str(v.get("value") or "").strip()] for k in ("85", "22232")}
        tnved = codes(attrvals["22232"])
        ozon_conflicts = []
        if str(p.get("offer_id")) != offer or p.get("is_archived") is not False:
            ozon_conflicts.append("offer_or_archived_identity_conflict")
        if str(p.get("product_id") or p.get("id")) != str(snap_product.get("product_id")) or str(p.get("sku")) != str(snap_product.get("sku")):
            ozon_conflicts.append("product_id_or_sku_changed_since_snapshot")
        if "navigator" not in str(p.get("name") or "").casefold():
            ozon_conflicts.append("brand_missing_from_product_name")
        if not tnved or not set(tnved) <= DOCS["declaration"]["allowed_tnved"]:
            ozon_conflicts.append("ozon_tnved_unconfirmed_or_out_of_scope")
        covered_now = str(p.get("product_id") or p.get("id")) in covered_product_ids
        card_rows = wb_by_offer[offer]
        wb_conflicts = []
        card = card_rows[0] if len(card_rows) == 1 else {}
        if len(card_rows) != 1:
            wb_conflicts.append(f"wb_exact_card_count_{len(card_rows)}")
        wb_tnved = card_codes(card) if card else []
        if card and str(card.get("vendorCode")) != offer:
            wb_conflicts.append("wb_vendor_code_mismatch")
        if card and str(card.get("brand") or "").strip().casefold() not in {"navigator", "navigator group"}:
            wb_conflicts.append("wb_brand_mismatch")
        if card and (not wb_tnved or not set(wb_tnved) <= DOCS["declaration"]["allowed_tnved"]):
            wb_conflicts.append("wb_tnved_unconfirmed_or_out_of_scope")
        wb_doc_result = {}
        if card:
            for key, info in DOCS.items():
                expected_type = 2 if key == "declaration" else 1
                same_number = [d for d in ((card.get("documents") or {}).get("items") or [])
                               if norm_number(d.get("number")) == norm_number(info["number"])]
                exact = [d for d in same_number if int(d.get("type") or 0) == expected_type and date_matches(d, info)]
                valid = [d for d in exact if (d.get("verdict") or {}).get("verified") is True
                         and (d.get("verdict") or {}).get("status") == 1
                         and (d.get("verdict") or {}).get("reason") == "valid"]
                wb_doc_result[key] = {"exact_count": len(exact), "valid_count": len(valid),
                                      "documents": [{k: x.get(k) for k in ("type", "number", "startDate", "endDate", "verdict")} for x in exact]}
        else:
            wb_doc_result = {key: {"exact_count": 0, "valid_count": 0, "documents": []} for key in DOCS}
        rows.append({
            "offer_id": offer, "product_id": str(p.get("product_id") or p.get("id")), "sku": str(p.get("sku")),
            "product_name": p.get("name"), "brand_attribute_values": attrvals["85"],
            "ozon_tnved": tnved, "current_approved_document_before_new_writes": covered_now,
            "ozon_eligible": not ozon_conflicts, "ozon_conflicts": ozon_conflicts,
            "source_assignment_declaration": source_rows["declaration"][offer],
            "source_assignment_certificate": source_rows["certificate"][offer],
            "wb_nmID": str(card.get("nmID")) if card else None, "wb_title": card.get("title") if card else None,
            "wb_tnved": wb_tnved, "wb_eligible": not wb_conflicts, "wb_conflicts": wb_conflicts,
            "wb_documents": wb_doc_result,
        })
    summary = {
        "checked_at_utc": now(), "read_only": True, "snapshot_checked_at": {
            k: snapshot[k].get("checked_at") for k in ("ozon_products", "ozon_certificates", "wb_catalog")},
        "declaration_fsa_url": DOCS["declaration"]["fsa_url"],
        "certificate_fsa_url": DOCS["certificate"]["fsa_url"],
        "declaration_pdf_sha256": DOCS["declaration"]["sha256"],
        "certificate_pdf_sha256": DOCS["certificate"]["sha256"],
        "declaration_dates": [DOCS["declaration"]["issue_date"], DOCS["declaration"]["expire_date"]],
        "certificate_dates": [DOCS["certificate"]["issue_date"], DOCS["certificate"]["expire_date"]],
        "ozon_record_matches": records,
        "target_count": len(rows),
        "target_products_already_covered_by_any_current_approved_document": sum(x["current_approved_document_before_new_writes"] for x in rows),
        "target_products_without_any_current_approved_document": sum(not x["current_approved_document_before_new_writes"] for x in rows),
        "ozon_eligible_targets": sum(x.get("ozon_eligible") is True for x in rows),
        "ozon_skipped_targets": [x["offer_id"] for x in rows if x.get("ozon_eligible") is not True],
        "wb_eligible_targets": sum(x.get("wb_eligible") is True for x in rows),
        "wb_skipped_targets": [x["offer_id"] for x in rows if x.get("wb_eligible") is not True],
        "wb_declaration_valid": sum(x["wb_documents"]["declaration"]["valid_count"] == 1 for x in rows),
        "wb_certificate_valid": sum(x["wb_documents"]["certificate"]["valid_count"] == 1 for x in rows),
        "ozon_tnved_distribution": dict(collections.Counter(code for x in rows for code in x["ozon_tnved"])),
        "wb_tnved_distribution": dict(collections.Counter(code for x in rows for code in x["wb_tnved"])),
        "declaration_only_source_offers": declaration_only,
        "certificate_only_source_offers": certificate_only,
        "targets": rows,
        "local_source_files_deleted": False,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in (
        "checked_at_utc", "target_count", "target_products_already_covered_by_any_current_approved_document",
        "target_products_without_any_current_approved_document", "wb_declaration_valid", "wb_certificate_valid",
        "ozon_record_matches", "ozon_tnved_distribution", "wb_tnved_distribution")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
