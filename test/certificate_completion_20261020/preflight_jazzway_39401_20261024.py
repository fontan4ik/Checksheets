#!/usr/bin/env python3
"""Read-only fresh cross-platform preflight for Jazzway declaration 39401/24."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА03.В.39401/24"
ISSUE = "2024-04-08"
EXPIRY = "2029-04-07"
FSA_ID = "18798316"
FILE = ROOT / "output_to_user/certificates/group_2/JAZZWAY/documents/svetilniki-ptr-s-cokolem-ds-tr-ts-037-07.04.2029_4bc83219de73.pdf"
SHA = "4bc83219de73df55b59d8de26bdbc53161ce1280cb93d0c0a334660b2acc90e1"
OUT = HERE / "jazzway_39401_crossplatform_preflight_20261024.json"
ALLOWED_TNVED = {"9405110039"}
EXPECTED_OFFERS = {
    "5037830-1", "5037892-1", "5037939-1", "5037953-1", "5037984A-1",
    "5038004A-1", "5038035A-1", "5038059A-1", "5038073A-1", "5038097A-1",
    "5039124-1", "5039148-1", "5040182-1", "5040205-1", "5049208-1",
    "5049208-2", "5049222-1", "5049222-2", "5052178-1", "5052192-1",
}


def values(row: dict, attribute_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip() for x in
            ((attrs.get(str(attribute_id)) or {}).get("values") or [])
            if str(x.get("value") or "").strip()]


def codes(items: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in items if str(x).strip()})


def wb_codes(card: dict) -> list[str]:
    found = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            raw = item.get("value")
            found.extend(raw if isinstance(raw, list) else [raw])
    return codes([str(x) for x in found if x])


def ozon_records(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_exists_inspect_first")
    if not FILE.is_file() or hashlib.sha256(FILE.read_bytes()).hexdigest() != SHA:
        raise RuntimeError("source_file_hash_mismatch")
    assignments = []
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(
            encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("Номер/название документа") != NUMBER:
                continue
            if row.get("Локальный файл") != str(FILE.relative_to(ROOT)):
                raise RuntimeError("assignment_path_mismatch")
            if row.get("Бренд подтвержденный") != "Jazzway":
                raise RuntimeError("assignment_brand_mismatch")
            if row.get("Применимость") != "Подтверждено статусом покрытия":
                raise RuntimeError("assignment_scope_not_confirmed")
            if row.get("SHA256 фактический") != SHA:
                raise RuntimeError("assignment_hash_mismatch")
            assignments.append(str(row.get("Артикул продавца") or "").strip())
    if len(assignments) != len(EXPECTED_OFFERS) or set(assignments) != EXPECTED_OFFERS:
        raise RuntimeError("assignment_target_set_changed")

    client = Client()
    offers = sorted(EXPECTED_OFFERS)
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attributes = client.call("ozon", "/v4/product/info/attributes",
                             {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    if len(products) != len(offers) or len(attributes) != len(offers):
        raise RuntimeError("fresh_ozon_item_count_mismatch")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attributes}
    if set(pmap) != EXPECTED_OFFERS or set(amap) != EXPECTED_OFFERS:
        raise RuntimeError("fresh_ozon_offer_set_mismatch")

    matching = [x for x in ozon_records(client)
                if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matching) > 1:
        raise RuntimeError("duplicate_ozon_certificate_records")
    record = matching[0] if matching else None
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("ozon_existing_record_metadata_conflict")
    bindings = client.ozon_bindings(int(record["certificate_id"])) if record else []
    ozon_by_pid: dict[str, list[dict]] = {}
    for item in bindings:
        ozon_by_pid.setdefault(str(item.get("product_id") or ""), []).append(item)

    targets = []
    for offer in offers:
        p, a = pmap[offer], amap[offer]
        brand = values(a, 85)
        tnved = codes(values(a, 22232))
        model_match = re.search(r"PTR\s*(\d+)", str(p.get("name") or ""), flags=re.I)
        model_number = int(model_match.group(1)) if model_match else None
        product_id, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        ozon_blockers = []
        if p.get("is_archived") is not False:
            ozon_blockers.append("archived_or_unclear")
        if brand != ["Jazzway"]:
            ozon_blockers.append("brand_mismatch")
        if tnved != sorted(ALLOWED_TNVED):
            ozon_blockers.append("tnved_mismatch")
        if model_number is None or not 24 <= model_number <= 48:
            ozon_blockers.append("model_series_not_in_declaration")
        existing = ozon_by_pid.get(product_id, [])
        if len(existing) > 1:
            ozon_blockers.append("duplicate_existing_binding")
        elif existing and str(existing[0].get("sku") or "") != sku:
            ozon_blockers.append("existing_binding_sku_mismatch")
        elif existing and str(existing[0].get("product_status_code") or "").casefold() != "approved":
            ozon_blockers.append("existing_binding_not_approved")

        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        wb_card = cards[0] if len(cards) == 1 else {}
        wb_brand = str(wb_card.get("brand") or "")
        wb_tnved = wb_codes(wb_card) if wb_card else []
        title = str(wb_card.get("title") or "")
        wb_model_match = re.search(r"PTR\s*(\d+)", title, flags=re.I)
        wb_model = int(wb_model_match.group(1)) if wb_model_match else None
        same = [x for x in ((wb_card.get("documents") or {}).get("items") or [])
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        wb_blockers = []
        if len(cards) != 1:
            wb_blockers.append("missing_or_duplicate_card")
        if wb_brand.casefold() != "jazzway":
            wb_blockers.append("brand_mismatch")
        if wb_tnved != sorted(ALLOWED_TNVED):
            wb_blockers.append("tnved_mismatch")
        if wb_model is None or not 24 <= wb_model <= 48:
            wb_blockers.append("model_series_not_in_declaration")
        if same and (len(same) != 1 or len(exact) != 1):
            wb_blockers.append("same_number_document_conflict")
        targets.append({"offer_id": offer, "product_id": product_id, "sku": sku,
                        "ozon_name": p.get("name"), "ozon_brand": brand, "ozon_tnved": tnved,
                        "ozon_model_number": model_number, "ozon_existing_binding_count": len(existing),
                        "ozon_existing_binding_status": existing[0].get("product_status_code") if len(existing) == 1 else None,
                        "ozon_safe": not ozon_blockers, "ozon_blockers": ozon_blockers,
                        "nmID": str(wb_card.get("nmID") or ""), "wb_brand": wb_brand,
                        "wb_title": title, "wb_tnved": wb_tnved, "wb_model_number": wb_model,
                        "wb_existing_exact": bool(exact), "wb_safe": not wb_blockers,
                        "wb_blockers": wb_blockers})

    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
              "document_type": "declaration", "fsa_record_id": FSA_ID,
              "fsa_url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product",
              "fsa_status": "Действует", "issue_date": ISSUE, "expiry_date": EXPIRY,
              "fsa_tnved": sorted(ALLOWED_TNVED), "fsa_models": list(range(24, 49)),
              "sample_production_cutoff": "2024-01",
              "source_file": str(FILE.relative_to(ROOT)), "source_sha256": SHA,
              "ozon_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code",
                               "status_code", "issue_date", "expire_date", "products_count")} if record else None),
              "ozon_bindings_visible_before": len(bindings), "targets": targets,
              "ozon_safe_count": sum(x["ozon_safe"] for x in targets),
              "ozon_blocker_counts": dict(Counter(reason for x in targets for reason in x["ozon_blockers"])),
              "wb_safe_count": sum(x["wb_safe"] for x in targets),
              "wb_blocker_counts": dict(Counter(reason for x in targets for reason in x["wb_blockers"])),
              "wb_already_exact_count": sum(x["wb_existing_exact"] for x in targets),
              "writes_performed": False, "local_files_deleted": False}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("checked_at_utc", "number", "ozon_record", "ozon_safe_count",
          "ozon_blocker_counts", "wb_safe_count", "wb_blocker_counts", "wb_already_exact_count")},
          ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
