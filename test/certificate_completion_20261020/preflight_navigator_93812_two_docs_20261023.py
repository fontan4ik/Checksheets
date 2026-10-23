#!/usr/bin/env python3
"""Read-only live preflight for the exact Navigator 93812 pack variants."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "navigator_93812_two_docs_live_preflight_20261023.json"
OFFERS = {"93812-5", "93812-10"}
DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА11.В.08110/24",
        "type_code": "declaration",
        "wb_type": 2,
        "issue_date": "2024-12-02",
        "expire_date": "2029-12-01",
        "source_pdf": ROOT / "output_to_user/certificates/additional_search/brand_research/navigator/followup_2026_10_02/documents/originals/NAV_93812_declaration_2024_original.pdf",
        "source_sha256": "6281784d69c80c6fb396c095d4fafef82fad9771694f8b74510a7fafc2846fd2",
        "fsa_registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/19670009/common",
        "fsa_status_evidence": "FSA extract dated 2026-10-02 reports active through 2029-12-01; Ozon record is currently approved.",
        "tnved": {"8539520001", "8539520003", "8539520009"},
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.НВ93.В.03629/23",
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "issue_date": "2023-07-18",
        "expire_date": "2028-07-17",
        "source_pdf": ROOT / "output_to_user/certificates/additional_search/brand_research/navigator/followup_2026_10_02/documents/originals/NAV_93812_certificate_2023_original.pdf",
        "source_sha256": "3ff6e60fdd4ddac47a52ea19142c61f29f99d041510fb79c519ff70b2390add1",
        "fsa_registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3284481/baseInfo",
        "fsa_status_evidence": "Live FSA page read on 2026-10-23: active through 2028-07-17; product tab lists Navigator NLL and TN VED 8539520009.",
        "tnved": {"8539520001", "8539520003", "8539520009"},
    },
}
CONFIRMED = {"Подтверждено статусом покрытия", "Подтверждено источником"}


def code_values(values: list[object]) -> set[str]:
    return {str(v or "").split(" - ", 1)[0].strip() for v in values
            if str(v or "").split(" - ", 1)[0].strip()}


def attr_values(row: dict, ident: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def wb_codes(card: dict) -> set[str]:
    values = []
    for row in card.get("characteristics") or []:
        name = "".join(str(row.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            value = row.get("value")
            values.extend(value if isinstance(value, list) else [value])
    return code_values(values)


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    assignments: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer not in OFFERS or row.get("Применимость") not in CONFIRMED:
                continue
            for name, doc in DOCS.items():
                if norm_number(row.get("Номер/название документа")) == norm_number(doc["number"]):
                    assignments[(name, offer)].append(row)
    if any(len(assignments[(doc, offer)]) != 1 for doc in DOCS for offer in OFFERS):
        raise RuntimeError("source_assignment_missing_or_ambiguous")
    for doc_name, doc in DOCS.items():
        if not doc["source_pdf"].is_file():
            raise RuntimeError("source_pdf_missing:" + doc_name)
        if hashlib.sha256(doc["source_pdf"].read_bytes()).hexdigest() != doc["source_sha256"]:
            raise RuntimeError("source_pdf_sha256_mismatch:" + doc_name)

    client = Client()
    records = list_certificates(client)
    product_rows, attribute_rows = [], []
    for offer in sorted(OFFERS):
        product_rows.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or [])
        attribute_rows.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": [offer]}, "limit": 1}).get("result") or [])
    by_offer_products: dict[str, list[dict]] = collections.defaultdict(list)
    by_offer_attrs: dict[str, list[dict]] = collections.defaultdict(list)
    for row in product_rows:
        by_offer_products[str(row.get("offer_id") or "")].append(row)
    for row in attribute_rows:
        by_offer_attrs[str(row.get("offer_id") or "")].append(row)
    if set(by_offer_products) != OFFERS or set(by_offer_attrs) != OFFERS:
        raise RuntimeError("ozon_current_target_set_incomplete")

    products = {}
    for offer in sorted(OFFERS):
        if len(by_offer_products[offer]) != 1 or len(by_offer_attrs[offer]) != 1:
            raise RuntimeError("ozon_target_identity_not_unique:" + offer)
        product, attrs = by_offer_products[offer][0], by_offer_attrs[offer][0]
        brand = attr_values(attrs, "85")
        tnved = code_values(attr_values(attrs, "22232"))
        if (product.get("is_archived") is not False or brand != ["Navigator"]
                or tnved != {"8539520009"}
                or "NLL-GX53-11-230-3K" not in str(product.get("name") or "")):
            raise RuntimeError("ozon_target_scope_changed:" + offer)
        products[offer] = {"offer_id": offer, "product_id": str(product.get("product_id") or product.get("id")),
                           "sku": str(product.get("sku") or ""), "name": product.get("name"),
                           "brand": brand, "tnved": sorted(tnved)}
        if not products[offer]["product_id"] or not products[offer]["sku"]:
            raise RuntimeError("ozon_target_id_or_sku_missing:" + offer)

    cards = {}
    for offer in sorted(OFFERS):
        result = client.wb_cards(offer)
        if len(result) != 1 or str(result[0].get("vendorCode") or "") != offer:
            raise RuntimeError("wb_target_card_missing_or_ambiguous:" + offer)
        card = result[0]
        if card.get("brand") != "Navigator" or wb_codes(card) != {"8539520009"}:
            raise RuntimeError("wb_target_scope_changed:" + offer)
        cards[offer] = card

    ozon_docs = {}
    for doc_name, doc in DOCS.items():
        matches = [c for c in records if norm_number(c.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) > 1:
            raise RuntimeError("ozon_duplicate_document_records:" + doc_name)
        record = matches[0] if matches else None
        if record and (record.get("type_code") != doc["type_code"]
                       or str(record.get("issue_date") or "")[:10] != doc["issue_date"]
                       or str(record.get("expire_date") or "")[:10] != doc["expire_date"]
                       or record.get("accordance_type_code") != "EAEU"):
            raise RuntimeError("ozon_record_metadata_conflict:" + doc_name)
        bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
        by_product = {str(x.get("product_id")): x for x in bindings}
        target_bindings = []
        for offer in sorted(OFFERS):
            product = products[offer]
            prior = by_product.get(product["product_id"])
            if prior and str(prior.get("sku")) != product["sku"]:
                raise RuntimeError("ozon_existing_binding_identity_conflict:" + offer)
            if prior and prior.get("product_status_code") == "declined":
                raise RuntimeError("ozon_existing_binding_declined:" + offer)
            target_bindings.append({"offer_id": offer, "product_id": product["product_id"], "sku": product["sku"],
                                    "present": bool(prior), "status": prior.get("product_status_code") if prior else None})
        outside = [x for x in bindings if str(x.get("product_id")) not in {p["product_id"] for p in products.values()}]
        # Existing records may legitimately contain other products. Record, but do not change them.
        ozon_docs[doc_name] = {"number": doc["number"], "record": record,
                               "current_binding_count": len(bindings), "target_bindings": target_bindings,
                               "outside_existing_binding_count": len(outside),
                               "missing_target_bindings": sum(not x["present"] for x in target_bindings)}

    desired = []
    wb_state = {}
    for doc_name, doc in DOCS.items():
        desired.append({"type": doc["wb_type"], "number": doc["number"],
                        "startDate": doc["issue_date"] + "T00:00:00Z",
                        "endDate": doc["expire_date"] + "T00:00:00Z", "isEndless": False})
    for offer, card in cards.items():
        prior = copy_documents(card)
        additions = []
        by_doc = {}
        for doc_name, doc in DOCS.items():
            matches = [x for x in prior if norm_number(x.get("number")) == norm_number(doc["number"])]
            if matches:
                if any(int(x.get("type") or 0) != doc["wb_type"]
                       or str(x.get("startDate") or "")[:10] != doc["issue_date"]
                       or str(x.get("endDate") or "")[:10] != doc["expire_date"] for x in matches):
                    raise RuntimeError("wb_existing_document_metadata_conflict:" + offer + ":" + doc_name)
                by_doc[doc_name] = {"present": True, "count": len(matches),
                                    "verdicts": [x.get("verdict") for x in matches]}
            else:
                by_doc[doc_name] = {"present": False, "count": 0}
                additions.append(next(x for x in desired if norm_number(x["number"]) == norm_number(doc["number"])))
        payload = merge_wb(card, additions) if additions else None
        wb_state[offer] = {"nmID": str(card.get("nmID")), "brand": card.get("brand"),
                           "tnved": sorted(wb_codes(card)), "documents": by_doc,
                           "new_document_count": len(additions), "payload": payload}

    out = {"checked_at_utc": now(), "read_only": True,
           "fsa_registry_checks": {name: {"url": doc["fsa_registry_url"], "status": "Действует",
                                          "issue_date": doc["issue_date"], "expire_date": doc["expire_date"],
                                          "tnved": sorted(doc["tnved"]), "evidence": doc["fsa_status_evidence"]}
                                   for name, doc in DOCS.items()},
           "target_count": len(OFFERS), "targets": list(products.values()),
           "source_assignments": {name: {offer: {"local_file": str(assignments[(name, offer)][0].get("Локальный файл")),
                                                       "sha256_actual": doc["source_sha256"],
                                                       "source_url": assignments[(name, offer)][0].get("URL документа"),
                                                       "scope_basis": assignments[(name, offer)][0].get("Основание сопоставления")}
                                                for offer in sorted(OFFERS)} for name, doc in DOCS.items()},
           "ozon": ozon_docs, "wb": wb_state,
           "no_writes_sent": True, "no_local_files_deleted": True}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "target_count": len(OFFERS),
                      "ozon": {k: {"record_id": (v["record"] or {}).get("certificate_id"),
                                  "status": (v["record"] or {}).get("status_code"),
                                  "missing_target_bindings": v["missing_target_bindings"]}
                               for k, v in ozon_docs.items()},
                      "wb": {k: {"nmID": v["nmID"], "missing_documents": v["new_document_count"]}
                             for k, v in wb_state.items()},
                      "no_writes_sent": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
