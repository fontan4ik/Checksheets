#!/usr/bin/env python3
"""Read-only live scope/identity check for Stekker declaration 01452/23."""
from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents, doc_key  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА07.В.01452/23"
ISSUE, EXPIRE = "2023-08-31", "2028-08-30"
REGISTRY = "https://pub.fsa.gov.ru/rds/declaration/view/18056436/common"
FSA_TNVED = {"8544429009"}
ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_resume_20261023.csv"
OUT = HERE / "stekker_01452_live_preflight_20261024.json"


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_exists_inspect_before_overwrite")
    rows = [r for r in csv.DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline=""))
            if norm_number(r.get("number")) == norm_number(NUMBER)]
    offers = {r.get("offer_id"): r for r in rows}
    if len(offers) != len(rows) or not offers:
        raise RuntimeError("duplicate_or_empty_offer_set")
    if any(r.get("brand") != "Stekker" or r.get("type") != "declaration"
           or r.get("source_type_conflict") not in ("False", "false", "0")
           for r in rows):
        raise RuntimeError("source_assignment_type_or_brand_conflict")

    client = Client()
    offer_ids = list(offers)
    products, attrs = [], []
    for start in range(0, len(offer_ids), 100):
        batch = offer_ids[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes",
                                {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap, amap = collections.defaultdict(list), collections.defaultdict(list)
    for p in products:
        pmap[str(p.get("offer_id"))].append(p)
    for a in attrs:
        amap[str(a.get("offer_id"))].append(a)
    ozon_rows, ozon_conflicts = [], []
    for offer, source in offers.items():
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            ozon_conflicts.append({"offer_id": offer, "reason": "product_or_attributes_not_unique"})
            continue
        p, a = pmap[offer][0], amap[offer][0]
        values = {str(x.get("id")): [str(v.get("value") or "").strip()
                   for v in x.get("values") or [] if str(v.get("value") or "").strip()]
                  for x in a.get("attributes") or []}
        brands = values.get("85", [])
        codes = sorted({x.split(" - ", 1)[0].strip() for x in values.get("22232", [])})
        product_id, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        expected_id, expected_sku = str(source.get("ozon_product_id") or ""), str(source.get("ozon_sku") or "")
        ok_identity = product_id == expected_id and sku == expected_sku and p.get("is_archived") is False
        ok_brand = bool(brands) and all(x.casefold() == "stekker" for x in brands)
        ok_tnved = bool(codes) and set(codes) <= FSA_TNVED
        row = {"offer_id": offer, "product_id": product_id, "sku": sku, "name": p.get("name"),
               "brands": brands, "tnved_codes": codes, "identity_exact": ok_identity,
               "brand_exact": ok_brand, "tnved_exact": ok_tnved,
               "eligible": ok_identity and ok_brand and ok_tnved}
        ozon_rows.append(row)
        if not row["eligible"]:
            ozon_conflicts.append({"offer_id": offer, "identity_exact": ok_identity,
                                   "brand_exact": ok_brand, "tnved_exact": ok_tnved,
                                   "brand": brands, "tnved": codes})

    wb_rows, wb_conflicts = [], []
    for i, (offer, source) in enumerate(offers.items(), start=1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            wb_conflicts.append({"offer_id": offer, "reason": "card_count", "count": len(cards)})
            continue
        card = cards[0]
        codes = tnved(card)
        exact_identity = (str(card.get("vendorCode")) == offer
                          and str(card.get("nmID")) == str(source.get("wb_nmID")))
        exact_brand = str(card.get("brand") or "").strip().casefold() == "stekker"
        exact_tnved = bool(codes) and set(codes) <= FSA_TNVED
        items = copy_documents(card)
        same = [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if doc_key(x) == (2, norm_number(NUMBER))
                 and str(x.get("startDate", ""))[:10] == ISSUE
                 and str(x.get("endDate", ""))[:10] == EXPIRE
                 and x.get("isEndless") is False]
        metadata_conflict = bool(same) and (len(same) != 1 or len(exact) != 1)
        eligible = exact_identity and exact_brand and exact_tnved and not metadata_conflict
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID")), "title": card.get("title"),
                        "brand": card.get("brand"), "tnved_codes": codes,
                        "prior_document_count": len(items),
                        "document_state": "already_exact" if exact else "missing",
                        "identity_exact": exact_identity, "brand_exact": exact_brand,
                        "tnved_exact": exact_tnved, "metadata_conflict": metadata_conflict,
                        "eligible": eligible, "card": card})
        if not eligible:
            wb_conflicts.append({"offer_id": offer, "identity_exact": exact_identity,
                                 "brand_exact": exact_brand, "tnved_exact": exact_tnved,
                                 "metadata_conflict": metadata_conflict, "tnved": codes})
        if i % 15 == 0 or i == len(offers):
            print(json.dumps({"wb_live_cards_checked": i, "total": len(offers)}, ensure_ascii=False), flush=True)

    records = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) > 1:
        raise RuntimeError("ozon_duplicate_exact_document_records")
    record_summary = None
    if records:
        record = records[0]
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date", ""))[:10] != ISSUE
                or str(record.get("expire_date", ""))[:10] != EXPIRE):
            raise RuntimeError("ozon_existing_document_metadata_conflict")
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        record_summary = {"certificate_id": str(record["certificate_id"]),
                          "status_code": record.get("status_code"),
                          "binding_count": len(bindings),
                          "binding_status_counts": dict(collections.Counter(
                              str(x.get("product_status_code") or "unknown") for x in bindings)),
                          "bindings": bindings}

    result = {"checked_at_utc": now(), "read_only": True,
              "fsa_registry": {"number": NUMBER, "status": "Действует",
                               "issue_date": ISSUE, "expire_date": EXPIRE,
                               "record_id": "18056436", "registry_url": REGISTRY,
                               "tnved": sorted(FSA_TNVED), "scope": "Stekker HM/PRF/STD extension cords, cord sets and power strips",
                               "sample_date_note": "FSA says declaration applies from sample date; exact batch manufacture dates are unavailable"},
              "target_count": len(offers), "ozon_targets": ozon_rows,
              "ozon_conflicts": ozon_conflicts, "ozon_existing_record": record_summary,
              "wb_targets": wb_rows, "wb_conflicts": wb_conflicts,
              "summary": {"source_assignment_targets": len(offers),
                          "ozon_live_eligible": sum(x["eligible"] for x in ozon_rows),
                          "ozon_tnved_or_identity_conflicts": len(ozon_conflicts),
                          "wb_live_eligible": sum(x["eligible"] for x in wb_rows),
                          "wb_tnved_or_identity_conflicts": len(wb_conflicts),
                          "wb_missing_document_edges": sum(x["eligible"] and x["document_state"] == "missing" for x in wb_rows),
                          "writes_performed": False, "local_files_deleted": False}}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
