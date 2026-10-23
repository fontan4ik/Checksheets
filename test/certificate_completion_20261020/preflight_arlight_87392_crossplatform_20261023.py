#!/usr/bin/env python3
"""Fresh read-only preflight for Arlight EAEU declaration 87392/22."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number, wb_datetime  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.PA08.B.87392/22"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/E8503D1F8C103B41B49B024538942102.pdf"
SOURCE_SHA256 = "cb52ca8a72f07018e22ecf6861cfcf48aad25963c11ab6937efb97a921d99267"
ISSUE = "2022-12-07"
EXPIRY = "2027-12-06"
ALLOWED_TNVED = {"8539519009"}
LOCAL_FILE = "output_to_user/certificates/group_1/documents/arlight/E8503D1F8C103B41B49B024538942102.pdf"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_fresh_reconciled_20261023.json"
OUT = HERE / "arlight_87392_crossplatform_preflight_20261023.json"


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(values: list[str]) -> set[str]:
    return {str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()}


def load_targets() -> dict[str, dict]:
    targets: dict[str, dict] = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("Локальный файл") != LOCAL_FILE
                    or row.get("Бренд подтвержденный") != "Arlight"
                    or row.get("Применимость") != "Подтверждено статусом покрытия"):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if not offer or offer in targets:
                raise RuntimeError("missing_or_duplicate_assignment_offer:" + offer)
            targets[offer] = {"offer_id": offer,
                "assignment_product_name": row.get("Название товара Ozon"),
                "assignment_scope_evidence": row.get("Основание сопоставления"),
                "source_url": row.get("URL документа")}
    if len(targets) != 153:
        raise RuntimeError(f"unexpected_assignment_target_count:{len(targets)}")
    return targets


def ozon_certificates(client: Client) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_page_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_before_retry")
    actual_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest() if SOURCE.is_file() else ""
    if actual_sha != SOURCE_SHA256:
        raise RuntimeError("source_pdf_missing_or_hash_mismatch")
    targets = load_targets()
    offers = sorted(targets)
    client = Client()

    products: dict[str, list[dict]] = collections.defaultdict(list)
    attributes: dict[str, list[dict]] = collections.defaultdict(list)
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("ozon_product_or_attribute_response_incomplete")
        for row in p_rows:
            products[str(row.get("offer_id") or "")].append(row)
        for row in a_rows:
            attributes[str(row.get("offer_id") or "")].append(row)
    if set(products) != set(offers) or set(attributes) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_mismatch")

    records = [x for x in ozon_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) != 1:
        raise RuntimeError(f"ozon_record_identity_not_unique:{len(records)}")
    record = records[0]
    if (record.get("type_code") != "declaration"
            or record.get("accordance_type_code") != "EAEU"
            or record.get("status_code") != "approved"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_not_exact_current_approved")
    record_id = int(record["certificate_id"])
    bindings = client.ozon_bindings(record_id)
    bound_by_pid = {str(x.get("product_id") or ""): x for x in bindings}

    # All pre-existing bindings must resolve to exact active Arlight products in the allowed code.
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    products_by_sku = {str(x.get("sku")): x for x in snapshot["ozon_products"]["products"] if x.get("sku")}
    outside_bindings = []
    target_pid_by_offer = {}
    ozon_targets = []
    for offer in offers:
        if len(products[offer]) != 1 or len(attributes[offer]) != 1:
            raise RuntimeError("fresh_ozon_identity_ambiguous:" + offer)
        p, a = products[offer][0], attributes[offer][0]
        pid = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brand = attr_values(a, 85)
        tnved = codes(attr_values(a, 22232))
        blockers = []
        if p.get("is_archived") is not False:
            blockers.append("ozon_product_archived_or_status_unclear")
        if brand != ["Arlight"]:
            blockers.append("ozon_brand_mismatch_or_ambiguous")
        if tnved != ALLOWED_TNVED:
            blockers.append("ozon_tnved_out_of_scope_or_ambiguous")
        if not pid or not sku:
            blockers.append("missing_ozon_identity")
        existing = bound_by_pid.get(pid)
        if existing and str(existing.get("sku") or "") != sku:
            blockers.append("existing_binding_identity_conflict")
        target_pid_by_offer[offer] = pid
        ozon_targets.append({**targets[offer], "product_id": pid, "sku": sku,
            "live_name": p.get("name"), "brand_values": brand,
            "tnved_codes": sorted(tnved), "existing_binding": existing,
            "ozon_safe": not blockers, "ozon_blockers": blockers})
    target_pids = set(target_pid_by_offer.values())
    for binding in bindings:
        pid, sku = str(binding.get("product_id") or ""), str(binding.get("sku") or "")
        if pid in target_pids:
            continue
        product = products_by_sku.get(sku)
        if (not product or str(product.get("product_id") or "") != pid
                or product.get("is_archived") is not False
                or product.get("brand_values") != ["Arlight"]
                or codes(product.get("tnved_values") or []) != ALLOWED_TNVED):
            outside_bindings.append({"product_id": pid, "sku": sku,
                                     "product_status_code": binding.get("product_status_code"),
                                     "resolved_product": product})

    wb_targets = []
    expected_doc = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                    "endDate": wb_datetime(EXPIRY), "isEndless": False}
    for index, target in enumerate(ozon_targets, 1):
        offer = target["offer_id"]
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        blockers = []
        card = cards[0] if len(cards) == 1 else None
        if not card:
            blockers.append("no_exact_or_duplicate_wb_card")
            wb_targets.append({"offer_id": offer, "safe_for_wb": False, "blockers": blockers})
            continue
        wb_tnved = set()
        for item in card.get("characteristics") or []:
            label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
            if "тнвэд" in label or "тнвед" in label:
                raw = item.get("value")
                values = raw if isinstance(raw, list) else [raw]
                wb_tnved.update(str(v).split(" - ", 1)[0].strip() for v in values if v)
        if str(card.get("brand") or "").strip().casefold() != "arlight":
            blockers.append("wb_brand_mismatch_or_ambiguous")
        if wb_tnved != ALLOWED_TNVED:
            blockers.append("wb_tnved_out_of_scope_or_ambiguous")
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and not (len(same) == len(exact) == 1):
            blockers.append("same_number_metadata_conflict")
        payload = None if exact else merge_wb(card, [expected_doc])
        if not exact and payload is None:
            blockers.append("wb_merge_noop_unexpected")
        wb_targets.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "brand": card.get("brand"), "title": card.get("title"),
            "tnved_codes": sorted(wb_tnved), "existing_same_number": same,
            "already_exact": bool(exact), "safe_for_wb": not blockers,
            "blockers": blockers, "full_card": card})
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_read_only_preflight", "checked": index,
                              "targets": len(ozon_targets)}, ensure_ascii=False), flush=True)

    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_file": str(SOURCE), "source_sha256": actual_sha,
        "issue_date": ISSUE, "expire_date": EXPIRY,
        "source_official_url": "https://arlight.ru/upload/certificates/E8503D1F8C103B41B49B024538942102.pdf",
        "source_scope": "Arlight LED strips, series MOONLIGHT; TN VED 8539519009",
        "ozon_record": {k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
            "accordance_type_code", "status_code", "issue_date", "expire_date", "products_count")},
        "ozon_existing_binding_count": len(bindings), "ozon_unresolved_outside_bindings": outside_bindings,
        "assignment_target_count": len(targets),
        "ozon_safe_count": sum(x["ozon_safe"] for x in ozon_targets),
        "ozon_problem_counts": dict(collections.Counter(p for x in ozon_targets for p in x["ozon_blockers"])),
        "ozon_targets": ozon_targets,
        "wb_safe_count": sum(x.get("safe_for_wb") for x in wb_targets),
        "wb_already_exact_count": sum(x.get("already_exact") for x in wb_targets),
        "wb_problem_counts": dict(collections.Counter(p for x in wb_targets for p in x.get("blockers", []))),
        "wb_targets": wb_targets,
        "wb_review_left_pending": True, "local_source_deleted": False}
    save(OUT, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("ozon_targets", "wb_targets")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
