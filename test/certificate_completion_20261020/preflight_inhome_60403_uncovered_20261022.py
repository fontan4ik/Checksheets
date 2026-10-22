#!/usr/bin/env python3
"""Fresh scope preflight for uncovered IN HOME lamp products assigned to 60403/26."""
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

NUMBER = "ЕАЭС N RU Д-CN.PA03.B.60403/26"
SOURCE_REL = "output_to_user/certificates/group_2/IN_HOME/documents/2af3c6d70766_D4AD85E8BEBDCE783525AB54A97FAFC6.pdf"
SOURCE = ROOT / SOURCE_REL
SOURCE_SHA256 = "2af3c6d7076685571ca18ff8a7f2bfbbe76d9baf0d9732cd45134e6c7a21504f"
FSA_ID = 21351639
RECORD_ID = 5448292
ISSUE = "2026-04-24"
EXPIRY = "2027-04-21"
ALLOWED = {"8539520002", "8539520003", "8539520001", "8539520009"}
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SNAPSHOT = HERE / "live_marketplaces_snapshot_resume_20261022.json"
OUT = HERE / "inhome_60403_uncovered_preflight_20261022.json"


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def codes(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


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


def load_uncovered_assignments() -> dict[str, dict]:
    snapshot = json.loads(SNAPSHOT.read_text())
    products = snapshot["ozon_products"]["products"]
    by_sku = {str(p.get("sku")): p for p in products if p.get("sku")}
    covered = set()
    today = date.today().isoformat()
    for cert in snapshot["ozon_certificates"]["certificates"]:
        issue = str(cert.get("issue_date") or "")[:10]
        expiry = str(cert.get("expire_date") or "")[:10]
        if (cert.get("status_code") != "approved" or not expiry
                or issue > today or expiry < today):
            continue
        for binding in cert.get("live_bindings") or []:
            product = by_sku.get(str(binding.get("sku") or ""))
            if (binding.get("product_status_code") == "approved" and product
                    and str(product.get("product_id")) == str(binding.get("product_id"))):
                covered.add(str(product.get("product_id")))
    uncovered = {str(p.get("offer_id")) for p in products if not p.get("is_archived")
                 and str(p.get("product_id")) not in covered}
    targets = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (norm_number(row.get("Номер/название документа")) != norm_number(NUMBER)
                    or row.get("Локальный файл") != SOURCE_REL
                    or row.get("Бренд подтвержденный") != "IN HOME"
                    or row.get("Применимость") != "Подтверждено статусом покрытия"):
                continue
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer not in uncovered:
                continue
            if not offer or offer in targets:
                raise RuntimeError("missing_or_duplicate_uncovered_offer:" + offer)
            targets[offer] = {
                "offer_id": offer,
                "assignment_product_name": row.get("Название товара Ozon"),
                "assignment_scope_evidence": row.get("Основание сопоставления"),
                "source_url": row.get("URL документа"),
            }
    if len(targets) != 99:
        raise RuntimeError(f"unexpected_uncovered_target_count:{len(targets)}")
    return targets


def ozon_records(client: Client) -> list[dict]:
    rows = []
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
    actual_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest() if SOURCE.is_file() else ""
    if actual_hash != SOURCE_SHA256:
        raise RuntimeError("source_pdf_missing_or_hash_mismatch")
    assignments = load_uncovered_assignments()
    offers = sorted(assignments)
    client = Client()

    products = {}
    attributes = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        ps = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        attrs = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result")
        if not isinstance(ps, list) or not isinstance(attrs, list):
            raise RuntimeError("ozon_product_or_attribute_response_incomplete")
        for row in ps:
            offer = str(row.get("offer_id") or "")
            products[offer] = row
        for row in attrs:
            offer = str(row.get("offer_id") or "")
            attributes[offer] = row
    if set(products) != set(offers) or set(attributes) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_mismatch")

    matches = [r for r in ozon_records(client)
               if norm_number(r.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) != 1 or str(matches[0].get("certificate_id")) != str(RECORD_ID):
        raise RuntimeError("existing_ozon_record_identity_ambiguous")
    record = matches[0]
    bindings = client.ozon_bindings(RECORD_ID)
    bound_ids = {str(x.get("product_id")) for x in bindings}
    bound_skus = {str(x.get("sku")) for x in bindings}
    today = date.today().isoformat()
    record_approved_current = (record.get("status_code") == "approved"
        and str(record.get("issue_date") or "")[:10] == ISSUE
        and str(record.get("expire_date") or "")[:10] == EXPIRY
        and ISSUE <= today <= EXPIRY)

    ozon_targets = []
    for offer in offers:
        p, a = products[offer], attributes[offer]
        pid = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brand = attr_values(a, 85)
        tnved = codes(attr_values(a, 22232))
        problems = []
        if p.get("is_archived") is not False:
            problems.append("ozon_product_archived_or_status_unclear")
        if brand != ["IN HOME"]:
            problems.append("ozon_brand_mismatch_or_ambiguous")
        if len(tnved) != 1 or tnved[0] not in ALLOWED:
            problems.append("ozon_tnved_out_of_declaration_scope_or_ambiguous")
        if not record_approved_current:
            problems.append("ozon_record_not_current_and_approved")
        if not pid or not sku:
            problems.append("missing_ozon_identity")
        if pid in bound_ids or sku in bound_skus:
            problems.append("already_bound_or_identity_conflict")
        ozon_targets.append({**assignments[offer], "product_id": pid, "sku": sku,
            "live_name": p.get("name"), "brand_values": brand, "tnved_codes": tnved,
            "eligible_for_existing_record_bind": not problems, "problems": problems})

    wb_targets = []
    expected = {"type": 2, "number": NUMBER, "startDate": f"{ISSUE}T00:00:00Z",
                "endDate": f"{EXPIRY}T00:00:00Z", "isEndless": False}
    for i, target in enumerate(ozon_targets, 1):
        offer = target["offer_id"]
        cards = client.wb_cards(offer)
        cards = [x for x in cards if str(x.get("vendorCode") or "") == offer]
        problems = []
        card = cards[0] if len(cards) == 1 else None
        tnved = card_codes(card) if card else []
        exact = []
        already_exact = False
        if not card:
            problems.append("no_exact_wb_card" if not cards else "duplicate_wb_cards")
        else:
            if str(card.get("brand") or "").strip().casefold() != "in home":
                problems.append("wb_brand_mismatch_or_ambiguous")
            if len(tnved) != 1 or tnved[0] not in ALLOWED:
                problems.append("wb_tnved_out_of_declaration_scope_or_ambiguous")
            exact = [d for d in copy_documents(card)
                     if norm_number(d.get("number")) == norm_number(NUMBER)]
            if exact:
                already_exact = (len(exact) == 1 and str(exact[0].get("type")) == "2"
                    and str(exact[0].get("startDate", ""))[:10] == ISSUE
                    and str(exact[0].get("endDate", ""))[:10] == EXPIRY)
                if not already_exact:
                    problems.append("same_number_metadata_conflict")
        wb_targets.append({"offer_id": offer, "nmID": str(card.get("nmID") or "") if card else "",
            "brand": card.get("brand") if card else None, "title": card.get("title") if card else None,
            "tnved_codes": tnved, "existing_exact_documents": exact, "already_exact": already_exact,
            "safe_for_update": bool(card) and not problems and not already_exact,
            "problems": problems, "full_card": card})
        if i % 25 == 0:
            print(json.dumps({"phase": "wb_target_preflight", "checked": i,
                              "targets": len(ozon_targets)}, ensure_ascii=False), flush=True)

    output = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_pdf": str(SOURCE), "source_sha256": actual_hash,
        "fsa_record_id_from_source_qr": FSA_ID,
        "pdf_visible_metadata": {"issue_date": ISSUE, "expiry_date": EXPIRY,
            "product_scope": "IN HOME LED lamps; model list in attached appendix pages 2-8",
            "tnved_codes": sorted(ALLOWED),
            "registry_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/common",
            "current_registry_page_accessible": False},
        "source_snapshot_checked_at": json.loads(SNAPSHOT.read_text())["ozon_products"].get("checked_at"),
        "uncovered_source_assignments": len(assignments),
        "ozon_record": {k: record.get(k) for k in ("certificate_id", "certificate_number", "status_code",
            "issue_date", "expire_date", "products_count")},
        "ozon_live_bindings_before": len(bindings), "ozon_record_approved_and_current": record_approved_current,
        "ozon_safe_targets": sum(x["eligible_for_existing_record_bind"] for x in ozon_targets),
        "ozon_problem_counts": dict(collections.Counter(p for x in ozon_targets for p in x["problems"])),
        "ozon_targets": ozon_targets,
        "wb_exact_cards_found": sum(bool(x.get("full_card")) for x in wb_targets),
        "wb_safe_targets": sum(x["safe_for_update"] for x in wb_targets),
        "wb_already_exact_targets": sum(x["already_exact"] for x in wb_targets),
        "wb_problem_counts": dict(collections.Counter(p for x in wb_targets for p in x["problems"])),
        "wb_targets": wb_targets, "wb_review_left_pending": True, "local_source_deleted": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items() if k not in {"ozon_targets", "wb_targets"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
