"""Fresh read-only audit for the exact Arlight declaration 05783 cohort."""
from __future__ import annotations

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

NUMBER = "ЕАЭС № BY/112 11.01. ТР037 004.02 05783"
ISSUE = "2024-03-14"
EXPIRY = "2029-03-13"
TNVED = "8539519009"
SOURCE_SHA256 = "2cd0a432b044d6e2b9dd19ee2507dd771ff0c4127b2ee06d8a4bbd39898c15a8"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/FD89310560D43042A1417AC15C491663.pdf"
OFFICIAL_PDF_URL = "https://arlight.ru/upload/certificates/FD89310560D43042A1417AC15C491663.pdf"
EAEU_ODATA = "https://tech.eaeunion.org/odata/conformityDocDetailsType"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
WB_CATALOG = BASE / "wb_catalog_minimal_live_20261014.json"
OUT = BASE / "arlight_05783_fresh_live_preflight_20261014.json"
EXCLUDED_V2 = {"031884(2)-1", "031900(2)-1", "031901(2)-1"}
WB_TNVED_CHAR_ID = "15000001"
WB_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
             "characteristics", "sizes", "kizMarked", "gtin")
TRANS = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
                       "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                       "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D",
                       "П": "P"})


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(TRANS) if ch.isalnum())


def post(client: Client, platform: str, path: str, payload: dict, interval: float = 0.2):
    host, headers = (("https://api-seller.ozon.ru", client.ozon_headers) if platform == "ozon"
                     else ("https://content-api.wildberries.ru", client.wb_headers))
    for attempt in range(5):
        response = client.http.post(host + path, json=payload, headers=headers, timeout=(15, 120))
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(min(2 ** (attempt + 1), 30))
            continue
        try:
            body = response.json()
        except ValueError:
            body = {"non_json_response": True}
        time.sleep(interval)
        return response.status_code, body
    raise RuntimeError("Read retry limit reached")


def read_wb(client: Client, offer: str) -> list[dict]:
    cards, cursor, seen = [], {"limit": 100}, set()
    for _ in range(100):
        status, body = post(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer},
        }}, interval=1.05)
        if status != 200 or body.get("error") or not isinstance(body.get("cards"), list):
            raise RuntimeError(f"WB full-card read failed for {offer}: HTTP {status}")
        batch = body["cards"]
        returned = body.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError(f"WB page count mismatch for {offer}")
        cards.extend(c for c in batch if str(c.get("vendorCode") or "") == offer)
        if len(batch) < 100:
            return cards
        signature = (str(returned.get("updatedAt") or ""), str(returned.get("nmID") or ""))
        if not all(signature) or signature in seen:
            raise RuntimeError(f"WB pagination repeated for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": int(signature[1])}
    raise RuntimeError(f"WB card pagination exceeded for {offer}")


