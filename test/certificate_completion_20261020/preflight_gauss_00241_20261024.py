#!/usr/bin/env python3
"""Read-only live check for Gauss BACKLIGHT certificate 00241/26."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number, copy_documents, doc_key  # noqa: E402

NUMBER = "ЕАЭС RU С-CN.НК50.В.00241/26"
FILE = ROOT / "output_to_user/certificates/additional_search/brand_research/gauss/followup_2026_10_02_d/docs/FSA_current_extract_00241_26.pdf"
SHA256 = "a407ecf937dda43c5fb4bc3600841e8e6c8828c63fe8794b91a494306e4024df"
REGISTRY = "https://pub.fsa.gov.ru/rss/certificate/view/3711373/baseInfo"
PRODUCT_PAGE = "https://pub.fsa.gov.ru/rss/certificate/view/3711373/product"
OUT = HERE / "gauss_00241_live_preflight_20261024.json"
TARGETS_CSV = HERE / "all_confirmed_source_assignments_live_resume_20261023.csv"
TNVED = {"9405110039"}
TARGETS = {
    "BL130-1": {"product_id": "531054055", "sku": "1004871962", "nmID": "496957527", "model": "BL130"},
    "BL131-1": {"product_id": "531054060", "sku": "1006572298", "nmID": "496957629", "model": "BL131"},
    "BL132-1": {"product_id": "531054077", "sku": "1006572299", "nmID": "496957551", "model": "BL132"},
    "BL134-1": {"product_id": "531054068", "sku": "1006572651", "nmID": "496957582", "model": "BL134"},
}
ISSUE, EXPIRE = "2026-08-10", "2031-08-09"


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


def card_tnved(card: dict) -> list[str]:
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
    if not FILE.is_file() or hashlib.sha256(FILE.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("official_fsa_extract_hash_mismatch")
    assignments = [r for r in csv.DictReader(TARGETS_CSV.open(encoding="utf-8-sig", newline=""))
                   if norm_number(r.get("number")) == norm_number(NUMBER)]
    by_offer = {r.get("offer_id"): r for r in assignments}
    if set(by_offer) != set(TARGETS):
        raise RuntimeError("source_assignment_target_set_changed")
    for offer, expected in TARGETS.items():
        row = by_offer[offer]
        if (row.get("brand") != "Gauss" or row.get("type") != "certificate_of_conformity"
                or str(row.get("ozon_product_id")) != expected["product_id"]
                or str(row.get("ozon_sku")) != expected["sku"]
                or str(row.get("wb_nmID")) != expected["nmID"]):
            raise RuntimeError("assignment_identity_mismatch:" + offer)

    client = Client()
    offers = list(TARGETS)
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = client.call("ozon", "/v4/product/info/attributes",
                        {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pmap = collections.defaultdict(list)
    amap = collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id"))].append(row)
    for row in attrs:
        amap[str(row.get("offer_id"))].append(row)
    ozon = []
    for offer, expected in TARGETS.items():
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("ozon_product_or_attributes_not_unique:" + offer)
        p, a = pmap[offer][0], amap[offer][0]
        values = {str(x.get("id")): [str(v.get("value") or "").strip()
                   for v in x.get("values") or [] if str(v.get("value") or "").strip()]
                  for x in a.get("attributes") or []}
        brands = values.get("85", [])
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in values.get("22232", [])})
        if (str(p.get("product_id") or p.get("id")) != expected["product_id"]
                or str(p.get("sku")) != expected["sku"] or p.get("is_archived") is not False
                or brands != ["Gauss"]):
            raise RuntimeError("ozon_live_identity_or_brand_conflict:" + offer)
        ozon.append({"offer_id": offer, "product_id": expected["product_id"], "sku": expected["sku"],
                     "name": p.get("name"), "brand_values": brands, "tnved_codes": tnved,
                     "model": expected["model"],
                     "eligible": bool(tnved) and set(tnved) <= TNVED,
                     "skip_reason": None if tnved and set(tnved) <= TNVED else "tnved_conflicts_with_live_fsa_record"})

    wb = []
    for offer, expected in TARGETS.items():
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_exact_card_count:" + offer + ":" + str(len(cards)))
        card = cards[0]
        codes = card_tnved(card)
        if (str(card.get("vendorCode")) != offer or str(card.get("nmID")) != expected["nmID"]
                or str(card.get("brand") or "").strip().casefold() != "gauss"
                or not codes or not set(codes) <= TNVED):
            raise RuntimeError("wb_live_identity_brand_or_tnved_conflict:" + offer + ":" + str(codes))
        items = copy_documents(card)
        same = [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if doc_key(x) == (1, norm_number(NUMBER))
                 and str(x.get("startDate", ""))[:10] == ISSUE
                 and str(x.get("endDate", ""))[:10] == EXPIRE
                 and x.get("isEndless") is False]
        if same and (len(same) != 1 or len(exact) != 1):
            raise RuntimeError("wb_existing_same_number_conflict:" + offer)
        wb.append({"offer_id": offer, "nmID": expected["nmID"], "brand": card.get("brand"),
                   "tnved_codes": codes, "prior_document_count": len(items),
                   "document_state": "already_exact" if exact else "missing"})

    records = [r for r in list_certificates(client)
               if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) > 1:
        raise RuntimeError("ozon_duplicate_document_records")
    ozon_record = None
    if records:
        record = records[0]
        if (record.get("type_code") != "certificate_of_conformity"
                or str(record.get("issue_date", ""))[:10] != ISSUE
                or str(record.get("expire_date", ""))[:10] != EXPIRE
                or record.get("accordance_type_code") not in (None, "EAEU")):
            raise RuntimeError("ozon_existing_record_metadata_conflict")
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        expected = {(x["product_id"], x["sku"]) for x in ozon}
        pairs = {(str(x.get("product_id")), str(x.get("sku"))) for x in bindings}
        if any(pair not in expected for pair in pairs):
            raise RuntimeError("ozon_existing_binding_outside_target_set")
        ozon_record = {"record": record, "binding_count": len(bindings),
                       "target_bindings_present": len(pairs & expected)}

    output = {"checked_at_utc": now(), "read_only": True,
              "fsa_registry": {"number": NUMBER, "type": "certificate_of_conformity",
                               "status": "Действует", "issue_date": ISSUE, "expire_date": EXPIRE,
                               "record_id": "3711373", "registry_url": REGISTRY,
                               "product_url": PRODUCT_PAGE,
                               "scope": "Gauss BACKLIGHT recessed LED luminaires; BL130, BL131, BL132, BL134",
                               "tnved": sorted(TNVED),
                               "source_file_sha256": SHA256,
                               "sample_manufacture_cutoff": "from selected sample manufactured 2024-12"},
              "target_count": len(ozon), "targets": ozon, "wb_targets": wb,
              "ozon_existing_record": ozon_record,
              "summary": {"ozon_identity_brand_tnved_exact": sum(x["eligible"] for x in ozon),
                          "wb_unique_identity_brand_tnved_exact": len(wb),
                          "ozon_tnved_conflict_count": sum(not x["eligible"] for x in ozon),
                          "ozon_exact_record_absent": not records,
                          "wb_missing_doc_edges": sum(x["document_state"] == "missing" for x in wb),
                          "writes_performed": False, "local_files_deleted": False}}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
