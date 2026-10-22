#!/usr/bin/env python3
"""Fresh exact-product and document-scope preflight for Jazzway PPC conformity documents."""
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
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "jazzway_power_connectors_preflight_20261022.json"
TNVED = "8536699008"
ISSUE = "2026-04-13"
EXPIRY = "2031-04-12"
DOCS = [
    {
        "key": "certificate_04539", "number": "ЕАЭС RU С-HK.СП28.В.04539/26",
        "type_code": "certificate_of_conformity", "ozon_create_type": "CERTIFICATE_OF_CONFORMITY", "wb_type": 1,
        "source_file": "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_ac8cb1fa1d.pdf",
        "sha256": "2b727485f9e87b0a78492d4afec02b80d5e2741f98740b8c81f810dfb4d602c9",
        "source_url": "https://jazz-way.com/docs/sertifikaty/razemy-silovye-vilki-rozetki-ss-tr-ts-004-12.04.2031.pdf",
    },
    {
        "key": "declaration_00949", "number": "ЕАЭС N RU Д-HK.РА03.В.00949/26",
        "type_code": "declaration", "ozon_create_type": "DECLARATION", "wb_type": 2,
        "source_file": "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_e936b8e8f7.pdf",
        "sha256": "588aa99508418e00fbfb93dbca31ff5dbbe7da40d298a0d5231a946037366c28",
        "source_url": "https://jazz-way.com/docs/sertifikaty/razemy-silovye-vilki-rozetki-ds-tr-ts-037-12.04.2031.pdf",
    },
]


def attrs(row: dict) -> dict[str, list[str]]:
    result = {}
    for item in row.get("attributes") or []:
        values = [str(x.get("value") or "").strip() for x in item.get("values") or []
                  if str(x.get("value") or "").strip()]
        result[str(item.get("id"))] = values
    return result


def pages_of_certificates(client: Client) -> list[dict]:
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
    raise RuntimeError("ozon_certificate_page_limit")


