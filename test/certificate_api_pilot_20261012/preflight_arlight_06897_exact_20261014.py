"""Fresh read-only preflight for Arlight EAEU declaration BY/112 ... 06897."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402

NUMBER = "ЕАЭС № BY/112 11.01. ТР037 004.02 06897"
NUMBER_END = "06897"
ISSUE = "2024-09-03"
EXPIRY = "2029-09-02"
TNVED = "8539519009"
SOURCE_SHA256 = "892f461d0071e290406b73b110bce2f29bb31099bca5106c0a463d6d689724d0"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
PDF = ROOT / "output_to_user/certificates/additional_search/brand_research/arlight/docs/5F2ED782CCE4CB4CBA510758C10E647A.pdf"
OFFICIAL_PDF_URL = "https://arlight.ru/upload/certificates/5F2ED782CCE4CB4CBA510758C10E647A.pdf"
EAEU_ODATA = "https://tech.eaeunion.org/odata/conformityDocDetailsType"
EAEU_VIEW = "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs/view/66d6d7ce30dcf805187f602c"
OUT = BASE / "arlight_06897_exact_live_preflight_20261014.json"
OZON_HOST = "https://api-seller.ozon.ru"
WB_HOST = "https://content-api.wildberries.ru"
WB_TNVED_CHAR_ID = 15000001


def norm(value: object) -> str:
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
                           "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                           "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(ch for ch in str(value or "").upper().translate(table) if ch.isalnum())


def save(data: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)


def api_post(client: Client, platform: str, path: str, payload: dict | list) -> tuple[int, dict]:
    host, headers = (OZON_HOST, client.ozon_headers) if platform == "ozon" else (WB_HOST, client.wb_headers)
    response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 120))
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    if response.status_code in (429, 500, 502, 503, 504):
        raise RuntimeError(f"{platform} read returned transient HTTP {response.status_code} for {path}")
    time.sleep(0.2 if platform == "ozon" else 0.55)
    return response.status_code, body


def read_assignments() -> tuple[list[dict], Path]:
    rows = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if NUMBER_END not in str(row.get("Номер/название документа") or ""):
                continue
            if row.get("Бренд подтвержденный") != "Arlight":
                continue
            if row.get("Статус покрытия артикула") != "есть официальный документ":
                continue
            if row.get("Применимость") != "Подтверждено источником":
                continue
            if norm(row.get("Тип документа")) not in {norm("Декларация ЕАЭС ТР 037/2016"), norm("Декларация о соответствии ЕАЭС 037/2016")}:
                continue
            if str(row.get("SHA256 фактический") or "").lower() != SOURCE_SHA256:
                raise RuntimeError("A confirmed source assignment has a different source-file hash")
            if str(row.get("SHA256 заявленный") or "").lower() != SOURCE_SHA256:
                raise RuntimeError("A confirmed source assignment has a different declared source hash")
            if NUMBER_END not in norm(row.get("Номер/название документа")):
                raise RuntimeError("A matched assignment has a different document number")
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer:
                raise RuntimeError("An exact source assignment has no seller article")
            rows.append(row)
    by_offer = {str(row["Артикул продавца"]): row for row in rows}
    if len(by_offer) != len(rows) or not by_offer:
        raise RuntimeError("Exact local source assignment list is empty or duplicated")
    source_paths = {str(row.get("Локальный файл") or "") for row in rows}
    if len(source_paths) != 1:
        raise RuntimeError("Exact assignments disagree on local source file")
    source_path = ROOT / next(iter(source_paths))
    if not source_path.is_file() or hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Local source PDF is missing or changed")
    return [by_offer[k] for k in sorted(by_offer)], source_path


def live_eaeu_record(client: Client) -> dict:
    query = urlencode({"$filter": f"docId eq '{NUMBER}'", "$top": "1"})
    response = client.http.get(EAEU_ODATA + "?" + query, headers={"Accept": "application/json"}, timeout=(15, 60))
    if response.status_code != 200:
        raise RuntimeError(f"Official EAEU live lookup returned HTTP {response.status_code}")
    body = response.json()
    rows = body.get("value")
    if not isinstance(rows, list) or len(rows) != 1 or norm(rows[0].get("docId")) != norm(NUMBER):
        raise RuntimeError("Official EAEU record is missing or ambiguous")
    return rows[0]


def read_ozon_offers(client: Client, offers: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    products: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        status, body = api_post(client, "ozon", "/v3/product/info/list", {"offer_id": offers[start:start + 100]})
        if status != 200:
            raise RuntimeError(f"Ozon product list returned HTTP {status}")
        rows = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(rows, list):
            raise RuntimeError("Ozon product list response is malformed")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in offers or offer in products:
                raise RuntimeError("Ozon product list returned an unexpected or duplicate offer")
            products[offer] = row
    if set(products) != set(offers):
        raise RuntimeError(f"Ozon current identity lookup incomplete: {len(products)}/{len(offers)}")

    attrs: dict[str, dict] = {}
    for start in range(0, len(offers), 50):
        batch = offers[start:start + 50]
        status, body = api_post(client, "ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": batch}, "limit": 100})
        if status != 200:
            raise RuntimeError(f"Ozon attribute lookup returned HTTP {status}")
        rows = body.get("result") or body.get("items")
        if not isinstance(rows, list):
            raise RuntimeError("Ozon attribute response is malformed")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in attrs:
                raise RuntimeError("Ozon attribute response returned an unexpected or duplicate offer")
            attrs[offer] = {str(x.get("id")): x for x in row.get("attributes") or []}
    if set(attrs) != set(offers):
        raise RuntimeError(f"Ozon current attribute lookup incomplete: {len(attrs)}/{len(offers)}")
    return products, attrs


def read_ozon_certificates(client: Client) -> list[dict]:
    records = []
    for page in range(1, 101):
        status, body = api_post(client, "ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        if status != 200:
            raise RuntimeError(f"Ozon certificate list returned HTTP {status}")
        batch = (body.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list response is malformed")
        records.extend(batch)
        if len(batch) < 100:
            ids = [str(x.get("certificate_id") or "") for x in records]
            if len(ids) != len(set(ids)):
                raise RuntimeError("Ozon certificate list contains duplicate IDs")
            return records
    raise RuntimeError("Ozon certificate list pagination exceeded 100 pages")


def live_ozon_number_lookup(client: Client) -> dict:
    status, body = api_post(client, "ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER})
    if status == 404 and body.get("code") == 5:
        return {"http_status": status, "error_code": body.get("code"), "exact_record_absent": True}
    if status == 200 and isinstance(body.get("result"), dict):
        result = body["result"]
        return {"http_status": status, "exact_record_absent": False,
                "certificate_id": result.get("certificate_id"), "status_code": result.get("status_code"),
                "type_code": result.get("type_code"), "certificate_number": result.get("certificate_number"),
                "issue_date": result.get("issue_date"), "expire_date": result.get("expire_date")}
    return {"http_status": status, "exact_record_absent": False, "body": body}


def read_wb_cards(client: Client, offer: str) -> list[dict]:
    cards = []
    cursor: dict = {"limit": 100}
    seen: set[tuple[str, str]] = set()
    for _ in range(100):
        status, body = api_post(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer}}})
        if status != 200 or body.get("error"):
            raise RuntimeError(f"WB card lookup failed for {offer}: HTTP {status}")
        batch = body.get("cards")
        if not isinstance(batch, list):
            raise RuntimeError(f"WB card lookup malformed for {offer}")
        cards.extend(x for x in batch if str(x.get("vendorCode") or "") == offer)
        returned = body.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError(f"WB cursor page count mismatch for {offer}")
        if len(batch) < 100:
            return cards
        signature = (str(returned.get("updatedAt") or ""), str(returned.get("nmID") or ""))
        if not all(signature) or signature in seen:
            raise RuntimeError(f"WB cursor repeated or incomplete for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": int(signature[1])}
    raise RuntimeError(f"WB card pagination exceeded for {offer}")


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"Preflight output already exists; inspect before overwriting: {OUT}")
    rows, source_path = read_assignments()
    offers = [str(row["Артикул продавца"]) for row in rows]
    source_docs = [{"offer_id": str(row["Артикул продавца"]),
                    "source_evidence": row.get("Основание сопоставления"),
                    "source_url": row.get("URL карточки/основания"),
                    "ozon_assignment_name": row.get("Название товара Ozon"),
                    "source_pdf_path": row.get("Локальный файл")} for row in rows]
    client = Client()
    registry = live_eaeu_record(client)
    product_details, attrs = read_ozon_offers(client, offers)
    ozon_records = read_ozon_certificates(client)
    exact_records = [x for x in ozon_records if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    exact_lookup = live_ozon_number_lookup(client)

    targets = []
    for offer in offers:
        product = product_details[offer]
        attr = attrs[offer]
        brand = [str(v.get("value") or "") for v in (attr.get("85") or {}).get("values") or []]
        raw_codes = [str(v.get("value") or "") for v in (attr.get("22232") or {}).get("values") or []]
        codes = sorted({v.split(" - ", 1)[0].strip() for v in raw_codes if v.strip()})
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        wb_cards = read_wb_cards(client, offer)
        wb_summary = []
        for card in wb_cards:
            tnved_values = [str(v) for char in card.get("characteristics") or []
                            if str(char.get("id")) == str(WB_TNVED_CHAR_ID)
                            for v in char.get("value") or []]
            wb_codes = sorted({v.split(" ", 1)[0].strip() for v in tnved_values if v.strip()})
            doc_container = card.get("documents") or card.get("docs") or {}
            docs = doc_container.get("items") or []
            matching_docs = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
            wb_summary.append({
                "nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                "brand": card.get("brand"), "title": card.get("title"), "tnved_values": tnved_values,
                "tnved_codes": wb_codes, "excludeDocuments": doc_container.get("excludeDocuments"),
                "existing_06897_rows": matching_docs,
                "other_documents": docs,
                "wb_card_raw": card,
            })
        targets.append({
            "offer_id": offer, "product_id": product_id, "sku": sku,
            "ozon_name": product.get("name"), "ozon_brand_values": brand,
            "ozon_tnved_values": raw_codes, "ozon_tnved_codes": codes,
            "is_archived": product.get("is_archived"), "wb_cards": wb_summary,
        })

    exact_wb_docs = [card for target in targets for card in target["wb_cards"]
                     if card["existing_06897_rows"]]
    wb_nmid_list = [card["nmID"] for target in targets for card in target["wb_cards"]]
    code_counter = collections.Counter(code for target in targets for code in target["ozon_tnved_codes"])
    wb_verdicts = collections.Counter()
    for target in targets:
        for card in target["wb_cards"]:
            for doc in card["existing_06897_rows"]:
                verdict = doc.get("verdict") or {}
                wb_verdicts[str(verdict.get("reason") or verdict.get("status") or "NO_VERDICT")] += 1

    errors = []
    doc_status = (registry.get("docStatusDetails") or {}).get("docStatusCode")
    start_date = str((registry.get("docStatusDetails") or {}).get("startDate") or "")[:10]
    end_date = str((registry.get("docStatusDetails") or {}).get("endDate") or "")[:10]
    if doc_status != "01" or start_date != ISSUE or end_date != EXPIRY:
        errors.append("official_eaeu_status_or_dates_conflict")
    if str(registry.get("docId") or "") != NUMBER:
        errors.append("official_eaeu_number_conflict")
    if not any(TNVED in (p.get("commodityCode") or []) for p in ((registry.get("technicalRegulationObjectDetails") or {}).get("productDetails") or [])):
        errors.append("official_eaeu_tnved_missing")
    if len(exact_records) > 1:
        errors.append("multiple_exact_ozon_records")
    if exact_records and exact_lookup.get("exact_record_absent"):
        errors.append("ozon_record_lookup_conflicts_with_list")
    if not exact_records and not exact_lookup.get("exact_record_absent"):
        errors.append("ozon_exact_record_absence_not_confirmed")
    identities = [(x["product_id"], x["sku"]) for x in targets]
    if any(not a or not b or b == "0" for a, b in identities) or len(identities) != len(set(identities)):
        errors.append("ozon_product_sku_identity_missing_or_duplicate")
    if any(x["is_archived"] is not False for x in targets):
        errors.append("ozon_target_not_active")
    if any(x["ozon_brand_values"] != ["Arlight"] for x in targets):
        errors.append("ozon_brand_mismatch")
    if any(x["ozon_tnved_codes"] != [TNVED] for x in targets):
        errors.append("ozon_tnved_mismatch")
    if len(wb_nmid_list) != len(set(wb_nmid_list)):
        errors.append("duplicate_wb_nmid")
    if any(len(x["wb_cards"]) != 1 for x in targets):
        errors.append("wb_card_missing_or_ambiguous")
    for target in targets:
        for card in target["wb_cards"]:
            if card["brand"] != "Arlight" or card["vendorCode"] != target["offer_id"]:
                errors.append("wb_brand_or_offer_mismatch:" + target["offer_id"])
            if card["tnved_codes"] != [TNVED]:
                errors.append("wb_tnved_mismatch:" + target["offer_id"])
            if card["excludeDocuments"] is not False:
                errors.append("wb_documents_excluded_or_flag_missing:" + target["offer_id"])
            if len(card["existing_06897_rows"]) > 1:
                errors.append("wb_duplicate_target_document:" + target["offer_id"])
    if len({str(x.get("nmID") or "") for target in targets for x in target["wb_cards"]}) != len(wb_nmid_list):
        errors.append("wb_nmid_missing")

    result = {
        "checked_at_utc": now(), "read_only": True, "marketplace_mutation_allowed": False,
        "number": NUMBER, "document_type": "declaration", "accordance_type": "EAEU",
        "issue_date": ISSUE, "expiry_date": EXPIRY, "tnved_scope": [TNVED],
        "official_eaeu_record_url": EAEU_VIEW, "official_eaeu_live_record": registry,
        "source_pdf": {"path": str(source_path), "bytes": source_path.stat().st_size,
                       "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                       "official_download_url": OFFICIAL_PDF_URL,
                       "ocr_visual_check": "macOS Vision OCR matched number 06897, applicant/manufacturer Arlight i K, series RT/RTW/S2, code 8539519009, serial release, dates 2024-09-03 to 2029-09-02; no sample-date limitation printed"},
        "source_assignment_count": len(rows), "source_assignments": source_docs,
        "ozon_certificate_list_count": len(ozon_records), "ozon_exact_records": exact_records,
        "ozon_exact_info_lookup": exact_lookup,
        "ozon_tnved_counts": dict(code_counter),
        "wb_matching_document_count": len(exact_wb_docs), "wb_matching_verdict_reasons": dict(wb_verdicts),
        "targets": targets, "preflight_eligible": not errors, "errors": sorted(set(errors)),
    }
    save(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("targets", "source_assignments", "official_eaeu_live_record")}, ensure_ascii=False, indent=2))
    print("TARGETS", json.dumps([{k: v for k, v in x.items() if k != "wb_cards"} | {
        "wb_cards": [{k: c[k] for k in ("nmID", "brand", "title", "tnved_codes", "excludeDocuments", "existing_06897_rows")} for c in x["wb_cards"]]
    } for x in targets], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
