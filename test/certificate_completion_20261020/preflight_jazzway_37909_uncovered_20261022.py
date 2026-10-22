#!/usr/bin/env python3
"""Fresh exact-scope preflight for uncovered Jazzway 37909/22 offers."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
SOURCE_REL = "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_c5a7e15132.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA256 = "ac05304912cfc122dfe810a85f16a4f801e680da3b6ccf93bff2707cfa8335ae"
RECORD_ID = 5458891
ISSUE = "2022-11-21"
EXPIRY = "2027-11-20"
ALLOWED = {"8539520001", "8539520002", "8539520003", "8539520009"}
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
OUT = HERE / "jazzway_37909_uncovered_preflight_20261022.json"


def values(row: dict, aid: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(aid)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def codes(items: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in items if str(x).strip()})


def card_codes(card: dict) -> list[str]:
    result = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        vals = raw if isinstance(raw, list) else [raw]
        result.extend(str(v or "").split(" - ", 1)[0].strip() for v in vals if v)
    return sorted(set(result))


def uncovered_offers(snapshot: dict) -> set[str]:
    products = snapshot["ozon_products"]["products"]
    by_sku = {str(p.get("sku")): p for p in products if p.get("sku")}
    covered = set()
    today = date.today().isoformat()
    for cert in snapshot["ozon_certificates"]["certificates"]:
        issue = str(cert.get("issue_date") or "")[:10]
        expiry = str(cert.get("expire_date") or "")[:10]
        if cert.get("status_code") != "approved" or not expiry or issue > today or expiry < today:
            continue
        for binding in cert.get("live_bindings") or []:
            p = by_sku.get(str(binding.get("sku") or ""))
            if binding.get("product_status_code") == "approved" and p and str(p.get("product_id")) == str(binding.get("product_id")):
                covered.add(str(p.get("product_id")))
    return {str(p.get("offer_id")) for p in products
            if not p.get("is_archived") and str(p.get("product_id")) not in covered}


def load_targets() -> dict[str, dict]:
    snapshot = json.loads(SNAPSHOT.read_text())
    uncovered = uncovered_offers(snapshot)
    targets = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (norm_number(row.get("Номер/название документа")) != norm_number(NUMBER)
                    or row.get("Локальный файл") != SOURCE_REL
                    or row.get("Бренд подтвержденный") != "Jazzway"
                    or row.get("Применимость") != "Подтверждено статусом покрытия"):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer not in uncovered:
                continue
            if not offer or offer in targets:
                raise RuntimeError("missing_or_duplicate_uncovered_assignment:" + offer)
            targets[offer] = {"offer_id": offer,
                "assignment_product_name": row.get("Название товара Ozon"),
                "scope_evidence": row.get("Основание сопоставления"),
                "source_url": row.get("URL документа")}
    if len(targets) != 133:
        raise RuntimeError(f"unexpected_uncovered_assignment_count:{len(targets)}")
    return targets


def all_records(client: Client) -> list[dict]:
    items = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("certificate_page_incomplete")
        items.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return items
    raise RuntimeError("certificate_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_before_retry")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_hash_mismatch_or_missing")
    assignment = load_targets()
    offers = sorted(assignment)
    client = Client()
    products, attrs = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        ps = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        aa = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(ps, list) or not isinstance(aa, list):
            raise RuntimeError("ozon_product_or_attribute_response_incomplete")
        for row in ps: products[str(row.get("offer_id") or "")] = row
        for row in aa: attrs[str(row.get("offer_id") or "")] = row
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_mismatch")

    records = [x for x in all_records(client) if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) != 1 or str(records[0].get("certificate_id")) != str(RECORD_ID):
        raise RuntimeError("existing_ozon_record_ambiguous")
    record = records[0]
    bindings = client.ozon_bindings(RECORD_ID)
    by_product = {str(x.get("product_id")): x for x in bindings}
    by_sku = {str(x.get("sku")): x for x in bindings}
    today = date.today().isoformat()
    record_current_approved = (record.get("status_code") == "approved"
        and str(record.get("issue_date") or "")[:10] == ISSUE
        and str(record.get("expire_date") or "")[:10] == EXPIRY
        and ISSUE <= today <= EXPIRY)

    ozon_targets = []
    for offer in offers:
        p, a = products[offer], attrs[offer]
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        brand = values(a, 85)
        tnved = codes(values(a, 22232))
        prior = by_product.get(pid) or by_sku.get(sku)
        prior_exact = bool(prior and str(prior.get("product_id")) == pid and str(prior.get("sku")) == sku)
        problems = []
        if p.get("is_archived") is not False: problems.append("archived_or_status_unclear")
        if brand != ["Jazzway"]: problems.append("ozon_brand_not_exact_jazzway")
        if len(tnved) != 1 or tnved[0] not in ALLOWED: problems.append("ozon_tnved_out_of_document_scope")
        if not record_current_approved: problems.append("existing_record_not_current_approved")
        if not pid or not sku: problems.append("missing_product_identity")
        if prior:
            problems.append("prior_binding_" + str(prior.get("product_status_code") or "unknown"))
        ozon_targets.append({**assignment[offer], "product_id": pid, "sku": sku,
            "live_name": p.get("name"), "brand_values": brand, "tnved_codes": tnved,
            "prior_binding": prior, "prior_binding_identity_exact": prior_exact,
            "safe_for_new_bind": not problems, "problems": problems})

    wb_targets = []
    for index, target in enumerate(ozon_targets, 1):
        offer = target["offer_id"]
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        card = cards[0] if len(cards) == 1 else None
        problems = []
        tnved = card_codes(card) if card else []
        same = []
        already_exact = False
        if not card:
            problems.append("no_exact_wb_card" if not cards else "duplicate_wb_card")
        else:
            brand = str(card.get("brand") or "").strip().casefold()
            if brand not in {"jazzway", "jazz way"}: problems.append("wb_brand_mismatch")
            if len(tnved) != 1 or tnved[0] not in ALLOWED: problems.append("wb_tnved_out_of_document_scope")
            same = [x for x in copy_documents(card) if norm_number(x.get("number")) == norm_number(NUMBER)]
            if same:
                already_exact = (len(same) == 1 and str(same[0].get("type")) == "2"
                    and str(same[0].get("startDate", ""))[:10] == ISSUE
                    and str(same[0].get("endDate", ""))[:10] == EXPIRY)
                if not already_exact: problems.append("same_number_metadata_conflict")
        wb_targets.append({"offer_id": offer, "nmID": str(card.get("nmID") or "") if card else "",
            "brand": card.get("brand") if card else None, "title": card.get("title") if card else None,
            "tnved_codes": tnved, "existing_exact_documents": same,
            "already_exact": already_exact,
            "safe_for_update": bool(card) and not problems and not already_exact,
            "problems": problems, "full_card": card})
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_target_preflight", "checked": index, "targets": len(offers)}, ensure_ascii=False), flush=True)

    out = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_pdf": str(SOURCE), "source_sha256": SOURCE_SHA256,
        "source_url": "https://jazz-way.com/docs/sertifikaty/lampy-svetodiodnye-ds-tr-ts-037-20.11.2027.pdf",
        "source_pdf_scope_tnved": sorted(ALLOWED),
        "fsa_registry_note": "FSA public registry access previously returned HTTP 403; exact document is already in Ozon approved record.",
        "uncovered_source_assignments": len(assignment),
        "ozon_record": {k: record.get(k) for k in ("certificate_id", "certificate_number", "status_code", "issue_date", "expire_date", "products_count")},
        "ozon_bindings_before": len(bindings), "ozon_record_current_approved": record_current_approved,
        "ozon_safe_targets": sum(x["safe_for_new_bind"] for x in ozon_targets),
        "ozon_problem_counts": dict(collections.Counter(p for x in ozon_targets for p in x["problems"])),
        "ozon_targets": ozon_targets,
        "wb_exact_cards_found": sum(bool(x.get("full_card")) for x in wb_targets),
        "wb_safe_targets": sum(x["safe_for_update"] for x in wb_targets),
        "wb_already_exact_targets": sum(x["already_exact"] for x in wb_targets),
        "wb_problem_counts": dict(collections.Counter(p for x in wb_targets for p in x["problems"])),
        "wb_targets": wb_targets, "wb_review_left_pending": True, "local_source_deleted": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in out.items() if k not in {"ozon_targets", "wb_targets"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
