#!/usr/bin/env python3
"""Fresh read-only preflight for two active Arlight declarations with exact product assignments."""
from __future__ import annotations

import collections
import csv
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
EDGES = HERE / "all_confirmed_source_assignments_live_20261022.csv"
OUT = HERE / "arlight_71655_33370_live_preflight_20261022.json"
TNVED = "8537109800"
DOCS = [
    {
        "number": "ЕАЭС N RU Д-CN.РА01.В.71655/26",
        "record_id": "21135804",
        "issue_date": "2026-02-10",
        "expire_date": "2031-02-09",
        "scope": "Arlight/Intelligent Arlight/Ardecoled LED control devices: SMART, ARL, VT, CS, HX, SR, Mini SR, LN, ARD, DALI, CSMB, SPV, TY, ZB, DMX, SPI, MATTER, STEP, KNX; ARL audio controllers.",
        "source_pdf": "output_to_user/certificates/group_1/documents/arlight/ADC6FD1692D7C547B67DF4B0765F9340.pdf",
        "source_sha256": "",
        "manufacturer_pdf_url": "https://arlight.ru/upload/certificates/ADC6FD1692D7C547B67DF4B0765F9340.pdf",
    },
    {
        "number": "ЕАЭС N RU Д-CN.РА03.В.33370/26",
        "record_id": "21321084",
        "issue_date": "2026-04-13",
        "expire_date": "2031-04-09",
        "scope": "Arlight/Intelligent Arlight decoders of SMART, ARL and DMX series.",
        "source_pdf": "output_to_user/certificates/group_1/documents/arlight/617FEA6F5689C343B1AC1D3C0350735F.pdf",
        "source_sha256": "",
        "manufacturer_pdf_url": "https://arlight.ru/upload/certificates/617FEA6F5689C343B1AC1D3C0350735F.pdf",
    },
]


def norm(value: object) -> str:
    translit = str.maketrans({"А":"A", "В":"B", "Е":"E", "К":"K", "М":"M", "Н":"H",
                             "О":"O", "Р":"P", "С":"C", "Т":"T", "У":"Y", "Х":"X",
                             "Ё":"E", "Э":"E", "Д":"D", "П":"P"})
    result = "".join(ch for ch in str(value or "").upper().translate(translit) if ch.isalnum())
    for prefix in ("EAEC", "EAEU", "EAES", "EAC"):
        if result.startswith(prefix):
            result = result[len(prefix):]
            break
    if result.startswith("N"):
        result = result[1:]
    if result.startswith("RU"):
        result = result[2:]
    return result


def values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(ident)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def codes(items: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in items if str(x).strip()})


