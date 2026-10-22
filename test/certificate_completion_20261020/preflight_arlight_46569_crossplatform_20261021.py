"""Fresh read-only preflight for Arlight 46569/26 on Ozon and WB."""
from __future__ import annotations

import collections
import csv
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
    copy_documents, doc_key, norm_number, wb_datetime,
)

PDF = ROOT / "output_to_user/certificates/group_1/documents/arlight/97331E1740F80745A33F67528E33A9AB.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OLD_SNAPSHOT = HERE / "live_marketplaces_snapshot_final_20261020.json"
OUT = HERE / "arlight_46569_preflight_live_20261021.json"
NUMBER = "ЕАЭС N RU Д-CN.РА01.В.46569/26"
ALLOWED = {"8539519009"}
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"


def save(value: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def tnved_wb(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values.extend(str(v or "").split(" - ", 1)[0].strip()
                      for v in (raw if isinstance(raw, list) else [raw]))
    return sorted(set(x for x in values if x))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists")
    digest = hashlib.sha256(PDF.read_bytes()).hexdigest()
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        all_rows = list(csv.DictReader(stream))
    rows = [r for r in all_rows if str(r.get("SHA256 фактический") or "").lower() == digest]
    by_offer = collections.defaultdict(list)
    for row in rows:
        by_offer[str(row["Артикул продавца"])].append(row)
    offers = sorted(by_offer)
    if len(rows) != 923 or len(offers) != 905:
        raise RuntimeError(f"unexpected_assignment_targets:{len(rows)}:{len(offers)}")
    identity_fields = ("Бренд Ozon", "Название товара Ozon", "Тип товара Ozon")
    for offer, assigned in by_offer.items():
        if len({tuple(r.get(k, "") for k in identity_fields) for r in assigned}) != 1:
            raise RuntimeError(f"conflicting_duplicate_assignment_identity:{offer}")
        if any("46569/26" not in str(r.get("Номер/название документа") or "") for r in assigned):
            raise RuntimeError(f"assignment_does_not_name_target_declaration:{offer}")

    old = json.loads(OLD_SNAPSHOT.read_text())
    old_products = {str(x["offer_id"]): x for x in old["ozon_products"]["products"]}
    if not old["ozon_products"].get("complete") or not old["wb_catalog"].get("complete"):
        raise RuntimeError("complete_previous_snapshot_required_for_identity_guard")
    initial = {offer: old_products[offer] for offer in offers if offer in old_products}
    if len(initial) != 905:
        raise RuntimeError("previous_ozon_target_identity_incomplete")

    client = Client()
    ids = [str(initial[o]["product_id"]) for o in offers]
    details = {}
    for start in range(0, len(ids), 500):
        batch_ids = ids[start:start + 500]
        result = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch_ids]
        }).get("items")
        if not isinstance(result, list):
            raise RuntimeError("ozon_details_missing")
        for item in result:
            pid = str(item.get("product_id") or item.get("id") or "")
            if pid not in batch_ids or pid in details:
                raise RuntimeError("ozon_detail_identity_mismatch")
            details[pid] = item
    if set(details) != set(ids):
        raise RuntimeError("ozon_details_incomplete")

    attributes = {}
    for start in range(0, len(offers), 100):
        batch_offers = offers[start:start + 100]
        result = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch_offers}, "limit": len(batch_offers)
        }).get("result")
        if not isinstance(result, list):
            raise RuntimeError("ozon_attributes_missing")
        for item in result:
            offer = str(item.get("offer_id") or "")
            if offer not in batch_offers or offer in attributes:
                raise RuntimeError("ozon_attribute_offer_mismatch")
            attributes[offer] = item
    if set(attributes) != set(offers):
        raise RuntimeError("ozon_attributes_incomplete")

    ozon_rows = []
    for offer in offers:
        old_row = initial[offer]
        pid = str(old_row["product_id"])
        detail = details[pid]
        attr = attributes[offer]
        if (str(detail.get("offer_id") or "") != offer
                or str(detail.get("sku") or "") != str(old_row["sku"])
                or str(detail.get("product_id") or detail.get("id") or "") != pid
                or str(attr.get("id") or attr.get("product_id") or "") != pid):
            raise RuntimeError(f"ozon_live_identity_changed:{offer}")
        values = {str(a.get("id")): a for a in attr.get("attributes") or []}
        brand = [str(v.get("value")) for v in (values.get("85") or {}).get("values") or []
                 if v.get("value") not in (None, "")]
        tnved = [str(v.get("value")) for v in (values.get("22232") or {}).get("values") or []
                 if v.get("value") not in (None, "")]
        code_set = {x.split(" - ", 1)[0].strip() for x in tnved}
        ozon_rows.append({"offer_id": offer, "product_id": pid, "sku": str(detail["sku"]),
                          "brand_values": brand, "tnved_values": tnved,
                          "is_archived": detail.get("is_archived"),
                          "in_scope": len(code_set) == 1 and code_set <= ALLOWED
                          and all("arlight" in b.casefold() for b in brand)})

    # Check the complete Ozon record list for visually/Unicode-normalized duplicates,
    # then use the exact-number endpoint. This endpoint returns HTTP 404 / code 5 for
    # an absent document; Client.call intentionally raises for non-200 responses.
    metadata = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_missing")
        metadata.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            break
        page += 1
    normalized_matches = [x for x in metadata
                          if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if normalized_matches:
        raise RuntimeError("ozon_normalized_record_already_exists:" + ",".join(
            str(x.get("certificate_id")) for x in normalized_matches))

    payload = {"certificate_number": NUMBER}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    entry = {"started_at": now(), "platform": "ozon",
             "path": "/v1/product/certificate/info", "mutation": False,
             "request_sha256": hashlib.sha256(encoded).hexdigest(),
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
        stream.write(json.dumps({**entry, "phase": "response",
                                 "http_status": response.status_code,
                                 "body": exact_info, "finished_at": now()},
                                ensure_ascii=False) + "\n")
    if response.status_code == 200:
        exact = exact_info.get("result") if isinstance(exact_info, dict) else None
        if exact and norm_number(exact.get("certificate_number")) == norm_number(NUMBER):
            raise RuntimeError(f"ozon_exact_record_already_exists:{exact.get('certificate_id')}")
        if exact:
            raise RuntimeError("ozon_exact_info_returned_unexpected_record")
    elif not (response.status_code == 404 and isinstance(exact_info, dict)
              and exact_info.get("code") == 5
              and "not found" in str(exact_info.get("message") or "").casefold()
              and NUMBER in str(exact_info.get("message") or "")):
        raise RuntimeError(f"ozon_exact_record_absence_unconfirmed:{response.status_code}")
    existing = {}

    wanted = set(offers)
    found: dict[str, list[dict]] = collections.defaultdict(list)
    cursor = {"limit": 100}
    seen = set()
    pages = count = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {
            "settings": {"sort": {"ascending": True}, "cursor": cursor,
                         "filter": {"withPhoto": -1}}
        })
        batch = body.get("cards")
        if body.get("error") or not isinstance(batch, list):
            raise RuntimeError("invalid_wb_catalog_page")
        pages += 1
        count += len(batch)
        for card in batch:
            offer = str(card.get("vendorCode") or "")
            if offer in wanted:
                found[offer].append(card)
        if pages % 50 == 0:
            print(json.dumps({"phase": "wb_full_catalog", "pages": pages,
                              "cards_read": count,
                              "target_cards_found": sum(map(len, found.values()))}), flush=True)
        if len(batch) < 100:
            break
        c = body.get("cursor") or {}
        sig = (c.get("updatedAt"), c.get("nmID"))
        if None in sig or sig in seen:
            raise RuntimeError("wb_catalog_cursor_incomplete_or_repeated")
        seen.add(sig)
        cursor = {"limit": 100, "updatedAt": sig[0], "nmID": sig[1]}

    wb_rows = []
    for offer in offers:
        cards = found.get(offer, [])
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "exact_card_count": len(cards), "in_scope": False})
            continue
        card = cards[0]
        codes = tnved_wb(card)
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        wb_rows.append({"offer_id": offer, "nmID": card.get("nmID"), "brand": card.get("brand"),
                        "tnved_values": codes, "in_scope": len(codes) == 1 and set(codes) <= ALLOWED,
                        "matching_number_docs": len(same), "current_documents": docs})

    target_doc = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRY), "isEndless": False}
    ozon_counts = collections.Counter(
        "in_scope" if x["in_scope"] else "out_of_scope_or_unverified" for x in ozon_rows)
    wb_counts = collections.Counter(
        "in_scope" if x.get("in_scope") else "out_of_scope_or_missing_or_duplicate"
        for x in wb_rows)
    exact_wb_doc_count = sum(x.get("matching_number_docs") == 1 for x in wb_rows)
    output = {
        "checked_at": now(), "read_only": True, "number": NUMBER,
        "official_fsa_record_id": 21106549, "official_status": "active",
        "official_issue_date": ISSUE, "official_expiry_date": EXPIRY,
        "official_tnved_scope": sorted(ALLOWED), "source_pdf": str(PDF),
        "source_pdf_sha256": digest, "assignment_rows": len(rows),
        "unique_offer_targets": len(offers),
        "ozon_targets_checked": len(ozon_rows), "ozon_scope_counts": dict(ozon_counts),
        "ozon_exact_record_preexisting": bool(existing),
        "ozon_normalized_record_matches": len(normalized_matches),
        "ozon_exact_info_http_status": response.status_code,
        "ozon_exact_record_info": existing,
        "wb_full_catalog_pages": pages, "wb_full_catalog_cards_read": count,
        "wb_targets_checked": len(wb_rows), "wb_scope_counts": dict(wb_counts),
        "wb_existing_target_cards_with_same_number": exact_wb_doc_count,
        "ozon_targets": ozon_rows, "wb_targets": wb_rows,
        "candidate_wb_document": target_doc,
        "eligible_for_upload": (len(ozon_rows) == 905 and ozon_counts == {"in_scope": 905}
                                and len(wb_rows) == 905 and wb_counts == {"in_scope": 905}
                                and exact_wb_doc_count == 0 and not existing),
        "local_files_deleted": False,
    }
    save(output)
    print(json.dumps({k: v for k, v in output.items()
                      if k not in {"ozon_targets", "wb_targets"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