def attr_values(row: dict, attribute_id: str) -> list[str]:
    return [str(v.get("value") or "") for a in (row.get("attributes") or [])
            if str(a.get("id")) == attribute_id for v in (a.get("values") or [])
            if v.get("value") not in (None, "")]


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"Preflight already exists; inspect it before replacing: {OUT}")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Local declaration PDF is missing or its SHA-256 changed")

    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        all_rows = list(csv.DictReader(stream))
    assigned = [r for r in all_rows
                if r.get("SHA256 фактический", "").lower() == SOURCE_SHA256
                and r.get("Номер/название документа") == "809001271"
                and r.get("Применимость") == "Подтверждено статусом покрытия"]
    by_offer = {str(r.get("Артикул продавца") or "").strip(): r for r in assigned}
    if len(assigned) != 21 or len(by_offer) != 21 or "" in by_offer:
        raise RuntimeError(f"Expected 21 exact-source assignments, found {len(assigned)}")
    offers = sorted(by_offer)
    if any("(2)" in x for x in offers) or any("COB" not in str(by_offer[x].get("Название товара Ozon") or "").upper() for x in offers):
        raise RuntimeError("Exact source assignments include a different COB revision/family")
    excluded_assignments = [r for r in all_rows
                            if str(r.get("Артикул продавца") or "") in EXCLUDED_V2
                            and norm(r.get("Номер/название документа")).endswith("05783")
                            and r.get("Применимость") == "Кандидат; не засчитывается как документ соответствия"]
    if {str(r.get("Артикул продавца")) for r in excluded_assignments} != EXCLUDED_V2:
        raise RuntimeError("The three excluded revision-(2) offers no longer match the source audit")

    client = Client()
    registry_query = urlencode({"$filter": f"docId eq '{NUMBER}'", "$top": "1"})
    registry_response = client.http.get(EAEU_ODATA + "?" + registry_query,
                                        headers={"Accept": "application/json"}, timeout=(15, 60))
    registry_response.raise_for_status()
    registry_body = registry_response.json()
    registry_rows = registry_body.get("value") or []
    if len(registry_rows) != 1 or norm(registry_rows[0].get("docId")) != norm(NUMBER):
        raise RuntimeError("Official EAEU live lookup is absent or ambiguous")
    registry = registry_rows[0]
    official_pdf_response = client.http.get(OFFICIAL_PDF_URL, timeout=(15, 120))
    official_pdf_response.raise_for_status()
    official_pdf_sha = hashlib.sha256(official_pdf_response.content).hexdigest()

    product_rows: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        status, body = post(client, "ozon", "/v3/product/info/list", {"offer_id": batch})
        result = body.get("items") or (body.get("result") or {}).get("items")
        if status != 200 or not isinstance(result, list):
            raise RuntimeError(f"Ozon exact product read failed: HTTP {status}")
        for row in result:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in product_rows:
                raise RuntimeError("Ozon product read returned unexpected/duplicate offer")
            product_rows[offer] = row
    if set(product_rows) != set(offers):
        raise RuntimeError(f"Ozon product identity read incomplete: {len(product_rows)}/{len(offers)}")

    attrs_by_offer: dict[str, dict] = {}
    status, body = post(client, "ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": 100})
    attr_rows = body.get("result") or body.get("items")
    if status != 200 or not isinstance(attr_rows, list):
        raise RuntimeError(f"Ozon compliance attribute read failed: HTTP {status}")
    for row in attr_rows:
        offer = str(row.get("offer_id") or "")
        if offer not in offers or offer in attrs_by_offer:
            raise RuntimeError("Ozon attributes returned unexpected/duplicate offer")
        attrs_by_offer[offer] = row
    if set(attrs_by_offer) != set(offers):
        raise RuntimeError(f"Ozon attribute read incomplete: {len(attrs_by_offer)}/{len(offers)}")

    certs = []
    for page in range(1, 101):
        status, body = post(client, "ozon", "/v1/product/certificate/list",
                            {"page": page, "page_size": 100})
        batch = ((body.get("result") or {}).get("certificates"))
        if status != 200 or not isinstance(batch, list):
            raise RuntimeError(f"Ozon certificate list read failed: HTTP {status}")
        certs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate list exceeded 100 pages")
    exact_records = [c for c in certs if norm(c.get("certificate_number") or c.get("number")) == norm(NUMBER)]
    if len(exact_records) > 1:
        raise RuntimeError("Duplicate 05783 certificate records already exist on Ozon")

    wb_targets, wb_exclusions = [], []
    for offer in offers + sorted(EXCLUDED_V2):
        cards = read_wb(client, offer)
        row = by_offer.get(offer)
        exact_cards = []
        for card in cards:
            container = card.get("documents") or card.get("docs") or {}
            docs = container.get("items") or []
            codes = sorted({str(v).split(" ", 1)[0].strip()
                            for c in (card.get("characteristics") or [])
                            if str(c.get("id")) == WB_TNVED_CHAR_ID
                            for v in (c.get("value") or []) if str(v).strip()})
            exact_cards.append({
                "nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
                "brand": card.get("brand"), "title": card.get("title"), "tnved_codes": codes,
                "excludeDocuments": container.get("excludeDocuments"),
                "matching_05783_rows": [d for d in docs if norm(d.get("number")) == norm(NUMBER)],
                "existing_documents": docs,
                "wb_card_raw": card,
            })
        if offer in EXCLUDED_V2:
            wb_exclusions.append({"offer_id": offer, "cards": exact_cards})
        else:
            prod = product_rows[offer]
            attr = attrs_by_offer[offer]
            product_id = str(prod.get("id") or prod.get("product_id") or "")
            ozon_brand = attr_values(attr, "85")
            ozon_tnved = attr_values(attr, "22232")
            wb_targets.append({
                "offer_id": offer, "product_id": product_id, "sku": str(prod.get("sku") or ""),
                "is_archived": prod.get("is_archived"), "ozon_name": prod.get("name"),
                "ozon_brand_values": ozon_brand, "ozon_tnved_values": ozon_tnved,
                "assignment_evidence": row.get("Основание сопоставления"),
                "assignment_source_url": row.get("URL карточки/основания"),
                "assignment_document_key": row.get("Номер/название документа"),
                "wb_cards": exact_cards,
            })

    product_details = registry.get("technicalRegulationObjectDetails") or {}
    product_scope = product_details.get("productDetails") or []
    tnved_scope = sorted({str(code) for p in product_scope for code in (p.get("commodityCode") or [])})
    wb_catalog = json.loads(WB_CATALOG.read_text(encoding="utf-8"))
    wb_by_offer = {str(c.get("vendorCode") or ""): c for c in wb_catalog.get("cards") or []}
    summary = {
        "target_offers": len(wb_targets),
        "ozon_exact_active_brand_scope_count": sum(
            x["is_archived"] is False and "arlight" in {b.casefold() for b in x["ozon_brand_values"]}
            and any(v.split(" - ", 1)[0].strip() == TNVED for v in x["ozon_tnved_values"])
            for x in wb_targets),
        "ozon_target_pairs": len({(x["product_id"], x["sku"]) for x in wb_targets}),
        "wb_exact_card_count": sum(len(x["wb_cards"]) for x in wb_targets),
        "wb_cards_with_exact_scope_code": sum(TNVED in c["tnved_codes"] for x in wb_targets for c in x["wb_cards"]),
        "wb_document_rows_already_present": sum(bool(c["matching_05783_rows"]) for x in wb_targets for c in x["wb_cards"]),
        "excluded_v2_offers": len(wb_exclusions),
        "excluded_v2_wb_card_count": sum(len(x["cards"]) for x in wb_exclusions),
        "ozon_exact_document_record_count": len(exact_records),
        "wb_full_catalog_exact_target_count": sum(o in wb_by_offer for o in offers),
    }
    errors = []
    status_details = registry.get("docStatusDetails") or {}
    if registry.get("docId") != NUMBER:
        errors.append("official_registry_number_mismatch")
    if status_details.get("docStatusCode") != "01":
        errors.append("official_registry_not_active")
    if str(registry.get("docStartDate") or "")[:10] != ISSUE or str(registry.get("docValidityDate") or "")[:10] != EXPIRY:
        errors.append("official_registry_dates_mismatch")
    if TNVED not in tnved_scope or official_pdf_sha != SOURCE_SHA256:
        errors.append("official_scope_or_pdf_hash_mismatch")
    if summary["ozon_exact_active_brand_scope_count"] != len(wb_targets):
        errors.append("ozon_brand_tnved_active_preflight_incomplete")
    if summary["wb_exact_card_count"] != 20:
        errors.append("wb_exact_card_count_not_20")
    if summary["wb_document_rows_already_present"]:
        errors.append("some_wb_target_document_rows_already_exist_reconcile")
    if summary["ozon_exact_document_record_count"]:
        errors.append("ozon_exact_document_record_already_exists_reconcile")
    for target in wb_targets:
        if not target["product_id"] or not target["sku"]:
            errors.append("ozon_product_id_or_sku_missing:" + target["offer_id"])
        if len(target["wb_cards"]) > 1:
            errors.append("duplicate_wb_cards:" + target["offer_id"])
        for card in target["wb_cards"]:
            if card["brand"] != "Arlight" or card["excludeDocuments"] is True:
                errors.append("wb_brand_or_document_exclusion_blocker:" + target["offer_id"])
    result = {
        "checked_at_utc": now(), "read_only": True, "complete": True,
        "number": NUMBER, "issue_date": ISSUE, "expiry_date": EXPIRY,
        "official_registry_url": "https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs/view/" + str(registry.get("Id")) + "/common",
        "official_registry_record": registry,
        "official_pdf_url": OFFICIAL_PDF_URL,
        "source_pdf": {"path": str(SOURCE), "sha256": SOURCE_SHA256,
                       "official_download_sha256": official_pdf_sha, "bytes": SOURCE.stat().st_size},
        "official_product_scope": {"product_details": product_scope, "tnved_codes": tnved_scope},
        "ozon_exact_certificate_records": exact_records,
        "targets": wb_targets, "excluded_v2": wb_exclusions,
        "summary": summary, "errors": sorted(set(errors)),
        "eligible_for_write": not errors,
    }
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({"checked_at_utc": result["checked_at_utc"], "summary": summary,
                      "official_registry_status": status_details.get("docStatusCode"),
                      "official_pdf_match": official_pdf_sha == SOURCE_SHA256,
                      "eligible_for_write": result["eligible_for_write"], "errors": result["errors"],
                      "wb_missing_exact_offers": [x["offer_id"] for x in wb_targets if not x["wb_cards"]]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