def wb_tnved(card: dict) -> list[str]:
    found = []
    for char in card.get("characteristics") or []:
        label = re.sub(r"\s+", "", str(char.get("name") or "").casefold()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            value = char.get("value")
            found.extend(value if isinstance(value, list) else [value])
    return codes([str(x) for x in found if x is not None])


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"preflight_artifact_exists_inspect_first:{OUT}")
    for doc in DOCS:
        path = ROOT / doc["source_pdf"]
        if not path.is_file():
            raise RuntimeError(f"source_missing:{path}")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if doc["source_sha256"] and doc["source_sha256"] != sha:
            raise RuntimeError(f"source_sha_mismatch:{path}")
        doc["source_sha256"] = sha

    edge_by_offer = {}
    with EDGES.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            edge_by_offer.setdefault(str(row.get("offer_id") or ""), row)

    assignment_rows = list(csv.DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline="")))
    targets_by_doc = {}
    for doc in DOCS:
        selected = {}
        for row in assignment_rows:
            if norm(row.get("Номер/название документа")) != norm(doc["number"]):
                continue
            if row.get("Бренд подтвержденный") != "Arlight":
                continue
            if row.get("Применимость") not in ("Подтверждено статусом покрытия", "Подтверждено источником"):
                continue
            if str(row.get("Локальный файл") or "") != doc["source_pdf"]:
                raise RuntimeError("assignment_source_path_conflict:" + str(row.get("Артикул продавца")))
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer:
                raise RuntimeError("assignment_offer_missing")
            if offer in selected and selected[offer].get("Исходная запись JSON") != row.get("Исходная запись JSON"):
                raise RuntimeError("duplicate_assignment_conflict:" + offer)
            selected[offer] = row
        if not selected:
            raise RuntimeError("no_confirmed_assignment_rows:" + doc["number"])
        for offer in selected:
            if offer not in edge_by_offer:
                raise RuntimeError("no_baseline_live_edge:" + offer)
        targets_by_doc[doc["number"]] = selected

    sys.path.insert(0, str(PILOT))
    from api_client import Client, now  # noqa: E402
    client = Client()

    all_offers = sorted({offer for selected in targets_by_doc.values() for offer in selected})
    ozon_products = {}
    ozon_attrs = {}
    for start in range(0, len(all_offers), 100):
        batch = all_offers[start:start + 100]
        pbody = client.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        prows = pbody.get("items") or pbody.get("result", {}).get("items") or []
        abody = client.call("ozon", "/v4/product/info/attributes",
                            {"filter": {"offer_id": batch}, "limit": len(batch)})
        arows = abody.get("result") or abody.get("items") or []
        for row in prows:
            offer = str(row.get("offer_id") or "")
            if not offer or offer in ozon_products:
                raise RuntimeError("ozon_duplicate_or_empty_offer")
            ozon_products[offer] = row
        for row in arows:
            offer = str(row.get("offer_id") or "")
            if not offer or offer in ozon_attrs:
                raise RuntimeError("ozon_duplicate_or_empty_attribute_offer")
            ozon_attrs[offer] = row
    if set(ozon_products) != set(all_offers) or set(ozon_attrs) != set(all_offers):
        raise RuntimeError("ozon_live_products_or_attributes_incomplete")

    ozon_certs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        ozon_certs.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_list_page_limit")

    by_number = collections.defaultdict(list)
    for row in ozon_certs:
        by_number[norm(row.get("certificate_number"))].append(row)

    result_docs = []
    all_ozon_targets = []
    all_wb_targets = []
    for doc in DOCS:
        assignments = targets_by_doc[doc["number"]]
        offers = sorted(assignments)
        match = by_number.get(norm(doc["number"]), [])
        if len(match) > 1:
            raise RuntimeError("duplicate_ozon_certificate_record:" + doc["number"])
        record = match[0] if match else None
        bindings = client.ozon_bindings(record["certificate_id"]) if record else []
        bound_by_product = collections.defaultdict(list)
        for binding in bindings:
            bound_by_product[str(binding.get("product_id") or "")].append(binding)

        ozon_rows = []
        wb_rows = []
        for offer in offers:
            assignment = assignments[offer]
            edge = edge_by_offer[offer]
            product = ozon_products[offer]
            attr = ozon_attrs[offer]
            product_id = str(product.get("id") or product.get("product_id") or "")
            sku = str(product.get("sku") or "")
            brand = values(attr, 85)
            tnved = codes(values(attr, 22232))
            conflicts = []
            if product_id != str(edge.get("ozon_product_id") or "") or sku != str(edge.get("ozon_sku") or ""):
                conflicts.append("ozon_identity_changed")
            if product.get("is_archived") is not False:
                conflicts.append("ozon_archived_or_unknown")
            if brand != ["Arlight"]:
                conflicts.append("ozon_brand_mismatch")
            if tnved != [TNVED]:
                conflicts.append("ozon_tnved_not_exact")
            source_offer = json.loads(assignment.get("Исходная запись JSON") or "{}")
            binding_rows = bound_by_product.get(product_id, [])
            exact_bindings = [b for b in binding_rows if str(b.get("sku") or "") == sku]
            if len(exact_bindings) > 1:
                conflicts.append("duplicate_ozon_binding")
            ozon_row = {"offer_id": offer, "product_id": product_id, "sku": sku,
                        "live_name": product.get("name"), "brand_values": brand, "tnved_codes": tnved,
                        "is_archived": product.get("is_archived"),
                        "source_article_evidence": assignment.get("Основание сопоставления"),
                        "source_product_page": assignment.get("URL карточки/основания"),
                        "assignment_json_model": source_offer.get("seller_article_base") or source_offer.get("article"),
                        "existing_binding_rows": [{"sku": str(b.get("sku") or ""),
                                                   "status": b.get("product_status_code")}
                                                  for b in binding_rows],
                        "already_exact_bound": bool(exact_bindings),
                        "eligible": not conflicts, "conflicts": conflicts}
            ozon_rows.append(ozon_row)
            all_ozon_targets.append({"document_number": doc["number"], **ozon_row})

            cards = client.wb_cards(offer)
            if len(cards) > 1:
                raise RuntimeError("duplicate_wb_vendor_code_cards:" + offer)
            card = cards[0] if cards else None
            wb_conflicts = []
            if card is None:
                wb_conflicts.append("no_exact_wb_card")
            else:
                if str(card.get("nmID") or "") != str(edge.get("wb_nmID") or ""):
                    wb_conflicts.append("wb_nmID_changed")
                if str(card.get("vendorCode") or "") != offer:
                    wb_conflicts.append("wb_vendor_code_mismatch")
                if str(card.get("brand") or "").casefold() != "arlight":
                    wb_conflicts.append("wb_brand_mismatch")
                if wb_tnved(card) != [TNVED]:
                    wb_conflicts.append("wb_tnved_not_exact")
            docs_container = (card.get("documents") or {}) if card else {}
            current_docs = docs_container.get("items") or []
            same_number = [d for d in current_docs if norm(d.get("number")) == norm(doc["number"])]
            exact_number = [d for d in same_number if int(d.get("type") or 0) == 2
                            and str(d.get("startDate") or "")[:10] == doc["issue_date"]
                            and str(d.get("endDate") or "")[:10] == doc["expire_date"]]
            if same_number and len(exact_number) != 1:
                wb_conflicts.append("wb_existing_number_metadata_conflict")
            if len(exact_number) > 1:
                wb_conflicts.append("wb_duplicate_exact_document")
            if card and docs_container.get("excludeDocuments") is True:
                wb_conflicts.append("wb_documents_explicitly_excluded")
            wb_row = {"offer_id": offer, "nmID": str(card.get("nmID") or "") if card else None,
                      "vendorCode": card.get("vendorCode") if card else None,
                      "brand": card.get("brand") if card else None,
                      "title": card.get("title") if card else None,
                      "tnved_codes": wb_tnved(card) if card else [],
                      "excludeDocuments": docs_container.get("excludeDocuments") if card else None,
                      "current_document_count": len(current_docs),
                      "exact_document_rows": exact_number,
                      "other_current_documents": [{k: d.get(k) for k in ("type", "number", "startDate", "endDate", "verdict")}
                                                  for d in current_docs],
                      "eligible": not wb_conflicts, "conflicts": wb_conflicts,
                      "card": card}
            wb_rows.append(wb_row)
            all_wb_targets.append({"document_number": doc["number"], **wb_row})

        if record:
            metadata_exact = (record.get("type_code") == "declaration"
                              and str(record.get("issue_date") or "")[:10] == doc["issue_date"]
                              and str(record.get("expire_date") or "")[:10] == doc["expire_date"])
            ozon_record = {k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                                                       "status_code", "issue_date", "expire_date", "products_count")}
            if not metadata_exact:
                raise RuntimeError("ozon_existing_record_metadata_conflict:" + doc["number"])
            if record.get("status_code") not in {"approved", "under_review"}:
                raise RuntimeError("ozon_existing_record_not_writable:" + str(record.get("status_code")))
        else:
            metadata_exact = False
            ozon_record = None
        result_docs.append({"number": doc["number"], "official_registry_id": doc["record_id"],
                            "issue_date": doc["issue_date"], "expire_date": doc["expire_date"],
                            "scope": doc["scope"], "tnved_on_fsa_record": TNVED,
                            "source_pdf": doc["source_pdf"], "source_sha256": doc["source_sha256"],
                            "manufacturer_pdf_url": doc["manufacturer_pdf_url"],
                            "source_assignment_count": len(assignments), "ozon_record": ozon_record,
                            "ozon_record_metadata_exact": metadata_exact,
                            "ozon_targets": ozon_rows, "wb_targets": wb_rows,
                            "ozon_eligible_count": sum(x["eligible"] for x in ozon_rows),
                            "wb_eligible_count": sum(x["eligible"] for x in wb_rows)})

    output = {"checked_at_utc": now(), "read_only": True,
              "official_fsa_records": [
                  {"number": "ЕАЭС N RU Д-CN.РА01.В.71655/26", "url": "https://pub.fsa.gov.ru/rds/declaration/view/21135804/product",
                   "status": "Действует", "issue_date": "2026-02-10", "expire_date": "2031-02-09",
                   "technical_regulation": "ТР ТС 020/2011", "tnved": TNVED},
                  {"number": "ЕАЭС N RU Д-CN.РА03.В.33370/26", "url": "https://pub.fsa.gov.ru/rds/declaration/view/21321084/product",
                   "status": "Действует", "issue_date": "2026-04-13", "expire_date": "2031-04-09",
                   "technical_regulation": "ТР ТС 020/2011", "tnved": TNVED},
              ],
              "documents": result_docs,
              "summary": {"document_count": len(result_docs), "target_offer_document_pairs": len(all_ozon_targets),
                          "ozon_eligible_pairs": sum(x["eligible"] for x in all_ozon_targets),
                          "ozon_already_bound_pairs": sum(x["already_exact_bound"] for x in all_ozon_targets),
                          "wb_exact_cards": sum(x["nmID"] is not None for x in all_wb_targets),
                          "wb_eligible_pairs": sum(x["eligible"] for x in all_wb_targets),
                          "wb_already_exact_pairs": sum(bool(x["exact_document_rows"]) for x in all_wb_targets),
                          "ozon_conflicts": dict(collections.Counter(c for x in all_ozon_targets for c in x["conflicts"])),
                          "wb_conflicts": dict(collections.Counter(c for x in all_wb_targets for c in x["conflicts"]))},
              "local_source_files_deleted": False}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": output["checked_at_utc"],
                      "summary": output["summary"],
                      "docs": [{"number": d["number"], "source_assignment_count": d["source_assignment_count"],
                                "ozon_eligible": d["ozon_eligible_count"], "wb_eligible": d["wb_eligible_count"],
                                "existing_record": d["ozon_record"]} for d in result_docs]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
