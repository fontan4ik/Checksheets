#!/usr/bin/env python3
"""Upload Feron 00973/24 and bind the exact CAB rail SKUs on Ozon and WB.

Default mode only builds a live preflight plan. The execute mode journals every
write, creates the Ozon record once, reads it back before binding, and leaves
WB review pending. Local source files are never deleted by this runner.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
API_DIR = BASE.parent / "certificate_api_pilot_20261012"
FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
ORIGINAL = FERON / "00_Оригиналы_файлов" / (
    "Сертификат__00973_Шинопровод_для_трековых_светильников_ТМ_Feron_"
    "серия_САВ_Сертификат_по_004_ТР_ТС__acf685d3e4.jpg"
)
PDF = BASE / "source_docs" / "feron_00973_24_upload.pdf"
NUMBER = "ЕАЭС RU C-CN.НВ12.В.00973/24"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3422351/baseInfo"
ISSUE = "2024-04-19"
EXPIRY = "2029-04-18"
TYPE_CODE = "certificate_of_conformity"
PLAN_PATH = BASE / "feron_00973_crossplatform_plan_20261020.json"
EXEC_PATH = BASE / "feron_00973_crossplatform_execution_20261020.json"
READBACK_PATH = BASE / "feron_00973_crossplatform_readback_20261020.json"

sys.path.insert(0, "/opt/homebrew/lib/python3.14/site-packages")
sys.path.insert(0, str(API_DIR))
from api_client import Client, digest, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    DOC_FIELDS, UPDATE_CARD_FIELDS, comparable_card, doc_key, wb_datetime,
)


def atomic(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush()
    tmp.replace(path)


def norm(value: object) -> str:
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H",
                           "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                           "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def suffix(value: object) -> str:
    match = re.search(r"(?<!\d)(\d{4,6})\s*/\s*(\d{2,4})(?!\d)", str(value or ""))
    return match.group(1) + "/" + match.group(2) if match else ""


def targets_from_workbook() -> tuple[list[dict], list[dict]]:
    import openpyxl

    if not WORKBOOK.is_file() or not ORIGINAL.is_file() or not PDF.is_file():
        raise RuntimeError("Feron workbook, original scan, or derived upload PDF is missing")
    wb = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    rows, excluded = [], []
    for row in wb["Артикул-файл"].iter_rows(min_row=6, values_only=True):
        if not row or suffix(row[6]) != "00973/24":
            continue
        offer, article, title = str(row[0] or ""), str(row[1] or ""), str(row[2] or "")
        # FSA scope is the Feron CAB track rail itself. Mounting brackets are
        # listed beside the rail in the supplier workbook but are separate goods.
        is_rail = "ШИНОПРОВОД" in title.upper() and re.search(r"\bCAB\s*100[3457]\b", title, re.I)
        reason = ""
        if "УДАЛИТЬ" in offer.upper():
            reason = "workbook_offer_marked_for_deletion"
        elif not is_rail:
            reason = "outside_FSA_product_scope_mounting_accessory_or_unmatched_model"
        if reason:
            excluded.append({"offer_id": offer, "article": article, "title": title, "reason": reason})
            continue
        if str(row[12] or "").find("2029-04-18") < 0:
            excluded.append({"offer_id": offer, "article": article, "title": title,
                             "reason": "workbook_status_or_expiry_not_confirmed"})
            continue
        rows.append({"offer_id": offer, "article": article, "title": title,
                     "product_id": str(row[3] or ""), "sku": str(row[4] or ""),
                     "document_number": str(row[6] or ""), "scope": str(row[13] or "")})
    if len({x["offer_id"] for x in rows}) != len(rows):
        raise RuntimeError("Duplicate source offers for 00973/24")
    if len({x["sku"] for x in rows}) != len(rows) or len({x["product_id"] for x in rows}) != len(rows):
        raise RuntimeError("Duplicate Ozon SKU or product ID in Feron source mapping")
    if not rows:
        raise RuntimeError("No CAB rail targets survived the exact-scope source filter")
    return rows, excluded


def ozon_certificates(client: Client) -> list[dict]:
    records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError(f"Ozon certificate list omitted page {page}")
        records.extend(batch)
        if len(batch) < 100:
            return records
    raise RuntimeError("Ozon certificate list exceeded 100 pages")


def ozon_bindings(client: Client, certificate_id: int) -> list[dict]:
    all_items, cursor, expected = [], 0, None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "last_id": cursor, "limit": 500,
        }).get("result") or {}
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon binding readback omitted items/count")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed during pagination")
        all_items.extend(batch)
        if len(all_items) == expected:
            if len({str(x.get("product_id")) for x in all_items}) != len(all_items):
                raise RuntimeError("Ozon binding list contains duplicate products")
            return all_items
        if not batch or len(all_items) > expected:
            raise RuntimeError("Ozon binding pagination is incomplete")
        next_cursor = int(batch[-1].get("product_id") or 0)
        if next_cursor <= cursor:
            raise RuntimeError("Ozon binding cursor failed to advance")
        cursor = next_cursor


def raw_wb_documents(card: dict) -> list[dict]:
    return list((card.get("documents") or {}).get("items") or [])


def wb_doc_projection(card: dict) -> list[dict]:
    return [{k: item[k] for k in DOC_FIELDS if k in item} for item in raw_wb_documents(card)]


def merge_wb(card: dict, wanted: dict) -> dict | None:
    docs = wb_doc_projection(card)
    same = [item for item in docs if doc_key(item) == doc_key(wanted)]
    if same:
        if any((str(item.get("startDate", ""))[:10], str(item.get("endDate", ""))[:10]) !=
               (ISSUE, EXPIRY) for item in same):
            raise ValueError("WB already has 00973/24 with conflicting dates")
        return None
    payload = {key: card[key] for key in UPDATE_CARD_FIELDS if key in card}
    payload["documents"] = {"items": docs + [wanted], "excludeDocuments": False}
    return payload


def build_plan(client: Client) -> dict:
    targets, source_exclusions = targets_from_workbook()
    pdf_hash = digest(PDF)
    workbook_hash = digest(WORKBOOK)

    products = []
    for start in range(0, len(targets), 100):
        result = client.call("ozon", "/v3/product/info/list", {
            "offer_id": [x["offer_id"] for x in targets[start:start + 100]],
        })
        products.extend(result.get("items") or result.get("result", {}).get("items") or [])
    by_offer = {str(x.get("offer_id")): x for x in products}
    eligible, ozon_exclusions = [], []
    by_source = {x["offer_id"]: x for x in targets}
    for offer in by_source:
        product = by_offer.get(offer)
        source = by_source[offer]
        if not product:
            ozon_exclusions.append({"offer_id": offer, "reason": "not_found_in_live_ozon_catalog"})
        elif (str(product.get("id")) != source["product_id"] or
              str(product.get("sku")) != source["sku"] or product.get("is_archived") is not False):
            ozon_exclusions.append({"offer_id": offer, "reason": "live_ozon_identity_or_archive_mismatch",
                                    "live_id": product.get("id"), "live_sku": product.get("sku"),
                                    "live_is_archived": product.get("is_archived")})
        else:
            eligible.append({**source, "live_name": product.get("name"),
                             "live_id": str(product.get("id")), "live_sku": str(product.get("sku"))})
    if not eligible:
        raise RuntimeError("No workbook target has an exact active Ozon product identity")

    certs = ozon_certificates(client)
    matching = [x for x in certs if x.get("type_code") == TYPE_CODE and suffix(x.get("certificate_number")) == "00973/24"]
    if len(matching) > 1:
        raise RuntimeError("Multiple live Ozon records already match 00973/24")

    wanted = {"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
    wb_updates, wb_already, wb_missing, wb_exclusions = [], [], [], []
    for target in eligible:
        try:
            cards = client.wb_cards(target["offer_id"])
        except Exception as exc:
            wb_exclusions.append({"offer_id": target["offer_id"], "reason": "wb_live_read_failed",
                                  "error_type": type(exc).__name__})
            continue
        if not cards:
            wb_missing.append(target["offer_id"])
            continue
        if len(cards) != 1 or str(cards[0].get("vendorCode")) != target["offer_id"]:
            wb_exclusions.append({"offer_id": target["offer_id"], "reason": "wb_card_identity_missing_or_ambiguous"})
            continue
        card = cards[0]
        if str(card.get("brand") or "").strip().casefold() != "feron":
            wb_exclusions.append({"offer_id": target["offer_id"], "reason": "wb_brand_mismatch",
                                  "live_brand": card.get("brand")})
            continue
        title = str(card.get("title") or "")
        # The live WB display title often omits Feron's CAB model code, while
        # the exact vendorCode still matches the supplier source row. Require
        # the product noun in the current title; the CAB series was verified
        # from the source SKU mapping against the official FSA scope above.
        if "ШИНОПРОВОД" not in title.upper():
            wb_exclusions.append({"offer_id": target["offer_id"], "reason": "wb_title_outside_verified_FSA_scope",
                                  "live_title": title})
            continue
        try:
            payload = merge_wb(card, wanted)
        except ValueError as exc:
            wb_exclusions.append({"offer_id": target["offer_id"], "reason": "wb_conflicting_document",
                                  "detail": str(exc)})
            continue
        row = {"offer_id": target["offer_id"], "nmID": str(card.get("nmID")),
               "brand": card.get("brand"), "title": title,
               "existing_document_count": len(wb_doc_projection(card)), "payload": payload}
        if payload is None:
            exact = [d for d in raw_wb_documents(card) if doc_key(d) == doc_key(wanted)]
            row["existing_document"] = exact
            row["valid_wb_verdict"] = any((d.get("verdict") or {}).get("verified") is True and
                                              (d.get("verdict") or {}).get("reason") == "valid" for d in exact)
            wb_already.append(row)
        else:
            row["before"] = card
            wb_updates.append(row)
    return {
        "checked_at": now(), "number": NUMBER, "fsa_url": FSA_URL,
        "fsa_status_checked_live": "Действует до 2029-04-18",
        "fsa_scope_checked_live": "Feron; шинопроводы для трековых светильников; серия CAB",
        "issue_date": ISSUE, "expire_date": EXPIRY, "type_code": TYPE_CODE,
        "workbook": str(WORKBOOK), "workbook_sha256": workbook_hash,
        "original_scan": str(ORIGINAL), "original_scan_sha256": digest(ORIGINAL),
        "source_pdf": str(PDF), "source_file_sha256": pdf_hash, "source_file_bytes": PDF.stat().st_size,
        "source_mapping_targets": targets, "source_exclusions": source_exclusions,
        "ozon_live_products_read": len(products), "ozon_eligible_products": eligible,
        "ozon_product_exclusions": ozon_exclusions, "ozon_certificate_list_count": len(certs),
        "ozon_existing_matching_records": matching,
        "wb_cards_to_update": wb_updates, "wb_already_present": wb_already,
        "wb_no_exact_card": wb_missing, "wb_exclusions": wb_exclusions,
    }


def execute(client: Client, plan: dict) -> dict:
    if READBACK_PATH.exists():
        raise RuntimeError("Final readback already exists; repeated writes are blocked")
    if EXEC_PATH.exists():
        raise RuntimeError("Execution journal already exists; reconcile its recorded phase before another write")
    execution = {"started_at": now(), "phase": "preflight_complete", "number": NUMBER,
                 "plan_path": str(PLAN_PATH), "ozon": {}, "wb": {}}
    atomic(EXEC_PATH, execution)
    matching = plan["ozon_existing_matching_records"]
    if matching:
        record = matching[0]
        if (str(record.get("issue_date", ""))[:10] != ISSUE or str(record.get("expire_date", ""))[:10] != EXPIRY
                or record.get("accordance_type_code") != "EAEU"
                or record.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
            raise RuntimeError("Existing Ozon certificate metadata conflicts with the verified FSA document")
        certificate_id = int(record["certificate_id"])
    else:
        seed = plan["ozon_eligible_products"][0]
        expiry = dt.date.fromisoformat(EXPIRY)
        params = {
            "name": "Сертификат соответствия № " + NUMBER,
            "certificate_type": TYPE_CODE.upper(), "certificate_country": "RU",
            "accordance_type": "EAEU", "number": NUMBER,
            "issue_date": ISSUE + "T00:00:00Z",
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": [seed["sku"]], "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(PDF.read_bytes()).decode("ascii"), "name": PDF.name}],
            "link_to_registry": FSA_URL.replace("/baseInfo", ""),
        }
        if digest(PDF) != plan["source_file_sha256"]:
            raise RuntimeError("Upload PDF hash changed after preflight")
        execution.update(phase="ozon_create_prepared", ozon={"seed_offer": seed["offer_id"],
                         "seed_sku": seed["sku"], "source_file_sha256": plan["source_file_sha256"]})
        atomic(EXEC_PATH, execution)
        try:
            response = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
        except Exception as exc:
            execution.update(phase="ozon_create_uncertain", error_type=type(exc).__name__, updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon create outcome uncertain; read live certificate list before retry") from None
        certificate_id = int(response.get("certificate_id") or 0)
        states = [x.get("state") for x in response.get("params", []) if isinstance(x, dict)]
        execution["ozon"].update(create_response=response, certificate_id=certificate_id)
        if not certificate_id or response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
            execution.update(phase="ozon_create_not_validated", updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon create response is not fully valid; no binds/updates were sent")
        execution.update(phase="ozon_created", updated_at=now())
        atomic(EXEC_PATH, execution)

    certs = ozon_certificates(client)
    live = next((x for x in certs if str(x.get("certificate_id")) == str(certificate_id)), None)
    if not live or suffix(live.get("certificate_number")) != "00973/24":
        raise RuntimeError("Ozon live listing does not confirm the exact 00973/24 record")
    lookup_number = str(live.get("certificate_number") or "")
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": lookup_number}).get("result") or {}
    if (int(info.get("certificate_id") or -1) != certificate_id or info.get("type_code") != TYPE_CODE or
            str(info.get("issue_date", ""))[:10] != ISSUE or str(info.get("expire_date", ""))[:10] != EXPIRY or
            info.get("accordance_type_code") != "EAEU" or
            info.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        execution.update(phase="ozon_metadata_conflict", ozon_info=info, updated_at=now())
        atomic(EXEC_PATH, execution)
        raise RuntimeError("Ozon metadata differs from current official FSA data")

    targets = plan["ozon_eligible_products"]
    prior = ozon_bindings(client, certificate_id)
    by_id = {str(x.get("product_id")): x for x in prior}
    for target in targets:
        item = by_id.get(target["product_id"])
        if item and str(item.get("sku")) != target["sku"]:
            raise RuntimeError(f"Ozon binding identity conflict for {target['offer_id']}")
        if item and item.get("product_status_code") in {"declined", "rejected", "invalid"}:
            raise RuntimeError(f"Ozon existing target binding is declined: {target['offer_id']}")
    missing = [x["sku"] for x in targets if x["product_id"] not in by_id]
    if not matching and targets[0]["sku"] in missing:
        # Creation includes the seed SKU in the request and should create its
        # first association. Never bind twice if that association is delayed.
        raise RuntimeError("Ozon create seed binding is not yet visible; reconcile before retry")
    if missing:
        execution.update(phase="ozon_bind_prepared", updated_at=now(), ozon={
            **execution.get("ozon", {}), "certificate_id": certificate_id,
            "initial_binding_count": len(prior), "missing_skus": missing})
        atomic(EXEC_PATH, execution)
        try:
            bound = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": certificate_id, "skus": missing,
            }, mutation=True)
        except Exception as exc:
            execution.update(phase="ozon_bind_uncertain", error_type=type(exc).__name__, updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon bind outcome uncertain; reconcile live bindings before retry") from None
        execution["ozon"]["bind_response"] = bound
        if bound.get("result") is not True:
            execution.update(phase="ozon_bind_rejected", updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon rejected the bind request")
        execution.update(phase="ozon_bind_accepted", updated_at=now())
        atomic(EXEC_PATH, execution)
    final_info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": lookup_number}).get("result") or {}
    final_bindings = ozon_bindings(client, certificate_id)
    final_by_id = {str(x.get("product_id")): x for x in final_bindings}
    ozon_rows = []
    for target in targets:
        item = final_by_id.get(target["product_id"])
        ozon_rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                          "sku": target["sku"], "visible": bool(item),
                          "identity_matches": bool(item and str(item.get("sku")) == target["sku"]),
                          "status": item.get("product_status_code") if item else None})
    if any(not x["visible"] or not x["identity_matches"] for x in ozon_rows):
        execution.update(phase="ozon_readback_incomplete", updated_at=now(), ozon_info=final_info,
                         ozon_binding_readback=ozon_rows)
        atomic(EXEC_PATH, execution)
        raise RuntimeError("Ozon did not expose every intended binding")
    execution.update(phase="ozon_readback_complete", updated_at=now(), ozon={
        **execution.get("ozon", {}), "certificate_id": certificate_id,
        "certificate_status": final_info.get("status_code"), "binding_count": len(final_bindings),
        "target_binding_readback": ozon_rows})
    atomic(EXEC_PATH, execution)

    updates = plan["wb_cards_to_update"]
    wanted = {"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
    for row in updates:
        fresh = client.wb_cards(row["offer_id"])
        if len(fresh) != 1 or str(fresh[0].get("nmID")) != row["nmID"]:
            raise RuntimeError(f"WB card changed or became ambiguous: {row['offer_id']}")
        if str(fresh[0].get("brand") or "").strip().casefold() != "feron":
            raise RuntimeError(f"WB brand changed before write: {row['offer_id']}")
        row["payload"] = merge_wb(fresh[0], wanted)
        row["before"] = fresh[0]
    payloads = [x["payload"] for x in updates if x["payload"] is not None]
    if payloads:
        execution.update(phase="wb_update_prepared", updated_at=now(), wb={
            "cards": [{"offer_id": x["offer_id"], "nmID": x["nmID"]} for x in updates],
            "document": wanted})
        atomic(EXEC_PATH, execution)
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            execution.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("WB update outcome uncertain; read the cards before any retry") from None
        execution["wb"]["update_response"] = response
        if response.get("error") is not False:
            execution.update(phase="wb_update_rejected", updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("WB returned an error for the certificate update")
        execution.update(phase="wb_update_accepted", updated_at=now())
        atomic(EXEC_PATH, execution)

    wb_rows = []
    for row in updates:
        fresh = client.wb_cards(row["offer_id"])
        exact = [d for d in (raw_wb_documents(fresh[0]) if len(fresh) == 1 else [])
                 if doc_key(d) == doc_key(wanted)]
        dates_match = any(str(d.get("startDate", ""))[:10] == ISSUE and
                          str(d.get("endDate", ""))[:10] == EXPIRY for d in exact)
        preserved = (len(fresh) == 1 and comparable_card(fresh[0]) == comparable_card(row["before"]))
        valid = any((d.get("verdict") or {}).get("verified") is True and
                    (d.get("verdict") or {}).get("reason") == "valid" for d in exact)
        wb_rows.append({"offer_id": row["offer_id"], "nmID": row["nmID"],
                        "document_visible": bool(exact), "dates_match": dates_match,
                        "unrelated_fields_preserved": preserved, "valid_wb_verdict": valid,
                        "status": "valid" if valid and dates_match and preserved else
                                 "visible_pending_review" if exact and dates_match and preserved else "readback_incomplete",
                        "documents": exact})
    for row in plan["wb_already_present"]:
        fresh = client.wb_cards(row["offer_id"])
        exact = [d for d in (raw_wb_documents(fresh[0]) if len(fresh) == 1 else [])
                 if doc_key(d) == doc_key(wanted)]
        dates = any(str(d.get("startDate", ""))[:10] == ISSUE and
                    str(d.get("endDate", ""))[:10] == EXPIRY for d in exact)
        valid = any((d.get("verdict") or {}).get("verified") is True and
                    (d.get("verdict") or {}).get("reason") == "valid" for d in exact)
        wb_rows.append({"offer_id": row["offer_id"], "nmID": row["nmID"],
                        "document_visible": bool(exact), "dates_match": dates,
                        "unrelated_fields_preserved": True, "valid_wb_verdict": valid,
                        "status": "valid" if valid and dates else
                                 "visible_pending_review" if exact and dates else "readback_incomplete",
                        "documents": exact})
    if any(x["status"] not in {"valid", "visible_pending_review"} for x in wb_rows):
        execution.update(phase="wb_readback_incomplete", updated_at=now(), wb_readback=wb_rows)
        atomic(EXEC_PATH, execution)
        raise RuntimeError("WB readback did not confirm all submitted/already-present document metadata")
    result = {
        "checked_at": now(), "number": NUMBER, "ozon_certificate_id": certificate_id,
        "ozon_certificate_status": final_info.get("status_code"),
        "ozon_targets_expected": len(targets), "ozon_targets_visible": len(ozon_rows),
        "ozon_binding_status_counts": dict(collections.Counter(x["status"] for x in ozon_rows)),
        "ozon_bindings": ozon_rows,
        "wb_cards_updated": len(payloads), "wb_documents_already_present": len(plan["wb_already_present"]),
        "wb_valid_verdicts": sum(x["valid_wb_verdict"] for x in wb_rows),
        "wb_pending_review": sum(x["status"] == "visible_pending_review" for x in wb_rows),
        "wb_card_readback": wb_rows, "wb_exact_cards_missing": plan["wb_no_exact_card"],
        "wb_cards_skipped": plan["wb_exclusions"], "ozon_products_skipped": plan["ozon_product_exclusions"],
        "source_rows_excluded": plan["source_exclusions"],
        "source_pdf_deleted": False,
        "source_pdf_retained_reason": "Not every product has a confirmed card and verified document association on both platforms.",
    }
    atomic(READBACK_PATH, result)
    execution.update(phase="complete", finished_at=now(), readback_path=str(READBACK_PATH))
    atomic(EXEC_PATH, execution)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    client = Client()
    plan = build_plan(client)
    atomic(PLAN_PATH, plan)
    summary = {"mode": "execute" if args.execute else "dry_run", "plan_path": str(PLAN_PATH),
               "number": NUMBER, "source_exact_rail_targets": len(plan["source_mapping_targets"]),
               "source_excluded": len(plan["source_exclusions"]),
               "ozon_live_products_read": plan["ozon_live_products_read"],
               "ozon_eligible_products": len(plan["ozon_eligible_products"]),
               "ozon_product_exclusions": len(plan["ozon_product_exclusions"]),
               "ozon_existing_matching_records": len(plan["ozon_existing_matching_records"]),
               "wb_cards_to_update": len(plan["wb_cards_to_update"]),
               "wb_documents_already_present": len(plan["wb_already_present"]),
               "wb_exact_cards_missing": len(plan["wb_no_exact_card"]),
               "wb_cards_skipped": len(plan["wb_exclusions"]),
               "source_file_sha256": plan["source_file_sha256"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.execute:
        print(json.dumps(execute(client, plan), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
