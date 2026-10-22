#!/usr/bin/env python3
"""Upload Feron certificate 01317/22 to exact verified products on Ozon and WB.

Default is a read-only preflight. Writes require --execute. Every mutation is
recorded before it is sent, and uncertain outcomes are reconciled by readback,
never replayed blindly.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
API_DIR = BASE.parent / "certificate_api_pilot_20261012"
FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
WORKBOOK = FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"
PDF = FERON / "00_Оригиналы_файлов" / (
    "Сертификат__01317_датчики_движения_и_освещенности,_серия_SEN;_"
    "дистанционные_выключатели,_серия_TM,_тм_Feron._Сертификат_по_004_и_020_1__0937d89ef4.pdf"
)
NUMBER = "ЕАЭС RU C-CN.HB85.B.01317/22"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3129890/baseInfo"
ISSUE = "2022-08-15"
EXPIRY = "2027-08-14"
TYPE_CODE = "certificate_of_conformity"
PLAN_PATH = BASE / "feron_01317_crossplatform_plan_20261020.json"
EXEC_PATH = BASE / "feron_01317_crossplatform_execution_20261020.json"
VERIFICATION_PATH = BASE / "feron_01317_crossplatform_readback_20261020.json"

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


def normalized(value: object) -> str:
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H",
                           "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                           "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def suffix(value: object) -> str:
    match = re.search(r"(?<!\d)(\d{4,6})\s*/\s*(\d{2,4})(?!\d)", str(value or ""))
    return match.group(1) + "/" + match.group(2) if match else ""


def workbook_targets() -> list[dict]:
    import openpyxl

    if not WORKBOOK.is_file() or not PDF.is_file():
        raise RuntimeError("Feron workbook or source PDF is missing")
    wb = openpyxl.load_workbook(WORKBOOK, read_only=False, data_only=True)
    targets = []
    for row in wb["Артикул-файл"].iter_rows(min_row=6, values_only=True):
        if not row or not row[6] or normalized(row[6]) != normalized(NUMBER):
            continue
        if row[14]:
            continue
        if not str(row[12] or "").startswith("Действует; Действует в ФСА до 2027-08-14"):
            raise RuntimeError(f"Workbook status/date mismatch for {row[0]}")
        if "SEN" not in str(row[2] or "").upper():
            raise RuntimeError(f"Product model no longer matches certificate scope for {row[0]}")
        targets.append({
            "offer_id": str(row[0]), "article": str(row[1]), "title": str(row[2]),
            "product_id": str(row[3]), "sku": str(row[4]), "type": str(row[5]),
            "number": str(row[6]), "scope": str(row[13]), "source_note": str(row[16]),
        })
    if len(targets) != 5 or len({x["offer_id"] for x in targets}) != 5 or len({x["sku"] for x in targets}) != 5:
        raise RuntimeError(f"Expected five exact non-manual SEN targets; found {len(targets)}")
    return targets


def list_ozon_certificates(client: Client) -> list[dict]:
    result = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError(f"Ozon certificate list omitted page {page}")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError("Ozon certificate list exceeded 100 pages")


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    items, cursor, expected = [], 0, None
    while True:
        body = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "last_id": cursor, "limit": 500,
        }).get("result") or {}
        batch, count = body.get("items"), body.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon binding readback")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed during readback")
        items.extend(batch)
        if len(items) == expected:
            if len({str(x.get("product_id")) for x in items}) != len(items):
                raise RuntimeError("Ozon returned duplicate product bindings")
            return items
        if not batch or len(items) > expected:
            raise RuntimeError("Ozon binding pagination incomplete")
        next_cursor = int(batch[-1].get("product_id") or 0)
        if next_cursor <= cursor:
            raise RuntimeError("Ozon binding cursor did not advance")
        cursor = next_cursor


def raw_wb_documents(card: dict) -> list[dict]:
    return list((card.get("documents") or {}).get("items") or [])


def wb_documents(card: dict) -> list[dict]:
    return [{k: item[k] for k in DOC_FIELDS if k in item} for item in raw_wb_documents(card)]


def merge_wb(card: dict, wanted: dict) -> dict | None:
    items = wb_documents(card)
    same = [item for item in items if doc_key(item) == doc_key(wanted)]
    if same:
        if any((str(item.get("startDate", ""))[:10], str(item.get("endDate", ""))[:10]) !=
               (wanted["startDate"][:10], wanted["endDate"][:10]) for item in same):
            raise ValueError("WB already has this number with conflicting dates")
        return None
    payload = {key: card[key] for key in UPDATE_CARD_FIELDS if key in card}
    payload["documents"] = {"items": items + [wanted], "excludeDocuments": False}
    return payload


def wb_error_offers(client: Client, wanted: set[str]) -> set[str]:
    cursor, seen, found = {"limit": 100}, set(), set()
    for _ in range(1000):
        body = client.call("wb", "/content/v2/cards/error/list", {
            "cursor": cursor, "order": {"ascending": True},
        })
        if body.get("error"):
            raise RuntimeError("WB error list returned an error")
        data = body.get("data") or {}
        for item in data.get("items") or []:
            if item.get("vendorCode") in wanted or item.get("offerId") in wanted:
                found.add(str(item.get("vendorCode") or item.get("offerId")))
        next_cursor = data.get("cursor") or {}
        if next_cursor.get("next") is not True:
            return found
        signature = (next_cursor.get("updatedAt"), next_cursor.get("batchUUID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB error list cursor repeated")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "batchUUID": signature[1]}
    raise RuntimeError("WB error list exceeded pagination limit")


def preflight(client: Client) -> dict:
    targets = workbook_targets()
    file_hash = digest(PDF)

    products = []
    for start in range(0, len(targets), 100):
        body = client.call("ozon", "/v3/product/info/list", {
            "offer_id": [x["offer_id"] for x in targets[start:start + 100]],
        })
        products.extend(body.get("items") or body.get("result", {}).get("items") or [])
    by_offer = {str(x.get("offer_id")): x for x in products}
    if set(by_offer) != {x["offer_id"] for x in targets}:
        raise RuntimeError("Ozon current product response did not match all five workbook offers")
    for target in targets:
        product = by_offer[target["offer_id"]]
        if (str(product.get("id")) != target["product_id"] or str(product.get("sku")) != target["sku"]
                or product.get("is_archived") is not False):
            raise RuntimeError(f"Ozon product identity/archive mismatch for {target['offer_id']}")

    certificates = list_ozon_certificates(client)
    matching = [item for item in certificates
                if item.get("type_code") == TYPE_CODE and suffix(item.get("certificate_number")) == "01317/22"]
    if len(matching) > 1:
        raise RuntimeError("Multiple live Ozon records match certificate 01317/22; reconcile before writing")

    offers = {x["offer_id"] for x in targets}
    errors = wb_error_offers(client, offers)
    wb_rows = []
    wb_missing = []
    wb_existing = {}
    wb_already_present = {}
    wanted = {
        "type": 1, "number": NUMBER,
        "startDate": wb_datetime(ISSUE), "endDate": wb_datetime(EXPIRY),
        "isEndless": False,
    }
    for target in targets:
        cards = client.wb_cards(target["offer_id"])
        if not cards:
            wb_missing.append(target["offer_id"])
            continue
        if len(cards) != 1 or cards[0].get("vendorCode") != target["offer_id"]:
            raise RuntimeError(f"WB exact vendorCode is missing or ambiguous for {target['offer_id']}")
        card = cards[0]
        if str(card.get("brand") or "").strip().casefold() != "feron":
            raise RuntimeError(f"WB brand mismatch for {target['offer_id']}")
        if target["offer_id"] in errors:
            raise RuntimeError(f"WB card has an unresolved error for {target['offer_id']}")
        exact_docs = [doc for doc in raw_wb_documents(card) if doc_key(doc) == doc_key(wanted)]
        if exact_docs:
            if any((str(doc.get("startDate", ""))[:10], str(doc.get("endDate", ""))[:10]) !=
                   (ISSUE, EXPIRY) for doc in exact_docs):
                raise RuntimeError(f"WB has a conflicting 01317/22 date for {target['offer_id']}")
            verdicts = [doc.get("verdict") or {} for doc in exact_docs]
            wb_already_present[target["offer_id"]] = {
                "nmID": card.get("nmID"), "number": exact_docs[0].get("number"),
                "type": exact_docs[0].get("type"), "startDate": exact_docs[0].get("startDate"),
                "endDate": exact_docs[0].get("endDate"), "verdicts": verdicts,
                "valid_verdict": any(v.get("verified") is True and v.get("reason") == "valid" for v in verdicts),
            }
        payload = merge_wb(card, wanted)
        wb_existing[target["offer_id"]] = {
            "nmID": card.get("nmID"), "brand": card.get("brand"),
            "title": card.get("title"), "existing_document_count": len(wb_documents(card)),
            "payload": payload,
        }
        if payload is not None:
            wb_rows.append({"offer_id": target["offer_id"], "nmID": card.get("nmID"), "payload": payload})
    return {
        "checked_at": now(), "number": NUMBER, "type_code": TYPE_CODE,
        "fsa_url": FSA_URL, "fsa_status_checked_live": "Действует до 2027-08-14",
        "fsa_scope_checked_live": "Feron, датчики движения и освещенности серии SEN; дистанционные выключатели серии TM",
        "issue_date": ISSUE, "expire_date": EXPIRY,
        "workbook": str(WORKBOOK), "workbook_sha256": digest(WORKBOOK),
        "source_file": str(PDF), "source_file_sha256": file_hash,
        "source_file_bytes": PDF.stat().st_size, "targets": targets,
        "ozon_products_verified": len(products), "ozon_certificate_list_count": len(certificates),
        "ozon_existing_matching_records": matching,
        "wb_error_offers": sorted(errors), "wb_exact_cards": wb_existing,
        "wb_cards_to_update": wb_rows, "wb_already_present": wb_already_present,
        "wb_no_exact_card": wb_missing,
    }


def execute(client: Client, plan: dict) -> dict:
    if VERIFICATION_PATH.exists():
        raise RuntimeError("Final readback already exists; no additional write is allowed")
    resuming = EXEC_PATH.exists()
    if resuming:
        execution = json.loads(EXEC_PATH.read_text(encoding="utf-8"))
        if execution.get("phase") != "ozon_created" or execution.get("number") != NUMBER:
            raise RuntimeError("Existing execution is not at the safe post-create reconciliation point")
    else:
        execution = {"started_at": now(), "phase": "preflight_complete", "number": NUMBER,
                     "plan_path": str(PLAN_PATH), "ozon": {}, "wb": {}}
        atomic(EXEC_PATH, execution)
    matching = plan["ozon_existing_matching_records"]
    if resuming:
        certificate_id = int(execution.get("ozon", {}).get("certificate_id") or 0)
        same_id = [item for item in matching if str(item.get("certificate_id")) == str(certificate_id)]
        if not certificate_id or len(same_id) != 1:
            raise RuntimeError("Fresh Ozon list did not reconcile the prior create by certificate ID")
    elif matching:
        cert = matching[0]
        if (str(cert.get("issue_date", ""))[:10] != ISSUE or str(cert.get("expire_date", ""))[:10] != EXPIRY
                or cert.get("accordance_type_code") != "EAEU"
                or cert.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
            raise RuntimeError("Existing Ozon record has conflicting dates, market, or status")
        certificate_id = int(cert["certificate_id"])
    else:
        seed = plan["targets"][0]
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
            raise RuntimeError("PDF hash changed after preflight")
        execution.update(phase="ozon_create_prepared", ozon={
            "request_path": "/v2/product/certificate/create", "target_count": len(plan["targets"]),
            "seed_offer": seed["offer_id"], "seed_sku": seed["sku"],
            "file_sha256": plan["source_file_sha256"],
        })
        atomic(EXEC_PATH, execution)
        try:
            response = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
        except Exception as exc:
            execution.update(phase="ozon_create_uncertain", error_type=type(exc).__name__, updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon create outcome is uncertain; reconcile by live listing before retry") from None
        states = [item.get("state") for item in response.get("params", []) if isinstance(item, dict)]
        certificate_id = int(response.get("certificate_id") or 0)
        execution["ozon"].update(create_response=response, certificate_id=certificate_id)
        if not certificate_id or response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
            execution.update(phase="ozon_create_not_validated", updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon create response was not fully valid; no additional binds sent")
        execution.update(phase="ozon_created", updated_at=now())
        atomic(EXEC_PATH, execution)

    live_records = list_ozon_certificates(client)
    live_record = next((item for item in live_records if str(item.get("certificate_id")) == str(certificate_id)), None)
    if not live_record or suffix(live_record.get("certificate_number")) != "01317/22":
        raise RuntimeError("Ozon list readback did not confirm certificate identity")
    lookup_number = str(live_record.get("certificate_number") or "")
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": lookup_number}).get("result") or {}
    if (int(info.get("certificate_id") or -1) != certificate_id
            or info.get("type_code") != TYPE_CODE
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or info.get("accordance_type_code") != "EAEU"
            or info.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        execution.update(phase="ozon_metadata_conflict", updated_at=now(), ozon_info=info)
        atomic(EXEC_PATH, execution)
        raise RuntimeError("Ozon live metadata differs from the verified FSA source")

    targets_by_sku = {x["sku"]: x for x in plan["targets"]}
    bindings = read_bindings(client, certificate_id)
    by_product = {str(x.get("product_id")): x for x in bindings}
    existing_skus = set()
    for target in plan["targets"]:
        prior = by_product.get(target["product_id"])
        if prior:
            if str(prior.get("sku")) != target["sku"]:
                raise RuntimeError(f"Ozon binding identity conflict for {target['offer_id']}")
            if prior.get("product_status_code") in {"declined", "rejected", "invalid"}:
                raise RuntimeError(f"Existing Ozon binding is declined for {target['offer_id']}")
            existing_skus.add(target["sku"])
    missing = [x["sku"] for x in plan["targets"] if x["sku"] not in existing_skus]
    if not matching:
        seed_sku = plan["targets"][0]["sku"]
        if seed_sku not in existing_skus:
            raise RuntimeError("Ozon create seed binding is not yet visible; wait for readback")
        missing = [sku for sku in missing if sku != seed_sku]
    if missing:
        execution.update(phase="ozon_bind_prepared", updated_at=now(), ozon={
            **execution.get("ozon", {}), "certificate_id": certificate_id,
            "initial_binding_count": len(bindings), "missing_skus": missing,
        })
        atomic(EXEC_PATH, execution)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": certificate_id, "skus": missing,
            }, mutation=True)
        except Exception as exc:
            execution.update(phase="ozon_bind_uncertain", error_type=type(exc).__name__, updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon bind outcome is uncertain; read live bindings before any retry") from None
        execution["ozon"]["bind_response"] = response
        if response.get("result") is not True:
            execution.update(phase="ozon_bind_rejected", updated_at=now())
            atomic(EXEC_PATH, execution)
            raise RuntimeError("Ozon rejected the bind request")
        execution.update(phase="ozon_bind_accepted", updated_at=now())
        atomic(EXEC_PATH, execution)

    final_info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": lookup_number}).get("result") or {}
    final_bindings = read_bindings(client, certificate_id)
    bound_by_product = {str(x.get("product_id")): x for x in final_bindings}
    binding_rows = []
    for target in plan["targets"]:
        entry = bound_by_product.get(target["product_id"])
        binding_rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                             "sku": target["sku"], "visible": bool(entry),
                             "identity_matches": bool(entry and str(entry.get("sku")) == target["sku"]),
                             "status": entry.get("product_status_code") if entry else None})
    if any(not x["visible"] or not x["identity_matches"] for x in binding_rows):
        execution.update(phase="ozon_readback_incomplete", updated_at=now(), ozon_info=final_info,
                         ozon_binding_readback=binding_rows)
        atomic(EXEC_PATH, execution)
        raise RuntimeError("Ozon did not show every expected product binding")
    execution.update(phase="ozon_readback_complete", updated_at=now(), ozon={
        **execution.get("ozon", {}), "certificate_id": certificate_id,
        "certificate_status": final_info.get("status_code"), "binding_count": len(final_bindings),
        "target_binding_readback": binding_rows,
    })
    atomic(EXEC_PATH, execution)

    updates = plan["wb_cards_to_update"]
    if updates:
        for row in updates:
            fresh = client.wb_cards(row["offer_id"])
            if len(fresh) != 1 or fresh[0].get("nmID") != row["nmID"]:
                raise RuntimeError(f"WB card identity changed before write for {row['offer_id']}")
            if str(fresh[0].get("brand") or "").strip().casefold() != "feron":
                raise RuntimeError(f"WB brand changed before write for {row['offer_id']}")
            row["payload"] = merge_wb(fresh[0], {
                "type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                "endDate": wb_datetime(EXPIRY), "isEndless": False,
            })
            row["before"] = fresh[0]
        payloads = [x["payload"] for x in updates if x["payload"] is not None]
        if payloads:
            execution.update(phase="wb_update_prepared", updated_at=now(), wb={
                "cards": [{"offer_id": x["offer_id"], "nmID": x["nmID"]} for x in updates],
                "documents": [{"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                               "endDate": wb_datetime(EXPIRY), "isEndless": False}],
            })
            atomic(EXEC_PATH, execution)
            try:
                response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
            except Exception as exc:
                execution.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
                atomic(EXEC_PATH, execution)
                raise RuntimeError("WB update outcome is uncertain; read cards before any retry") from None
            execution["wb"]["update_response"] = response
            if response.get("error") is not False:
                execution.update(phase="wb_update_rejected", updated_at=now())
                atomic(EXEC_PATH, execution)
                raise RuntimeError("WB rejected the document update")
            execution.update(phase="wb_update_accepted", updated_at=now())
            atomic(EXEC_PATH, execution)

    wb_readback = []
    verify_rows = {}
    for row in updates:
        verify_rows[row["offer_id"]] = {"nmID": row["nmID"], "before": row["before"]}
    for offer, row in plan["wb_exact_cards"].items():
        verify_rows.setdefault(offer, {"nmID": row["nmID"], "before": None})
    for offer, row in verify_rows.items():
        fresh = client.wb_cards(offer)
        exact = [d for d in (raw_wb_documents(fresh[0]) if len(fresh) == 1 else [])
                 if doc_key(d) == doc_key({"type": 1, "number": NUMBER})]
        correct_dates = any(str(d.get("startDate", ""))[:10] == ISSUE and
                            str(d.get("endDate", ""))[:10] == EXPIRY for d in exact)
        preserved = (row["before"] is None or
                     (len(fresh) == 1 and comparable_card(fresh[0]) == comparable_card(row["before"])))
        valid_verdict = any((d.get("verdict") or {}).get("verified") is True and
                            (d.get("verdict") or {}).get("reason") == "valid" for d in exact)
        wb_readback.append({"offer_id": offer, "nmID": row["nmID"],
                            "card_count": len(fresh), "document_visible": bool(exact),
                            "dates_match": correct_dates, "unrelated_fields_preserved": preserved,
                            "valid_wb_verdict": valid_verdict,
                            "verdict": ("valid" if valid_verdict and correct_dates and preserved else
                                        "visible_review_left_pending" if exact and correct_dates and preserved else
                                        "readback_incomplete"),
                            "documents": exact})
    if any(x["verdict"] not in {"valid", "visible_review_left_pending"} for x in wb_readback):
        execution.update(phase="wb_readback_incomplete", updated_at=now(), wb_readback=wb_readback)
        atomic(EXEC_PATH, execution)
        raise RuntimeError("WB card readback did not confirm every submitted document")

    result = {
        "checked_at": now(), "number": NUMBER, "ozon_certificate_id": certificate_id,
        "ozon_certificate_status": final_info.get("status_code"),
        "ozon_targets_expected": len(plan["targets"]), "ozon_targets_visible": len(binding_rows),
        "ozon_binding_status_counts": dict(collections.Counter(x["status"] for x in binding_rows)),
        "ozon_bindings": binding_rows, "wb_cards_submitted": len(updates),
        "wb_already_present_valid": sum(bool(x.get("valid_verdict")) for x in plan["wb_already_present"].values()),
        "wb_cards_readback": wb_readback,
        "wb_review_left_pending": any(x["verdict"] == "visible_review_left_pending" for x in wb_readback),
        "wb_exact_cards_missing": plan["wb_no_exact_card"],
        "local_pdf_deleted": False,
        "local_pdf_retained_reason": "Three target offers have no exact WB card; do not remove the source until cross-platform coverage is complete.",
    }
    atomic(VERIFICATION_PATH, result)
    execution.update(phase="complete", finished_at=now(), verification_path=str(VERIFICATION_PATH))
    atomic(EXEC_PATH, execution)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="perform the prepared Ozon and WB writes")
    args = parser.parse_args()
    client = Client()
    plan = preflight(client)
    atomic(PLAN_PATH, plan)
    print(json.dumps({
        "mode": "execute" if args.execute else "dry_run",
        "plan_path": str(PLAN_PATH), "number": NUMBER,
        "target_count": len(plan["targets"]),
        "ozon_existing_records": len(plan["ozon_existing_matching_records"]),
        "ozon_live_product_count": plan["ozon_products_verified"],
        "wb_cards_to_update": len(plan["wb_cards_to_update"]),
        "wb_documents_already_present": len(plan["wb_already_present"]),
        "wb_documents_with_valid_verdict": sum(bool(x.get("valid_verdict")) for x in plan["wb_already_present"].values()),
        "wb_no_exact_card": plan["wb_no_exact_card"],
        "source_file_sha256": plan["source_file_sha256"],
    }, ensure_ascii=False, indent=2))
    if args.execute:
        result = execute(client, plan)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
