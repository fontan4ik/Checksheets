"""Fresh read-only Ozon + WB audit for the 27 previously processed source groups."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "certificate_api_pilot_20261012"
sys.path.insert(0, str(BASE))
from api_client import Client  # noqa: E402

MANIFEST = BASE / "all_source_certificates_verified_manifest_20261014.json"
OUT = HERE / "previously_processed_groups_crossplatform_recheck_20261020.json"
WB_SNAPSHOT = HERE / "live_marketplaces_snapshot_complete_20261020.json"
PAGE = 100

CYRILLIC_CONFUSABLES = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "Т": "T", "У": "Y", "Х": "X",
    "І": "I", "Ѕ": "S",
})


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(value: object) -> str:
    value = str(value or "").upper().translate(CYRILLIC_CONFUSABLES)
    return re.sub(r"[^A-Z0-9]", "", value)


def read_ozon_certificates(client: Client) -> list[dict]:
    records = []
    ids = set()
    page = 1
    page_count = 1
    while page <= page_count:
        response = client.call(
            "ozon", "/v1/product/certificate/list",
            {"page": page, "page_size": PAGE}, mutation=False,
        ).get("result") or {}
        batch = response.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list omitted certificates")
        for item in batch:
            cid = int(item.get("certificate_id") or 0)
            if not cid or cid in ids:
                raise RuntimeError("Ozon certificate list contains missing/duplicate ID")
            ids.add(cid)
        records.extend(batch)
        page_count = int(response.get("page_count") or page)
        page += 1
    return records


def read_ozon_products(client: Client, product_ids: list[str]) -> dict[str, dict]:
    result = {}
    for start in range(0, len(product_ids), 500):
        batch = product_ids[start:start + 500]
        response = client.call(
            "ozon", "/v3/product/info/list",
            {"product_id": [int(x) for x in batch]}, mutation=False,
        ).get("items")
        if not isinstance(response, list):
            raise RuntimeError("Ozon product info omitted items")
        for item in response:
            pid = str(item.get("product_id") or item.get("id") or "")
            if not pid or pid not in batch or pid in result:
                raise RuntimeError("Ozon product detail IDs missing, duplicated, or unexpected")
            result[pid] = item
    if set(result) != set(product_ids):
        raise RuntimeError("Ozon product detail readback is incomplete")
    return result


def wb_type(group: dict) -> int:
    if group["type_code"] == "declaration":
        return 2
    if group["type_code"] == "certificate_of_conformity":
        return 1
    raise RuntimeError(f"Unsupported document type for WB: {group['type_code']}")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    groups = manifest.get("groups") or []
    client = Client()
    ozon_records = read_ozon_certificates(client)
    products_by_id: dict[str, dict] = {}
    cert_by_number: dict[str, list[dict]] = defaultdict(list)
    for record in ozon_records:
        cert_by_number[norm(record.get("certificate_number"))].append(record)

    group_records = {}
    target_ids = sorted({str(t["product_id"]) for g in groups for t in g["targets"]})
    for group in groups:
        matches = cert_by_number.get(norm(group["number"])) or []
        group_records[group["number"]] = matches
        if len(matches) == 1:
            record = matches[0]
            bindings = client.ozon_bindings(int(record["certificate_id"]))
            record["live_bindings"] = bindings
            record["live_binding_count"] = len(bindings)
    products_by_id = read_ozon_products(client, target_ids)
    wb_snapshot = json.loads(WB_SNAPSHOT.read_text())
    wb_catalog = wb_snapshot.get("wb_catalog") or {}
    if (wb_snapshot.get("complete") is not True or wb_catalog.get("complete") is not True
            or wb_catalog.get("unique_id_set_matches_previous_complete_read") is not True
            or wb_catalog.get("card_identity_and_tnved_stable") is not True):
        raise RuntimeError("Current complete WB full-card snapshot is not verified")
    wb_checked_at = wb_catalog.get("checked_at") or wb_snapshot.get("finished_at")
    wb_readback = {
        "pages": wb_catalog.get("pages"),
        "raw_rows": wb_catalog.get("raw_rows"),
        "duplicate_rows_removed": wb_catalog.get("duplicate_rows_removed"),
        "duplicate_nmids": wb_catalog.get("duplicate_nmids") or [],
        "documents_changed_since_previous_complete_read": wb_catalog.get("documents_changed_since_previous_read"),
        "document_changed_nmids": wb_catalog.get("document_changed_nmids") or [],
    }
    wb_cards = wb_catalog.get("cards") or []
    wb_by_offer: dict[str, list[dict]] = defaultdict(list)
    for card in wb_cards:
        wb_by_offer[str(card.get("vendorCode") or "")].append(card)

    results = []
    for group in groups:
        number = group["number"]
        records = group_records[number]
        expected = {(str(t["product_id"]), str(t["sku"])) for t in group["targets"]}
        result = {
            "number": number,
            "type_code": group["type_code"],
            "issue_date": group["issue_date"],
            "expire_date": group["expire_date"],
            "target_count": len(expected),
            "source_file": group["upload_file"]["path"],
            "source_sha256": group["upload_file"]["sha256"],
            "source_size": group["upload_file"]["size"],
            "ozon_record_count": len(records),
            "ozon": None,
            "wb": None,
        }
        if len(records) == 1:
            record = records[0]
            bindings = record.get("live_bindings") or []
            by_pair = defaultdict(list)
            all_statuses = Counter()
            for binding in bindings:
                pair = (str(binding.get("product_id") or ""), str(binding.get("sku") or ""))
                by_pair[pair].append(binding)
                all_statuses[str(binding.get("product_status_code") or "MISSING")] += 1
            target_statuses = Counter()
            target_problems = []
            for pair in sorted(expected):
                found = by_pair.get(pair) or []
                if len(found) != 1:
                    target_statuses["missing_or_duplicate"] += 1
                    target_problems.append({"product_id": pair[0], "sku": pair[1], "count": len(found)})
                else:
                    status = str(found[0].get("product_status_code") or "MISSING")
                    target_statuses[status] += 1
                    if status != "approved":
                        target_problems.append({"product_id": pair[0], "sku": pair[1], "status": status})
            extra_pairs = sorted(set(by_pair) - expected)
            current_identity_problems = []
            for target in group["targets"]:
                product = products_by_id[str(target["product_id"])]
                actual = {
                    "offer_id": str(product.get("offer_id") or ""),
                    "sku": str(product.get("sku") or ""),
                    "is_archived": product.get("is_archived"),
                }
                if (actual["offer_id"] != str(target["offer_id"])
                        or actual["sku"] != str(target["sku"])
                        or actual["is_archived"] is not False):
                    current_identity_problems.append({
                        "expected": target,
                        "actual": actual,
                    })
            result["ozon"] = {
                "certificate_id": record.get("certificate_id"),
                "document_status": record.get("status_code"),
                "record_type": record.get("type_code"),
                "accordance_type": record.get("accordance_type_code"),
                "issue_date": str(record.get("issue_date") or "")[:10],
                "expire_date": str(record.get("expire_date") or "")[:10],
                "live_binding_count": len(bindings),
                "all_binding_status_counts": dict(all_statuses),
                "target_binding_status_counts": dict(target_statuses),
                "extra_binding_pairs": len(extra_pairs),
                "target_binding_problems": target_problems,
                "current_product_identity_problems": current_identity_problems,
            }

        expected_wb_type = wb_type(group)
        wb_counts = Counter()
        wb_problems = []
        no_card_offers = []
        wb_edges = []
        for target in group["targets"]:
            offer = str(target["offer_id"])
            cards = [c for c in wb_by_offer.get(offer, []) if str(c.get("vendorCode") or "") == offer]
            if not cards:
                no_card_offers.append(offer)
                wb_counts["no_card"] += 1
                continue
            for card in cards:
                documents = card.get("documents") or {}
                matches = [item for item in documents.get("items") or []
                           if norm(item.get("number")) == norm(number)
                           and int(item.get("type") or 0) == expected_wb_type
                           and str(item.get("startDate") or "")[:10] == group["issue_date"]
                           and str(item.get("endDate") or "")[:10] == group["expire_date"]]
                state = "missing"
                verdict = None
                if documents.get("excludeDocuments") is not False:
                    state = "excluded"
                elif len(matches) == 1:
                    verdict = matches[0].get("verdict") or {}
                    if (verdict.get("verified") is True and verdict.get("status") == 1
                            and verdict.get("reason") == "valid"):
                        state = "valid"
                    elif verdict.get("status") == 2 or "reject" in str(verdict.get("reason") or "").lower():
                        state = "rejected"
                    elif verdict.get("verified") is False or not verdict:
                        state = "pending"
                    else:
                        state = "other"
                elif len(matches) > 1:
                    state = "duplicate_exact_items"
                wb_counts[state] += 1
                wb_edges.append({
                    "offer_id": offer,
                    "nmID": card.get("nmID"),
                    "state": state,
                    "verdict": verdict,
                    "overall_verdict": documents.get("overallVerdict"),
                })
                if state not in ("valid", "pending"):
                    wb_problems.append({"offer_id": offer, "nmID": card.get("nmID"), "state": state})
        result["wb"] = {
            "snapshot_cards": len(wb_cards),
            "cards_with_target_vendor_codes": sum(v for k, v in wb_counts.items() if k != "no_card"),
            "offer_counts": dict(wb_counts),
            "no_card_offer_count": len(no_card_offers),
            "wb_edge_count": len(wb_edges),
            "edge_problems": wb_problems,
            "no_card_offers": no_card_offers,
            "edges": wb_edges,
        }
        results.append(result)

    out = {
        "checked_at": stamp(),
        "read_only": True,
        "wb_catalog_snapshot": str(WB_SNAPSHOT),
        "wb_catalog_snapshot_complete": True,
        "manifest_built_at": manifest.get("built_at"),
        "source_group_count": len(groups),
        "source_target_count": sum(len(g.get("targets") or []) for g in groups),
        "ozon_certificate_list_records": len(ozon_records),
        "ozon_product_ids_checked": len(products_by_id),
        "ozon_products_checked_at": stamp(),
        "wb_catalog_cards": len(wb_cards),
        "wb_catalog_pages": wb_readback["pages"],
        "wb_catalog_raw_rows": wb_readback["raw_rows"],
        "wb_duplicate_rows_removed": wb_readback["duplicate_rows_removed"],
        "wb_duplicate_nmids": wb_readback["duplicate_nmids"],
        "wb_documents_changed_since_previous_complete_read": wb_readback["documents_changed_since_previous_complete_read"],
        "wb_document_changed_nmids": wb_readback["document_changed_nmids"],
        "wb_checked_at": wb_checked_at,
        "groups": results,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    safe = []
    for item in results:
        ozon = item.get("ozon") or {}
        wb = item.get("wb") or {}
        ozon_safe = bool(
            item["ozon_record_count"] == 1
            and ozon.get("document_status") == "approved"
            and ozon.get("record_type") == item["type_code"]
            and ozon.get("issue_date") == item["issue_date"]
            and ozon.get("expire_date") == item["expire_date"]
            and ozon.get("target_binding_status_counts") == {"approved": item["target_count"]}
            and ozon.get("all_binding_status_counts") == {"approved": item["target_count"]}
            and ozon.get("extra_binding_pairs") == 0
            and not ozon.get("target_binding_problems")
            and not ozon.get("current_product_identity_problems")
        )
        wb_safe = bool(not wb.get("edge_problems")
                       and wb.get("offer_counts", {}).get("valid", 0)
                       + wb.get("offer_counts", {}).get("pending", 0)
                       + wb.get("offer_counts", {}).get("no_card", 0)
                       == item["target_count"])
        if ozon_safe and wb_safe:
            safe.append(item["number"])
    print(json.dumps({
        "checked_at": out["checked_at"],
        "ozon_records": len(ozon_records),
        "ozon_products_checked": len(products_by_id),
        "wb_cards": len(wb_cards),
        "wb_raw_rows": wb_readback["raw_rows"],
        "wb_duplicate_rows_removed": wb_readback["duplicate_rows_removed"],
        "wb_documents_changed_since_previous_complete_read": wb_readback["documents_changed_since_previous_complete_read"],
        "groups": len(results),
        "crossplatform_cleanup_candidates": len(safe),
        "candidate_numbers": safe,
        "output": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
