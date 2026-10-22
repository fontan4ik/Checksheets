#!/usr/bin/env python3
"""Fresh read-only preflight for the two Gauss Elementary Promo declarations."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
EDGES = HERE / "all_confirmed_source_assignments_live_20261022.csv"
OUT = HERE / "gauss_elementary_declarations_live_preflight_v2_20261022.json"
TARGETS = {
    "613100150P-2": {"article": "613100150P", "wattage": 150},
    "613100200P-2": {"article": "613100200P", "wattage": 200},
}
DOCS = [
    {
        "number": "ЕАЭС N RU Д-CN.РА05.В.08477/23",
        "normalized_number": "RUДCNРА05В0847723",
        "fsa_record_id": "17832680",
        "type_code": "declaration",
        "issue_date": "2023-06-30",
        "expire_date": "2028-06-29",
        "tnved": "9405420012",
        "technical_regulations": ["ТР ТС 004/2011", "ТР ТС 020/2011"],
        "production_from": "2023-03",
        "pdf_relpath": "output_to_user/certificates/group_1/documents/gauss/33aab613ec7c4812c82c1f91.pdf",
        "pdf_sha256": "15289d16092b1dc56edcdc1fc5bec5affe6bde1bde771fb844d5c6ca6c542eec",
        "qr_record_id": "17832680",
    },
    {
        "number": "ЕАЭС N RU Д-CN.РА05.В.08558/23",
        "normalized_number": "RUДCNРА05В0855823",
        "fsa_record_id": "17832766",
        "type_code": "declaration",
        "issue_date": "2023-06-30",
        "expire_date": "2028-06-29",
        "tnved": "9405420012",
        "technical_regulations": ["ТР ЕАЭС 037/2016"],
        "production_from": "2023-03",
        "pdf_relpath": "output_to_user/certificates/group_1/documents/gauss/a9ec13b68073ed632c9e564b.pdf",
        "pdf_sha256": "26f46d687945f4874b13045d40474c8966cd9c5a781a0267db179100e7a7973f",
        "qr_record_id": "17832766",
    },
]


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def codes(values: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(ident)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def wb_tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        label = re.sub(r"\s+", "", str(char.get("name") or "").casefold()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            value = char.get("value")
            values.extend(value if isinstance(value, list) else [value])
    return codes([str(x) for x in values if x is not None])


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"preflight_artifact_exists_inspect_first:{OUT}")
    for doc in DOCS:
        path = ROOT / doc["pdf_relpath"]
        if not path.is_file():
            raise RuntimeError(f"source_pdf_missing:{path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["pdf_sha256"]:
            raise RuntimeError(f"source_pdf_hash_mismatch:{path}")

    expected = {}
    with EDGES.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            offer = str(row.get("offer_id") or "")
            if offer not in TARGETS:
                continue
            current = {key: str(row.get(key) or "") for key in
                       ("ozon_product_id", "ozon_sku", "wb_nmID")}
            if offer in expected and expected[offer] != current:
                raise RuntimeError(f"baseline_identity_conflict:{offer}")
            expected[offer] = current
    if set(expected) != set(TARGETS):
        raise RuntimeError(f"baseline_target_set_incomplete:{sorted(expected)}")

    sys.path.insert(0, str(PILOT))
    from api_client import Client, now  # noqa: E402

    client = Client()
    offers = sorted(TARGETS)
    pbody = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = pbody.get("items") or pbody.get("result", {}).get("items") or []
    abody = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)})
    attrs = abody.get("result") or abody.get("items") or []
    pm = collections.defaultdict(list)
    am = collections.defaultdict(list)
    for product in products:
        pm[str(product.get("offer_id") or "")].append(product)
    for attr in attrs:
        am[str(attr.get("offer_id") or "")].append(attr)
    if set(pm) != set(offers) or set(am) != set(offers):
        raise RuntimeError("ozon_live_target_set_incomplete")

    certs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        certs.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_page_limit")

    ozon_targets = []
    by_product_id = {}
    for offer in offers:
        product = pm[offer][0]
        attr = am[offer][0]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        brand = attr_values(attr, 85)
        tnved = codes(attr_values(attr, 22232))
        article = TARGETS[offer]["article"]
        conflicts = []
        if len(pm[offer]) != 1 or len(am[offer]) != 1:
            conflicts.append("ozon_identity_not_unique")
        if product_id != expected[offer]["ozon_product_id"] or sku != expected[offer]["ozon_sku"]:
            conflicts.append("ozon_identity_changed")
        if product.get("is_archived") is not False:
            conflicts.append("ozon_archived_or_unknown")
        if brand != ["Gauss"]:
            conflicts.append("ozon_brand_mismatch")
        live_name = str(product.get("name") or "").casefold()
        article_in_offer = offer.rsplit("-", 1)[0].casefold() == article.casefold()
        wattage_in_name = f"{TARGETS[offer]['wattage']}w" in live_name.replace(" ", "")
        elementary_in_name = "elementary" in live_name
        if not (article_in_offer and wattage_in_name and elementary_in_name):
            conflicts.append("ozon_article_model_or_wattage_scope_not_exact")
        if tnved != ["9405420012"]:
            conflicts.append("ozon_tnved_not_exact")
        row = {"offer_id": offer, "article": article, "product_id": product_id, "sku": sku,
               "name": product.get("name"), "brand_values": brand, "tnved_codes": tnved,
               "is_archived": product.get("is_archived"), "eligible": not conflicts,
               "conflicts": conflicts}
        ozon_targets.append(row)
        by_product_id[product_id] = offer

    wb_targets = []
    for offer in offers:
        cards = client.wb_cards(offer)
        conflicts = []
        card = cards[0] if len(cards) == 1 else {}
        if len(cards) != 1:
            conflicts.append(f"wb_exact_card_count_{len(cards)}")
        if card and str(card.get("nmID") or "") != expected[offer]["wb_nmID"]:
            conflicts.append("wb_nmid_changed")
        if card and str(card.get("vendorCode") or "") != offer:
            conflicts.append("wb_vendor_code_mismatch")
        if card and str(card.get("brand") or "").casefold() != "gauss":
            conflicts.append("wb_brand_mismatch")
        article = TARGETS[offer]["article"]
        title = str(card.get("title") or "").casefold()
        article_in_vendor_code = str(card.get("vendorCode") or "").rsplit("-", 1)[0].casefold() == article.casefold()
        wattage_in_title = f"{TARGETS[offer]['wattage']}w" in title.replace(" ", "")
        if card and not (article_in_vendor_code and wattage_in_title):
            conflicts.append("wb_article_or_wattage_scope_not_exact")
        tnved = wb_tnved(card) if card else []
        if tnved != ["9405420012"]:
            conflicts.append("wb_tnved_not_exact")
        docs = ((card.get("documents") or {}).get("items") or []) if card else []
        existing = []
        for doc in DOCS:
            same = [item for item in docs if norm(item.get("number")) == norm(doc["number"])]
            exact = [item for item in same if int(item.get("type") or 0) == 2
                     and str(item.get("startDate") or "")[:10] == doc["issue_date"]
                     and str(item.get("endDate") or "")[:10] == doc["expire_date"]]
            existing.append({"number": doc["number"], "same_number_count": len(same),
                             "exact_declaration_count": len(exact),
                             "same_number_rows": [{k: item.get(k) for k in
                                                   ("type", "number", "startDate", "endDate", "verdict")}
                                                  for item in same]})
            if same and len(exact) != 1:
                conflicts.append("wb_existing_number_metadata_conflict:" + doc["number"])
            if len(exact) > 1:
                conflicts.append("wb_duplicate_exact_document:" + doc["number"])
        wb_targets.append({"offer_id": offer, "article": article, "nmID": str(card.get("nmID") or "") if card else None,
                           "vendorCode": card.get("vendorCode") if card else None,
                           "brand": card.get("brand") if card else None, "title": card.get("title") if card else None,
                           "tnved_codes": tnved,
                           "excludeDocuments": (card.get("documents") or {}).get("excludeDocuments") if card else None,
                           "existing_target_documents": existing, "eligible": not conflicts,
                           "conflicts": conflicts})

    record_matches = []
    for doc in DOCS:
        matches = [row for row in certs if norm(row.get("certificate_number")) == norm(doc["number"])]
        if len(matches) > 1:
            raise RuntimeError("duplicate_ozon_record:" + doc["number"])
        record = matches[0] if matches else None
        bindings = client.ozon_bindings(record["certificate_id"]) if record else []
        relevant = []
        for binding in bindings:
            offer = by_product_id.get(str(binding.get("product_id") or ""))
            if offer:
                relevant.append({"offer_id": offer, "product_id": str(binding.get("product_id")),
                                 "sku": str(binding.get("sku")),
                                 "product_status_code": binding.get("product_status_code")})
        record_matches.append({
            "number": doc["number"], "type_code": record.get("type_code") if record else None,
            "certificate_id": str(record.get("certificate_id")) if record else None,
            "status_code": record.get("status_code") if record else None,
            "issue_date": str(record.get("issue_date") or "")[:10] if record else None,
            "expire_date": str(record.get("expire_date") or "")[:10] if record else None,
            "all_bindings_count": len(bindings), "target_bindings": relevant,
            "record_metadata_exact": bool(record and record.get("type_code") == "declaration"
                                           and str(record.get("issue_date") or "")[:10] == doc["issue_date"]
                                           and str(record.get("expire_date") or "")[:10] == doc["expire_date"]),
        })

    result = {
        "checked_at_utc": now(), "read_only": True,
        "document_source_mapping_corrected_from_assignment_metadata": True,
        "source_mapping_note": "Local PDF QR identifiers and printed declarations determine the upload mapping; assignment.csv row metadata swaps the two filenames/URLs.",
        "fsa_records": [{k: doc[k] for k in ("number", "fsa_record_id", "issue_date", "expire_date", "tnved",
                                               "technical_regulations", "production_from", "pdf_relpath",
                                               "pdf_sha256", "qr_record_id")} for doc in DOCS],
        "scope_evidence": {
            "manufacturer_product_pages": {
                "613100150P": "https://gauss.ru/catalog/product/prozhektor-gauss-elementary-150vt-12750lm-6500k-ip65",
                "613100200P": "https://gauss.ru/catalog/product/prozhektor-gauss-elementary-200vt-17000lm-6500k-ip65",
            },
            "visually_ocr_verified_article_codes_in_both_declarations": ["613100150P", "613100200P"],
            "fsa_product_scope_for_both_records": "Gauss Elementary Promo LED floodlights; articles 613100150P and 613100200P; TN VED 9405420012.",
            "fsa_production_cutoff_for_both_records": "Serial products manufactured from 2023-03.",
        },
        "baseline_identity": expected,
        "ozon": {"targets": ozon_targets,
                 "all_targets_eligible": len(ozon_targets) == 2 and all(x["eligible"] for x in ozon_targets),
                 "records": record_matches},
        "wb": {"targets": wb_targets,
               "all_targets_eligible": len(wb_targets) == 2 and all(x["eligible"] for x in wb_targets)},
        "safe_to_write": (len(ozon_targets) == 2 and len(wb_targets) == 2
                          and all(x["eligible"] for x in ozon_targets)
                          and all(x["eligible"] for x in wb_targets)
                          and all(not x["same_number_count"] or x["exact_declaration_count"] == 1
                                  for row in wb_targets for x in row["existing_target_documents"])
                          and all(x["certificate_id"] is None
                                  or (x["record_metadata_exact"] and x["status_code"] in {"approved", "under_review"})
                                  for x in record_matches)),
        "local_source_files_deleted": False,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": result["checked_at_utc"],
                      "safe_to_write": result["safe_to_write"],
                      "ozon_eligible": sum(x["eligible"] for x in ozon_targets),
                      "wb_eligible": sum(x["eligible"] for x in wb_targets),
                      "ozon_records": [{k: x.get(k) for k in ("number", "certificate_id", "status_code",
                                                                  "record_metadata_exact", "target_bindings")}
                                       for x in record_matches],
                      "ozon_targets": [{k: x.get(k) for k in ("offer_id", "product_id", "sku", "brand_values",
                                                                  "tnved_codes", "eligible", "conflicts")}
                                       for x in ozon_targets],
                      "wb_targets": [{k: x.get(k) for k in ("offer_id", "nmID", "brand", "tnved_codes",
                                                               "eligible", "conflicts", "existing_target_documents")}
                                     for x in wb_targets]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