def load_assignments() -> dict[str, dict[str, dict]]:
    docs = {x["number"]: x for x in DOCS}
    targets = {x["number"]: {} for x in DOCS}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            number = row.get("Номер/название документа") or ""
            if number not in docs:
                continue
            doc = docs[number]
            if (row.get("Бренд подтвержденный") != "Jazzway"
                    or row.get("Локальный файл") != doc["source_file"]
                    or row.get("SHA256 фактический") != doc["sha256"]
                    or row.get("Применимость") != "Подтверждено статусом покрытия"):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in targets[number]:
                raise RuntimeError("duplicate_or_missing_offer_assignment:" + number + ":" + offer)
            targets[number][offer] = {
                "offer_id": offer,
                "product_name": row.get("Название товара Ozon"),
                "source_url": row.get("URL документа"),
                "official_product_url": row.get("URL карточки/основания"),
                "scope_evidence": json.loads(row["Исходная запись JSON"]).get("Основание связи"),
                "upload_status_in_source_manifest": json.loads(row["Исходная запись JSON"]).get("Загрузка"),
            }
    for number, items in targets.items():
        if len(items) != 36:
            raise RuntimeError(f"unexpected_assignment_count:{number}:{len(items)}")
    offer_sets = [set(x) for x in targets.values()]
    if offer_sets[0] != offer_sets[1]:
        raise RuntimeError("certificate_and_declaration_offer_sets_differ")
    return targets


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_artifact_exists_inspect_before_retry")
    assignment = load_assignments()
    for doc in DOCS:
        path = ROOT / doc["source_file"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise RuntimeError("source_missing_or_hash_mismatch:" + doc["key"])

    offers = sorted(next(iter(assignment.values())).keys())
    client = Client()
    products: dict[str, dict] = {}
    attributes: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("ozon_product_or_attribute_response_incomplete")
        for row in p_rows:
            products.setdefault(str(row.get("offer_id") or ""), []).append(row)
        for row in a_rows:
            attributes.setdefault(str(row.get("offer_id") or ""), []).append(row)
    if set(products) != set(offers) or set(attributes) != set(offers):
        raise RuntimeError("live_ozon_offer_set_mismatch")
    records = pages_of_certificates(client)

    ozon_rows = []
    for offer in offers:
        p_rows, a_rows = products[offer], attributes[offer]
        if len(p_rows) != 1 or len(a_rows) != 1:
            raise RuntimeError("live_ozon_product_or_attribute_ambiguous:" + offer)
        p, a = p_rows[0], attrs(a_rows[0])
        brand = a.get("85", [])
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in a.get("22232", [])})
        doc_checks = {}
        for d in DOCS:
            matches = [r for r in records if norm_number(r.get("certificate_number")) == norm_number(d["number"])]
            if len(matches) > 1:
                raise RuntimeError("duplicate_ozon_record:" + d["number"])
            record = matches[0] if matches else None
            metadata_ok = bool(not record or (
                record.get("type_code") == d["type_code"]
                and str(record.get("issue_date") or "")[:10] == ISSUE
                and str(record.get("expire_date") or "")[:10] == EXPIRY
            ))
            doc_checks[d["key"]] = {
                "record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")} if record else None),
                "metadata_matches_source": metadata_ok,
            }
        ozon_rows.append({
            "offer_id": offer, "product_id": str(p.get("product_id") or p.get("id") or ""),
            "sku": str(p.get("sku") or ""), "is_archived": p.get("is_archived"),
            "brand_values": brand, "tnved_codes": tnved, "name": p.get("name"),
            "identity_scope_safe": p.get("is_archived") is False and brand == ["Jazzway"] and tnved == [TNVED],
            "document_records": doc_checks,
        })

    wb_rows = []
    for i, offer in enumerate(offers, 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "card_count": len(cards), "safe": False,
                            "reason": "exact_card_missing_or_duplicate"})
            continue
        card = cards[0]
        brand = str(card.get("brand") or "").strip().casefold()
        tnved = sorted(set(code_values(card)))
        docs = copy_documents(card)
        existing = {}
        for d in DOCS:
            matching = [x for x in docs if norm_number(x.get("number")) == norm_number(d["number"])]
            exact = bool(len(matching) == 1 and str(matching[0].get("type")) == str(d["wb_type"])
                         and str(matching[0].get("startDate", ""))[:10] == ISSUE
                         and str(matching[0].get("endDate", ""))[:10] == EXPIRY)
            existing[d["key"]] = {"count": len(matching), "exact": exact, "rows": matching}
        safe = brand in {"jazzway", "jazz way"} and tnved == [TNVED]
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "brand": card.get("brand"), "title": card.get("title"),
                        "tnved_codes": tnved, "identity_scope_safe": safe,
                        "existing_documents": existing, "full_card": card})
        if i % 10 == 0:
            print(json.dumps({"phase": "wb_live_preflight", "checked": i, "targets": len(offers)}, ensure_ascii=False), flush=True)

    ozon_safe = sum(x["identity_scope_safe"] for x in ozon_rows)
    wb_safe = sum(x.get("identity_scope_safe") is True for x in wb_rows)
    out = {
        "checked_at_utc": now(), "read_only": True,
        "source_basis": "Two manufacturer-hosted Jazzway PDFs; OCR of both source PDFs and exact article/order-code rows in official Jazzway product pages linked from the assignment manifest.",
        "issue_date": ISSUE, "expiry_date": EXPIRY, "tnved": TNVED,
        "products_per_document": 36, "documents": DOCS,
        "offer_set_identical_for_both_documents": True,
        "ozon_product_count": len(ozon_rows), "ozon_identity_scope_safe_count": ozon_safe,
        "ozon_problem_counts": dict(collections.Counter(
            "archived_or_unclear" if x["is_archived"] is not False else
            "brand_mismatch" if x["brand_values"] != ["Jazzway"] else
            "tnved_mismatch" if x["tnved_codes"] != [TNVED] else "safe" for x in ozon_rows)),
        "ozon_targets": ozon_rows,
        "wb_card_count": sum(x.get("card_count", 1) == 1 for x in wb_rows),
        "wb_identity_scope_safe_count": wb_safe,
        "wb_problem_counts": dict(collections.Counter("safe" if x.get("identity_scope_safe") else x.get("reason", "brand_or_tnved_mismatch") for x in wb_rows)),
        "wb_targets": wb_rows,
        "wb_review_left_pending": True,
        "local_source_files_deleted": False,
    }
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in out.items() if k not in {"ozon_targets", "wb_targets", "documents"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
