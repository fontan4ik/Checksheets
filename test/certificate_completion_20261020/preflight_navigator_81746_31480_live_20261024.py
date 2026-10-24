#!/usr/bin/env python3
"""Fresh read-only cross-platform preflight for Navigator driver docs."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

ASSIGNMENTS = HERE / "all_confirmed_source_assignments_live_resume_20261023.csv"
GAPS = HERE / "confirmed_source_gaps_audit_resume_20261024.json"
OUT = HERE / "navigator_81746_31480_live_preflight_20261024.json"
FSA_CODES = {"8504409100"}
DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА08.В.81746/23",
        "type_code": "declaration",
        "wb_type": 2,
        "issue_date": "2023-10-20",
        "expire_date": "2028-10-17",
        "source_url": "http://www.batteryteam.ru/sert/1370.pdf",
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/18254666/product",
        "fsa_record_id": "18254666",
        "fsa_scope": "Драйверы торговой марки Navigator серии ND",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.АЯ46.В.31480/23",
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "issue_date": "2023-10-12",
        "expire_date": "2028-10-11",
        "source_url": "http://www.batteryteam.ru/sert/1363.pdf",
        "fsa_url": "https://pub.fsa.gov.ru/rss/certificate/view/3328338/product",
        "fsa_record_id": "3328338",
        "fsa_scope": "Блоки питания (драйверы) для светодиодного оборудования; торговой марки Navigator серии ND",
    },
}


def save(value: dict) -> None:
    temporary = OUT.with_suffix(OUT.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(OUT)


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = item.get("value")
        values.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def list_certificates(client: Client) -> list[dict]:
    result = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result") or {}
        rows = data.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        result.extend(rows)
        if page >= int(data.get("page_count") or 0):
            return result
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_exists_inspect_before_overwrite")
    if not ASSIGNMENTS.is_file() or not GAPS.is_file():
        raise RuntimeError("assignment_or_source_audit_missing")
    gap_groups = json.loads(GAPS.read_text()).get("candidate_source_groups") or []
    candidates = {}
    for key, doc in DOCS.items():
        matches = [g for g in gap_groups if norm_number(g.get("document_number")) == norm_number(doc["number"])
                   and str(g.get("brand", "")).casefold() == "navigator"]
        if len(matches) != 1:
            raise RuntimeError(f"source_audit_candidate_count:{key}:{len(matches)}")
        g = matches[0]
        source = ROOT / g["source_file"]
        if (not source.is_file() or g.get("source_exists") is not True
                or hashlib.sha256(source.read_bytes()).hexdigest() != g.get("declared_sha256")
                or g.get("declared_sha256") != g.get("actual_sha256")):
            raise RuntimeError(f"source_file_hash_mismatch:{key}")
        doc["file"] = source
        doc["sha256"] = g["declared_sha256"]
        doc["source_audit"] = {k: g.get(k) for k in (
            "source_file", "declared_sha256", "actual_sha256", "scope_examples", "source_urls",
            "applicability_counts", "validity_examples",
        )}
        candidates[key] = g
        if date.fromisoformat(doc["issue_date"]) > date.today() or date.fromisoformat(doc["expire_date"]) < date.today():
            raise RuntimeError(f"document_outside_validity_dates:{key}")

    target_rows: dict[str, dict] = {}
    by_doc: dict[str, set[str]] = {key: set() for key in DOCS}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("brand", "")).casefold() != "navigator":
                continue
            for key, doc in DOCS.items():
                if norm_number(row.get("number")) != norm_number(doc["number"]):
                    continue
                offer = str(row.get("offer_id") or "").strip()
                if not offer:
                    raise RuntimeError("source_assignment_missing_offer")
                prior = target_rows.get(offer)
                current = {
                    "offer_id": offer,
                    "product_id": str(row.get("ozon_product_id") or ""),
                    "sku": str(row.get("ozon_sku") or ""),
                    "wb_nmID": str(row.get("wb_nmID") or ""),
                }
                if prior and prior != current:
                    raise RuntimeError("source_assignment_identity_conflict:" + offer)
                target_rows[offer] = current
                by_doc[key].add(offer)
    if any(len(offers) != 8 for offers in by_doc.values()) or len(target_rows) != 8:
        raise RuntimeError(f"unexpected_target_set:{ {k: len(v) for k, v in by_doc.items()} }")
    offers = sorted(target_rows)

    client = Client()
    fresh_products, fresh_attributes = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        fresh_products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        fresh_attributes.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch),
        }).get("result") or [])
    product_map = collections.defaultdict(list)
    attribute_map = collections.defaultdict(list)
    for row in fresh_products:
        product_map[str(row.get("offer_id"))].append(row)
    for row in fresh_attributes:
        attribute_map[str(row.get("offer_id"))].append(row)
    if set(product_map) != set(offers) or set(attribute_map) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_incomplete")

    products_out = []
    for offer in offers:
        expected = target_rows[offer]
        product, attr = product_map[offer][0], attribute_map[offer][0]
        if len(product_map[offer]) != 1 or len(attribute_map[offer]) != 1:
            raise RuntimeError("fresh_ozon_duplicate_product_or_attribute:" + offer)
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        values = {str(a.get("id")): [str(v.get("value") or "").strip()
                  for v in a.get("values") or [] if str(v.get("value") or "").strip()]
                  for a in attr.get("attributes") or []}
        brands = values.get("85", [])
        tnved = sorted({v.split(" - ", 1)[0].strip() for v in values.get("22232", [])})
        if (product_id != expected["product_id"] or sku != expected["sku"]
                or product.get("is_archived") is not False):
            raise RuntimeError("fresh_ozon_identity_conflict:" + offer)
        if not brands or any(v.casefold() != "navigator" for v in brands):
            raise RuntimeError("fresh_ozon_brand_conflict:" + offer)
        if not tnved or not set(tnved) <= FSA_CODES:
            raise RuntimeError("fresh_ozon_tnved_conflict:" + offer + ":" + ",".join(tnved))
        products_out.append({**expected, "name": product.get("name"), "brand_values": brands,
                             "tnved_codes": tnved, "archived": False})

    wb_out = []
    for offer in offers:
        expected = target_rows[offer]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError(f"wb_exact_card_count:{offer}:{len(cards)}")
        card = cards[0]
        codes = card_tnved(card)
        if (str(card.get("vendorCode")) != offer or str(card.get("nmID")) != expected["wb_nmID"]
                or str(card.get("brand") or "").strip().casefold() != "navigator"):
            raise RuntimeError("wb_card_identity_conflict:" + offer)
        if not codes or not set(codes) <= FSA_CODES:
            raise RuntimeError("wb_tnved_conflict:" + offer + ":" + ",".join(codes))
        prior_docs = card.get("documents", {}).get("items") or []
        docs_state = {}
        for key, doc in DOCS.items():
            same_number = [d for d in prior_docs if norm_number(d.get("number")) == norm_number(doc["number"])]
            exact = [d for d in same_number if d.get("type") == doc["wb_type"]
                     and str(d.get("startDate", ""))[:10] == doc["issue_date"]
                     and str(d.get("endDate", ""))[:10] == doc["expire_date"]
                     and d.get("isEndless") is False]
            if same_number and (len(same_number) != 1 or len(exact) != 1):
                raise RuntimeError("wb_same_number_metadata_conflict:" + offer + ":" + doc["number"])
            docs_state[key] = "already_exact" if exact else "missing"
        wb_out.append({"offer_id": offer, "nmID": expected["wb_nmID"], "brand": card.get("brand"),
                       "tnved_codes": codes, "documents": docs_state,
                       "prior_document_count": len(prior_docs)})

    certificates = list_certificates(client)
    ozon_records = {}
    for key, doc in DOCS.items():
        matches = [r for r in certificates
                   if norm_number(r.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) > 1:
            raise RuntimeError("ozon_duplicate_exact_record:" + key)
        if matches:
            r = matches[0]
            if (r.get("type_code") != doc["type_code"]
                    or str(r.get("issue_date", ""))[:10] != doc["issue_date"]
                    or str(r.get("expire_date", ""))[:10] != doc["expire_date"]
                    or r.get("status_code") in ("declined", "rejected")):
                raise RuntimeError("ozon_existing_record_conflict:" + key)
            bindings = client.ozon_bindings(r["certificate_id"])
            by_pid = {str(b.get("product_id")): b for b in bindings}
            for t in products_out:
                prior = by_pid.get(t["product_id"])
                if prior and (str(prior.get("sku")) != t["sku"]
                              or prior.get("product_status_code") == "declined"):
                    raise RuntimeError("ozon_existing_binding_conflict:" + key + ":" + t["offer_id"])
            ozon_records[key] = {"certificate_id": str(r["certificate_id"]),
                                 "record_status": r.get("status_code"),
                                 "existing_bindings": len(bindings),
                                 "target_bindings_present": sum(
                                     1 for t in products_out
                                     if str(t["product_id"]) in by_pid
                                     and str(by_pid[str(t["product_id"])].get("sku")) == t["sku"]) }
        else:
            ozon_records[key] = {"certificate_id": None, "record_status": None,
                                 "existing_bindings": 0, "target_bindings_present": 0}

    result = {
        "checked_at_utc": now(),
        "read_only": True,
        "fsa_registry": {
            key: {k: doc[k] for k in ("number", "issue_date", "expire_date", "fsa_url",
                                      "fsa_record_id", "fsa_scope")}
            for key, doc in DOCS.items()
        },
        "fsa_tnved_codes": sorted(FSA_CODES),
        "target_count": len(offers),
        "targets": products_out,
        "ozon_records": ozon_records,
        "wb_targets": wb_out,
        "source_files": {key: {"path": str(doc["file"]), "sha256": doc["sha256"],
                                "source_url": doc["source_url"],
                                "bytes": doc["file"].stat().st_size}
                         for key, doc in DOCS.items()},
        "summary": {
            "ozon_identity_brand_tnved_exact": len(products_out),
            "wb_unique_identity_brand_tnved_exact": len(wb_out),
            "ozon_exact_records_absent": sum(v["certificate_id"] is None for v in ozon_records.values()),
            "wb_missing_doc_edges": sum(1 for card in wb_out for state in card["documents"].values()
                                        if state == "missing"),
            "wb_already_exact_doc_edges": sum(1 for card in wb_out for state in card["documents"].values()
                                              if state == "already_exact"),
            "writes_performed": False,
            "local_files_deleted": False,
        },
    }
    save(result)
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
