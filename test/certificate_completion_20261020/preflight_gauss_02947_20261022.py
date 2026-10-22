#!/usr/bin/env python3
"""Fresh, read-only Ozon/WB scope check for Gauss certificate 02947/22."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

NUMBER = "ЕАЭС RU C-CN.HB54.B.02947/22"
SOURCE_REL = "output_to_user/certificates/group_1/documents/gauss/06b64537525886ce56ab0e3a.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA = "c1bae8dcead5bd3086090af159f5655a2460dbaa093140bac6068a4d64788108"
ISSUE = "2022-06-08"
EXPIRY = "2027-06-07"
ALLOWED_TNVED = {"9405420012"}
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
OCR = ROOT / "output_to_user/certificates/group_1/gauss_ocr.jsonl"
OUT = HERE / "gauss_02947_live_preflight_20261022.json"


def save(value: dict) -> None:
    temp = OUT.with_suffix(OUT.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)


def norm_article(value: str) -> str:
    table = str.maketrans({"Р": "P", "р": "P", "А": "A", "а": "A", "В": "B", "в": "B",
                           "С": "C", "с": "C", "Е": "E", "е": "E", "Н": "H", "н": "H",
                           "К": "K", "к": "K", "М": "M", "м": "M", "О": "O", "о": "O",
                           "Т": "T", "т": "T", "Х": "X", "х": "X"})
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().translate(table))


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def live_certificate_list(client: Client) -> list[dict]:
    records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        records.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return records
    raise RuntimeError("ozon_certificate_page_limit")


def baseline_uncovered(snapshot: dict) -> tuple[dict, set[str]]:
    products = snapshot["ozon_products"]["products"]
    by_sku = {str(p.get("sku")): p for p in products if p.get("sku")}
    covered = set()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for cert in snapshot["ozon_certificates"]["certificates"]:
        if (cert.get("status_code") != "approved"
                or str(cert.get("issue_date") or "")[:10] > today
                or str(cert.get("expire_date") or "")[:10] < today
                or not str(cert.get("expire_date") or "")[:10]):
            continue
        for binding in cert.get("live_bindings") or []:
            product = by_sku.get(str(binding.get("sku") or ""))
            if (binding.get("product_status_code") == "approved" and product
                    and str(product.get("product_id")) == str(binding.get("product_id"))):
                covered.add(str(product.get("product_id")))
    by_offer = {str(p.get("offer_id")): p for p in products if p.get("offer_id")}
    uncovered_offers = {str(p.get("offer_id")) for p in products if not p.get("is_archived")
                        and str(p.get("product_id")) not in covered}
    return by_offer, uncovered_offers


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_before_rerun")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source_file_missing_or_hash_mismatch")
    snapshot = json.loads(SNAPSHOT.read_text())
    if snapshot.get("complete") is not True or not all(snapshot.get(k, {}).get("complete") is True
            for k in ("ozon_products", "ozon_certificates", "wb_catalog", "wb_trash")):
        raise RuntimeError("complete_baseline_snapshot_required")
    ocr_by_path = {}
    for line in OCR.read_text().splitlines():
        row = json.loads(line)
        ocr_by_path[row.get("path", "")] = row.get("text", "")
    pdf_text = ocr_by_path.get(SOURCE_REL, "")
    norm_pdf = norm_article(pdf_text)
    if "9405420012" not in norm_pdf or "0294722" not in norm_pdf:
        raise RuntimeError("official_pdf_scope_or_number_missing_from_ocr")

    rows = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (norm_number(row.get("Номер/название документа")) != norm_number(NUMBER)
                    or row.get("Локальный файл") != SOURCE_REL
                    or row.get("Бренд подтвержденный") != "Gauss"
                    or row.get("Применимость") not in ("Подтверждено статусом покрытия", "Подтверждено источником")):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            model = offer.split("-", 1)[0]
            rows.append({"offer_id": offer, "model": model,
                         "model_explicit_in_pdf": bool(model and norm_article(model) in norm_pdf),
                         "source_title": row.get("Название товара Ozon"),
                         "source_evidence": row.get("Основание сопоставления"),
                         "validity_note": row.get("Сроки/валидность")})
    if not rows or len({x["offer_id"] for x in rows}) != len(rows):
        raise RuntimeError("assignment_rows_missing_or_duplicate")
    baseline_by_offer, uncovered_offers = baseline_uncovered(snapshot)
    offers = sorted({x["offer_id"] for x in rows})
    client = Client()
    products, attrs = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("ozon_product_or_attribute_page_invalid")
        for row in p_rows:
            products.setdefault(str(row.get("offer_id") or ""), []).append(row)
        for row in a_rows:
            attrs.setdefault(str(row.get("offer_id") or ""), []).append(row)
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_incomplete")

    live_records = live_certificate_list(client)
    matches = [r for r in live_records if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) > 1:
        raise RuntimeError("duplicate_live_ozon_document_records")
    record = matches[0] if matches else None
    if record and (record.get("type_code") != "certificate_of_conformity"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("live_ozon_document_metadata_conflict")
    existing_bindings = client.ozon_bindings(record["certificate_id"]) if record else []
    bound_pids = {str(x.get("product_id")) for x in existing_bindings}
    bound_skus = {str(x.get("sku")) for x in existing_bindings}

    ozon_targets = []
    for assignment in rows:
        offer = assignment["offer_id"]
        p_list, a_list = products[offer], attrs[offer]
        reasons = []
        if len(p_list) != 1 or len(a_list) != 1:
            reasons.append("live_product_or_attributes_not_unique")
            product, attr = (p_list[0] if p_list else {}), (a_list[0] if a_list else {})
        else:
            product, attr = p_list[0], a_list[0]
        pid, sku = str(product.get("product_id") or product.get("id") or ""), str(product.get("sku") or "")
        brands = attr_values(attr, 85)
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in attr_values(attr, 22232)})
        if product.get("is_archived") is not False:
            reasons.append("product_archived_or_status_unclear")
        if len(brands) != 1 or brands[0].casefold() != "gauss":
            reasons.append("live_brand_mismatch_or_ambiguous")
        if tnved != sorted(ALLOWED_TNVED):
            reasons.append("live_tnved_out_of_scope_or_ambiguous")
        if not assignment["model_explicit_in_pdf"]:
            reasons.append("exact_model_not_listed_in_pdf")
        baseline = baseline_by_offer.get(offer)
        if (not baseline or str(baseline.get("product_id")) != pid
                or str(baseline.get("sku")) != sku or offer not in uncovered_offers):
            reasons.append("baseline_identity_changed_or_product_not_uncovered")
        if record and (pid in bound_pids or sku in bound_skus):
            reasons.append("already_bound_or_binding_identity_conflict")
        ozon_targets.append({**assignment, "product_id": pid, "sku": sku,
            "live_name": product.get("name"), "live_brands": brands, "live_tnved": tnved,
            "baseline_product_id": str((baseline or {}).get("product_id") or ""),
            "baseline_sku": str((baseline or {}).get("sku") or ""),
            "safe_for_ozon": not reasons, "ozon_exclusion_reasons": reasons})

    # Per-offer queries remain reliable when the large WB catalog cursor shifts after writes.
    wb_targets, wb_preexisting, wb_excluded = [], [], []
    desired = {"type": 1, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
               "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
    for index, assignment in enumerate(rows, 1):
        offer = assignment["offer_id"]
        if not assignment["model_explicit_in_pdf"]:
            wb_excluded.append({"offer_id": offer, "reason": "exact_model_not_listed_in_pdf"})
            continue
        cards = [c for c in client.wb_cards(offer) if str(c.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_excluded.append({"offer_id": offer, "reason": "wb_card_missing_or_duplicate", "card_count": len(cards)})
            continue
        card = cards[0]
        tnved = code_values(card)
        if str(card.get("brand") or "").strip().casefold() != "gauss" or tnved != sorted(ALLOWED_TNVED):
            wb_excluded.append({"offer_id": offer, "reason": "wb_brand_or_tnved_out_of_scope",
                                "brand": card.get("brand"), "tnved": tnved})
            continue
        documents = ((card.get("documents") or {}).get("items") or [])
        same = [d for d in documents if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same:
            exact = [d for d in same if str(d.get("type")) == "1"
                     and str(d.get("startDate") or "")[:10] == ISSUE
                     and str(d.get("endDate") or "")[:10] == EXPIRY
                     and d.get("isEndless") is False]
            if len(same) == 1 and len(exact) == 1:
                wb_preexisting.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                    "verdict": exact[0].get("verdict"), "document": exact[0]})
            else:
                wb_excluded.append({"offer_id": offer, "reason": "same_number_document_conflict", "documents": same})
            continue
        wb_targets.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""), "card": card,
                           "tnved": tnved, "brand": card.get("brand")})
        if index % 20 == 0:
            print(json.dumps({"phase": "wb_preflight", "checked_assignments": index,
                              "offers": len(rows), "safe_wb_cards": len(wb_targets)}, ensure_ascii=False), flush=True)

    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_file": str(SOURCE), "source_sha256": SOURCE_SHA,
        "source_bytes": SOURCE.stat().st_size, "issue_date": ISSUE, "expire_date": EXPIRY,
        "allowed_tnved": sorted(ALLOWED_TNVED), "assignment_rows": len(rows),
        "pdf_explicit_models": sum(bool(x["model_explicit_in_pdf"]) for x in rows),
        "ozon_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
            "status_code", "issue_date", "expire_date", "products_count")} if record else None),
        "ozon_record_bindings_before": len(existing_bindings),
        "ozon_safe_targets": sum(bool(x["safe_for_ozon"]) for x in ozon_targets),
        "ozon_exclusion_counts": dict(collections.Counter(r for x in ozon_targets for r in x["ozon_exclusion_reasons"])),
        "ozon_targets": ozon_targets,
        "wb_update_targets": len(wb_targets), "wb_exact_preexisting": len(wb_preexisting),
        "wb_exclusion_counts": dict(collections.Counter(x["reason"] for x in wb_excluded)),
        "wb_targets": wb_targets, "wb_preexisting": wb_preexisting, "wb_excluded": wb_excluded,
        "wb_review_left_pending": True, "local_source_deleted": False}
    save(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("ozon_targets", "wb_targets", "wb_preexisting", "wb_excluded")},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
