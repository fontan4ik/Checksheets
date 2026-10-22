"""Fresh read-only preflight for Arlight certificate 03451/22."""
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
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, norm_number,
)

PDF = ROOT / "output_to_user/certificates/group_1/documents/arlight/772DD20BAEF0AD4FA297663655BFAC3A.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OZON_SNAPSHOT = HERE / "all_found_ozon_products_snapshot_20261014.json"
WB_SNAPSHOT = HERE / "all_found_wb_cards_snapshot_20261014.json"
OUT = HERE / "arlight_03451_preflight_live_20261021.json"
NUMBER = "ЕАЭС RU С-HK.НА46.В.03451/22"
ISSUE = "2022-04-16"
EXPIRY = "2027-04-15"
TNVED = "8504408300"
BRAND = "Arlight"
PDF_SHA256 = "22f5bd0657cf8c55754b3bd0d73d102de1b9520d6c167242555ae63349398add"
EXPECTED_ROWS = 462


def save(value: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)


def attr_values(row: dict, attr_id: int) -> list[str]:
    for attr in row.get("attributes") or []:
        if str(attr.get("id")) == str(attr_id):
            return [str(v.get("value")) for v in attr.get("values") or []
                    if v.get("value") not in (None, "")]
    return []


def wb_tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values.extend(str(v or "").split(" - ", 1)[0].strip()
                      for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(values))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists")
    digest = hashlib.sha256(PDF.read_bytes()).hexdigest()
    if digest != PDF_SHA256:
        raise RuntimeError("source_pdf_sha256_changed")
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        all_rows = list(csv.DictReader(stream))
    rows = [r for r in all_rows if str(r.get("SHA256 фактический") or "").lower() == digest]
    by_offer: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_offer[str(row.get("Артикул продавца") or "")].append(row)
    offers = sorted(by_offer)
    if len(rows) != EXPECTED_ROWS or len(offers) != EXPECTED_ROWS or "" in by_offer:
        raise RuntimeError(f"unexpected_source_assignment_counts:{len(rows)}:{len(offers)}")
    for offer, assigned in by_offer.items():
        if any((r.get("Бренд подтвержденный") or r.get("Бренд Ozon")) != BRAND for r in assigned):
            raise RuntimeError(f"assignment_brand_mismatch:{offer}")
        if any(norm_number(r.get("Номер/название документа")) != norm_number(NUMBER) for r in assigned):
            raise RuntimeError(f"assignment_number_mismatch:{offer}")
        if any(not str(r.get("URL документа") or "").startswith("https://arlight.ru/") for r in assigned):
            raise RuntimeError(f"non_manufacturer_source_url:{offer}")

    ozon_snapshot = json.loads(OZON_SNAPSHOT.read_text(encoding="utf-8"))
    wb_snapshot = json.loads(WB_SNAPSHOT.read_text(encoding="utf-8"))
    if not ozon_snapshot.get("complete") or not wb_snapshot.get("complete"):
        raise RuntimeError("complete_recent_marketplace_snapshots_required")
    ozon_time = dt.datetime.fromisoformat(str(ozon_snapshot["checked_at"]).replace("Z", "+00:00"))
    wb_time = dt.datetime.fromisoformat(str(wb_snapshot["checked_at"]).replace("Z", "+00:00"))
    if any((dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() > 7200
           for stamp in (ozon_time, wb_time)):
        raise RuntimeError("marketplace_snapshot_too_old")
    initial_products = {str(p.get("offer_id") or ""): p
                        for p in ozon_snapshot.get("products") or []}
    if any(offer not in initial_products for offer in offers):
        raise RuntimeError("source_offer_missing_from_recent_ozon_snapshot")
    initial_cards: dict[str, list[dict]] = collections.defaultdict(list)
    for card in wb_snapshot.get("cards") or []:
        offer = str(card.get("vendorCode") or "")
        if offer in by_offer:
            initial_cards[offer].append(card)

    client = Client()
    products_by_id: dict[str, dict] = {}
    product_ids = sorted({str(initial_products[o].get("product_id") or initial_products[o].get("id") or "")
                          for o in offers})
    if "" in product_ids:
        raise RuntimeError("missing_product_id_in_snapshot")
    for offset in range(0, len(product_ids), 500):
        batch = product_ids[offset:offset + 500]
        result = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch]
        }).get("items")
        if not isinstance(result, list):
            raise RuntimeError("ozon_product_details_missing")
        for item in result:
            pid = str(item.get("product_id") or item.get("id") or "")
            if pid not in batch or pid in products_by_id:
                raise RuntimeError("ozon_product_detail_identity_mismatch")
            products_by_id[pid] = item
    if set(products_by_id) != set(product_ids):
        raise RuntimeError("ozon_product_details_incomplete")

    attributes_by_offer: dict[str, dict] = {}
    for offset in range(0, len(offers), 100):
        batch = offers[offset:offset + 100]
        result = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result")
        if not isinstance(result, list):
            raise RuntimeError("ozon_attributes_missing")
        for item in result:
            offer = str(item.get("offer_id") or "")
            if offer not in batch or offer in attributes_by_offer:
                raise RuntimeError("ozon_attribute_offer_mismatch")
            attributes_by_offer[offer] = item
    if set(attributes_by_offer) != set(offers):
        raise RuntimeError("ozon_attributes_incomplete")

    ozon_rows = []
    for offer in offers:
        old = initial_products[offer]
        pid = str(old.get("product_id") or old.get("id") or "")
        detail = products_by_id[pid]
        attr = attributes_by_offer[offer]
        sku = str(detail.get("sku") or "")
        identity = (str(detail.get("offer_id") or "") == offer
                    and str(detail.get("product_id") or detail.get("id") or "") == pid
                    and str(attr.get("offer_id") or "") == offer
                    and str(attr.get("id") or attr.get("product_id") or "") == pid
                    and sku == str(old.get("sku") or "") and bool(sku))
        brands = attr_values(attr, 85)
        codes_raw = attr_values(attr, 22232)
        codes = sorted({v.split(" - ", 1)[0].strip() for v in codes_raw if v.strip()})
        ozon_rows.append({
            "offer_id": offer, "product_id": pid, "sku": sku, "identity_matches": identity,
            "brand_values": brands, "tnved_values": codes_raw,
            "tnved_codes": codes,
            "in_scope": identity and not detail.get("is_archived")
                        and len(brands) == 1 and brands[0].strip().casefold() == BRAND.casefold()
                        and codes == [TNVED],
            "product_name": detail.get("name") or detail.get("name_ru"),
        })

    # Recheck the full Ozon document list and normalized exact lookup before any write.
    certificate_rows = []
    page = 1
    pages = 1
    seen_ids = set()
    while page <= pages:
        body = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        for row in batch:
            cid = int(row.get("certificate_id") or 0)
            if not cid or cid in seen_ids:
                raise RuntimeError("ozon_certificate_id_missing_or_duplicate")
            seen_ids.add(cid)
        certificate_rows.extend(batch)
        pages = int(body.get("page_count") or page)
        page += 1
    normalized_matches = [c for c in certificate_rows
                          if norm_number(c.get("certificate_number")) == norm_number(NUMBER)]
    payload = {"certificate_number": NUMBER}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    entry = {"started_at": now(), "platform": "ozon", "path": "/v1/product/certificate/info",
             "mutation": False, "request_sha256": hashlib.sha256(encoded).hexdigest(),
             "request_bytes": len(encoded)}
    log = API / "api_calls.jsonl"
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**entry, "phase": "prepared"}, ensure_ascii=False) + "\n")
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=encoded, headers=client.ozon_headers, timeout=(15, 60))
    try:
        exact_info = response.json()
    except ValueError:
        exact_info = {"non_json_response": True}
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**entry, "phase": "response", "http_status": response.status_code,
                                 "body": exact_info, "finished_at": now()}, ensure_ascii=False) + "\n")
    exact_absence_confirmed = (response.status_code == 404 and isinstance(exact_info, dict)
                               and exact_info.get("code") == 5
                               and "not found" in str(exact_info.get("message") or "").casefold()
                               and NUMBER in str(exact_info.get("message") or ""))
    if response.status_code == 200 or normalized_matches or not exact_absence_confirmed:
        raise RuntimeError("ozon_exact_record_absence_not_confirmed")

    # Use the recent complete catalog to avoid writes to absent/duplicate cards, then
    # refresh every exact Arlight/TN VED match individually before considering it safe.
    wb_rows = []
    candidates = []
    for offer in offers:
        cards = initial_cards.get(offer, [])
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "snapshot_card_count": len(cards), "in_scope": False,
                            "reason": "wb_card_missing_or_duplicate"})
            continue
        card = cards[0]
        codes = wb_tnved(card)
        if str(card.get("brand") or "").strip().casefold() != BRAND.casefold() or codes != [TNVED]:
            wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                            "brand": card.get("brand"), "tnved_codes": codes,
                            "in_scope": False, "reason": "wb_brand_or_tnved_conflict"})
            continue
        candidates.append((offer, card))
    for index, (offer, old_card) in enumerate(candidates, 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "snapshot_nmID": str(old_card.get("nmID") or ""),
                            "live_card_count": len(cards), "in_scope": False,
                            "reason": "live_wb_card_missing_or_duplicate"})
            continue
        card = cards[0]
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if int(d.get("type") or 0) == 1
                 and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY
                 and d.get("isEndless") is False]
        identity = (str(card.get("vendorCode") or "") == offer
                    and str(card.get("nmID") or "") == str(old_card.get("nmID") or ""))
        code_now = wb_tnved(card)
        brand_now = str(card.get("brand") or "").strip()
        if not identity or brand_now.casefold() != BRAND.casefold() or code_now != [TNVED]:
            reason = "live_wb_identity_brand_or_tnved_changed"
        elif same and len(exact) == 1:
            reason = "already_exact_document_present"
        elif same:
            reason = "existing_document_number_conflicts"
        else:
            reason = "eligible_for_add"
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "brand": brand_now, "tnved_codes": code_now, "identity_matches": identity,
                        "matching_number_docs": len(same), "exact_matching_docs": len(exact),
                        "current_documents": docs, "in_scope": identity and brand_now.casefold() == BRAND.casefold()
                        and code_now == [TNVED], "reason": reason})
        if index % 50 == 0:
            print(json.dumps({"phase": "fresh_wb_card_recheck", "checked": index,
                              "candidates": len(candidates)}, ensure_ascii=False), flush=True)

    ozon_counts = collections.Counter("in_scope" if r["in_scope"] else "out_of_scope_or_unconfirmed"
                                      for r in ozon_rows)
    wb_reason_counts = collections.Counter(r.get("reason") for r in wb_rows)
    eligible_ozon = [r for r in ozon_rows if r["in_scope"]]
    eligible_wb = [r for r in wb_rows if r.get("reason") == "eligible_for_add"]
    result = {
        "checked_at": now(), "read_only": True, "certificate_number": NUMBER,
        "source_pdf": str(PDF), "source_pdf_sha256": digest,
        "manufacturer_source_url": "https://arlight.ru/upload/certificates/772DD20BAEF0AD4FA297663655BFAC3A.pdf",
        "fsa_certificate_issue_date": ISSUE, "fsa_certificate_expiry_date": EXPIRY,
        "fsa_tnved_scope": [TNVED], "fsa_product_scope": "Arlight LED light-source power supplies, series ARJ, ARPJ, ARPV, ARV",
        "production_lot_cutoff_found_in_certificate": False,
        "assignment_rows": len(rows), "unique_source_offers": len(offers),
        "source_assignment_application_counts": dict(collections.Counter(r.get("Применимость") for r in rows)),
        "ozon_snapshot_checked_at": ozon_snapshot.get("checked_at"),
        "wb_snapshot_checked_at": wb_snapshot.get("checked_at"),
        "ozon_targets_checked": len(ozon_rows), "ozon_scope_counts": dict(ozon_counts),
        "ozon_exact_record_preexisting": bool(normalized_matches),
        "ozon_exact_info_http_status": response.status_code,
        "ozon_exact_record_absence_confirmed": exact_absence_confirmed,
        "eligible_ozon_targets": len(eligible_ozon),
        "wb_snapshot_targets": len(offers), "wb_fresh_candidate_cards": len(candidates),
        "wb_targets_freshly_checked": len(wb_rows),
        "wb_reason_counts": dict(wb_reason_counts),
        "eligible_wb_cards_for_add": len(eligible_wb),
        "ozon_targets": ozon_rows, "wb_targets": wb_rows,
        "candidate_ozon_skus": [r["sku"] for r in eligible_ozon],
        "candidate_wb_cards": [{k:r.get(k) for k in ("offer_id", "nmID", "brand", "tnved_codes")}
                                for r in eligible_wb],
        "local_file_cleanup_allowed": False,
        "write_performed": False,
    }
    save(result)
    print(json.dumps({k: result[k] for k in (
        "checked_at", "assignment_rows", "unique_source_offers", "ozon_scope_counts",
        "ozon_exact_record_absence_confirmed", "eligible_ozon_targets",
        "wb_fresh_candidate_cards", "wb_targets_freshly_checked", "wb_reason_counts",
        "eligible_wb_cards_for_add", "write_performed", "local_file_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
