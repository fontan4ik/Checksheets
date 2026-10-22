"""Fresh no-write Ozon/source preflight for active Arlight declaration 41382/26."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

LOCAL_MAP = ROOT / "test/certificate_cleanup_20261006/local_map.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/F1AD317FA132F2448DFFCC8233E3D0C0.pdf"
OUT = BASE / "arlight_41382_ozon_preflight_scoped_v2_20261012.json"
WB_TARGET_LIST = BASE / "arlight_41382_wb_target_list_scoped_v2_20261012.json"
WB_IDENTITY_SNAPSHOT = BASE / "wb_live_refresh_20261012_1418.json"
NUMBER = "ЕАЭС N RU Д-RU.РА08.В.41382/26"
SOURCE_NUMBER = "RU Д-RU.PA08.B.41382/26"
SOURCE_SHA256 = "f21eee1e430f86bbef6f7570767243bf27dfe3fe7b7648e58ff7a1b87b04e193"
ISSUE_DATE = "2026-09-16"
EXPIRY_DATE = "2031-09-15"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/21895502/product"
FSA_SERIES = {"SP", "IM", "MS", "LTD", "LGD", "DL", "ALT", "CL", "LT", "LTM"}
FSA_TNVED = {"9405110039", "9405110013", "9405110033", "9405420039"}
SERIES_RE = re.compile(r"(?<![A-Z0-9])(LTM|LTD|LGD|ALT|IM|MS|SP|DL|CL|LT)(?=-|[A-Z0-9])", re.I)


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def read_certificates(client: Client) -> list[dict]:
    rows = []
    page, last_count = 1, 0
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result", {})
        batch, count = result.get("certificates"), result.get("page_count")
        if not isinstance(batch, list) or not isinstance(count, int) or count < last_count or page > count:
            raise RuntimeError("Ozon certificate pagination invalid or moved backwards")
        last_count = count
        rows.extend(batch)
        if page >= count or len(batch) < 100:
            break
        page += 1
    if len({str(x.get("certificate_id")) for x in rows}) != len(rows):
        raise RuntimeError("Duplicate Ozon certificate IDs in live certificate list")
    return rows


def main() -> None:
    if OUT.exists() or WB_TARGET_LIST.exists():
        raise RuntimeError("41382 preflight artifacts already exist; inspect before regenerating")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Local official manufacturer PDF missing or hash changed")

    local = json.loads(LOCAL_MAP.read_text())
    groups = [x for x in local.get("groups", []) if x.get("sha256") == SOURCE_SHA256]
    if len(groups) != 1:
        raise RuntimeError("Source map does not have one exact 41382/26 group")
    group = groups[0]
    if (group.get("issues") or not group.get("eligible_for_live_comparison")
            or {norm(x) for x in group.get("document_numbers", []) if x} != {norm(SOURCE_NUMBER)}):
        raise RuntimeError("Source map contains an unresolved identity or document-number conflict")

    assignments = {}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256 фактический") == SOURCE_SHA256:
                offer = str(row.get("Артикул продавца") or "")
                if not offer or offer in assignments:
                    raise RuntimeError("Assignment rows contain a missing or duplicate exact offer")
                assignments[offer] = row
    source_bindings = {str(x["offer_id"]): x for x in group.get("bindings", [])}
    if len(source_bindings) != 368 or set(source_bindings) != set(assignments):
        raise RuntimeError("Exact manufacturer/source-map offer counts differ from 368")
    wb_snapshot = json.loads(WB_IDENTITY_SNAPSHOT.read_text())
    if (not wb_snapshot.get("complete") or wb_snapshot.get("duplicate_nmids") != 0
            or wb_snapshot.get("unique_cards") != 19962):
        raise RuntimeError("Same-day complete WB identity snapshot is unavailable")
    wb_identity_by_offer = {}
    for card in wb_snapshot.get("cards") or []:
        offer = str(card.get("vendorCode") or "")
        if offer in wb_identity_by_offer:
            raise RuntimeError("Duplicate vendorCode in same-day WB identity snapshot")
        wb_identity_by_offer[offer] = str(card.get("nmID"))

    target_map = {}
    for offer, binding in source_bindings.items():
        row = assignments[offer]
        if (binding.get("ozon_product_ids") is None or len(binding["ozon_product_ids"]) != 1
                or binding.get("ozon_skus") is None or len(binding["ozon_skus"]) != 1
                or row.get("Бренд подтвержденный") != "Arlight" or row.get("Бренд Ozon") != "Arlight"
                or norm(row.get("Номер/название документа")) != norm(NUMBER)
                or row.get("Тип документа") != "Декларация соответствия"
                or row.get("SHA256 заявленный") != SOURCE_SHA256
                or row.get("Статус покрытия артикула") != "найдены сертификаты/декларации"
                or not row.get("Основание сопоставления", "").startswith("Точный артикул в официальном листинге/карточке:")):
            raise RuntimeError(f"Source assignment or exact offer identity is incomplete: {offer}")
        target_map[offer] = {"offer_id": offer, "product_id": str(binding["ozon_product_ids"][0]),
                             "sku": str(binding["ozon_skus"][0]), "wb_nmID": wb_identity_by_offer.get(offer),
                             "assignment_title": row.get("Название товара Ozon"),
                             "manufacturer_article_proof": row.get("Основание сопоставления"),
                             "manufacturer_proof_url": row.get("URL карточки/основания")}
    if any(not x["wb_nmID"] or x["wb_nmID"] == "None" for x in target_map.values()):
        raise RuntimeError("One or more target WB nmIDs are missing from the same-day full identity snapshot")
    if (len({x["sku"] for x in target_map.values()}) != 368
            or len({x["product_id"] for x in target_map.values()}) != 368
            or len({x["wb_nmID"] for x in target_map.values()}) != 368):
        raise RuntimeError("Source crosswalk product/SKU/nmID mappings are not one-to-one")

    client = Client()
    products = {}
    offers = sorted(target_map)
    for offset in range(0, len(offers), 100):
        batch = offers[offset:offset + 100]
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in products:
                raise RuntimeError("Ozon product read returned an unknown or duplicate offer")
            products[offer] = row
    if set(products) != set(target_map):
        raise RuntimeError(f"Fresh Ozon product read found {len(products)}/368 exact offers")

    live = read_certificates(client)
    live_by_number = [x for x in live if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if len(live_by_number) > 1:
        raise RuntimeError("Ozon already has multiple records with this normalized declaration number")
    exact_record = live_by_number[0] if live_by_number else None
    info = None
    info_lookup = None
    if exact_record:
        info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result", {})
        if (str(info.get("certificate_id")) != str(exact_record.get("certificate_id"))
                or str(info.get("issue_date", ""))[:10] != ISSUE_DATE
                or str(info.get("expire_date", ""))[:10] != EXPIRY_DATE
                or str(info.get("type_code", "")).lower() not in {"declaration", "declaration_of_conformity"}
                or str(info.get("accordance_type_code", "")).upper() != "EAEU"):
            raise RuntimeError("Existing exact Ozon document record conflicts with official FSA data")
    else:
        # A direct exact-number lookup complements the full list snapshot.
        response = client.http.post(
            "https://api-seller.ozon.ru/v1/product/certificate/info",
            data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
            headers=client.ozon_headers, timeout=(15, 60))
        try:
            body = response.json()
        except ValueError:
            body = {}
        info_lookup = {"http_status": response.status_code, "error_code": body.get("code")}
        if response.status_code != 404 or body.get("code") != 5:
            raise RuntimeError("Ozon exact-number query failed to confirm absence")

    target_values = list(target_map.values())
    batch_attrs = {}
    for offset in range(0, len(offers), 50):
        batch = offers[offset:offset + 50]
        rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": 100,
        }).get("result") or []
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in batch_attrs:
                raise RuntimeError("Ozon attribute read returned an unknown or duplicate offer")
            batch_attrs[offer] = row
    if set(batch_attrs) != set(target_map):
        raise RuntimeError(f"Ozon attribute read found {len(batch_attrs)}/368 exact offers")

    target_rows, issues, tnved_scope_exclusions = [], [], []
    brands, tnveds, families = Counter(), Counter(), Counter()
    current_certificate_ids = {}
    for offer in offers:
        target = target_map[offer]
        product = products[offer]
        if (str(product.get("id") or product.get("product_id")) != target["product_id"]
                or str(product.get("sku")) != target["sku"] or product.get("is_archived")):
            issues.append({"offer_id": offer, "kind": "product_identity_or_archive_conflict",
                           "live_id": str(product.get("id") or product.get("product_id")),
                           "live_sku": str(product.get("sku")), "is_archived": product.get("is_archived")})
        attrs = {str(x.get("id")): x for x in batch_attrs[offer].get("attributes") or []}
        get_values = lambda key: [str(v.get("value")) for v in (attrs.get(key) or {}).get("values") or []]
        brand_values = get_values("85")
        tnved_values = get_values("22232")
        model = str(product.get("name") or "")
        matched_families = sorted({x.upper() for x in SERIES_RE.findall(model)})
        brands.update(brand_values)
        tnved_codes = sorted({x.strip().split(" - ", 1)[0] for x in tnved_values if x.strip()})
        tnveds.update(tnved_codes)
        families.update(matched_families)
        if brand_values != ["Arlight"]:
            issues.append({"offer_id": offer, "kind": "brand_mismatch", "values": brand_values})
        if not matched_families or not set(matched_families).issubset(FSA_SERIES):
            issues.append({"offer_id": offer, "kind": "model_series_not_proven_in_fsa_scope",
                           "model_name": model, "matched_families": matched_families})
        outside_codes = sorted(set(tnved_codes) - FSA_TNVED)
        if not tnved_codes:
            issues.append({"offer_id": offer, "kind": "tnved_not_within_exact_fsa_list",
                           "values": tnved_values, "outside_codes": outside_codes})
        elif outside_codes:
            tnved_scope_exclusions.append({"offer_id": offer, "product_id": target["product_id"],
                                           "sku": target["sku"], "wb_nmID": target["wb_nmID"],
                                           "tnved_values": tnved_values, "outside_codes": outside_codes,
                                           "reason": "Ozon TN VED is not listed on the official FSA declaration"})
        target_rows.append({**target, "product_name": model, "brand": brand_values,
                            "model_families": matched_families, "tnved_values": tnved_values,
                            "tnved_in_scope": bool(tnved_codes) and not outside_codes,
                            "category_id": product.get("description_category_id"),
                            "type_id": product.get("type_id")})

    eligible_targets = [x for x in target_rows if x.get("tnved_in_scope")]
    if exact_record:
        bindings = client.ozon_bindings(int(exact_record["certificate_id"]))
        bound_by_sku = {}
        for row in bindings:
            bound_by_sku.setdefault(str(row.get("sku")), []).append(row)
        missing = [x["sku"] for x in eligible_targets if x["sku"] not in bound_by_sku]
        duplicates = [sku for sku, items in bound_by_sku.items() if len(items) > 1]
        identity_conflicts = [sku for x in eligible_targets for sku in [x["sku"]]
                              if sku in bound_by_sku and {str(y.get("product_id")) for y in bound_by_sku[sku]}
                              != {x["product_id"]}]
    else:
        bindings, missing, duplicates, identity_conflicts = [], [x["sku"] for x in eligible_targets], [], []

    plan = {"checked_at": now(), "read_only": True, "number": NUMBER,
            "source_number": SOURCE_NUMBER, "issue_date": ISSUE_DATE, "expiry_date": EXPIRY_DATE,
            "fsa_record_id": 21895502, "fsa_registry_url": FSA_URL,
            "fsa_status": "Действует", "fsa_applicant": "ООО \"АРЛАЙТ РУС\"",
            "fsa_product_scope": "Светильники светодиодные Arlight типов SP, IM, MS, LTD, LGD, DL, ALT, CL, LT, LTM",
            "fsa_tnved_codes": sorted(FSA_TNVED), "source_file": str(SOURCE),
            "source_file_bytes": SOURCE.stat().st_size, "source_sha256": SOURCE_SHA256,
            "source_map_issues": group.get("issues"), "source_map_count": len(source_bindings),
            "manufacturer_assignment_rows": len(assignments), "official_manufacturer_download_verified": True,
            "ozon_products_checked_at": now(), "ozon_active_exact_products": len(products) - len(issues),
            "ozon_product_count": len(products), "ozon_brand_counts": dict(brands),
            "ozon_tnved_counts": dict(tnveds), "matched_model_family_counts": dict(families),
            "ozon_certificate_records_checked": len(live), "existing_exact_ozon_record": exact_record,
            "existing_exact_certificate_info": info, "direct_absence_query": info_lookup,
            "existing_binding_count": len(bindings), "eligible_target_count": len(eligible_targets),
            "tnved_scope_exclusion_count": len(tnved_scope_exclusions),
            "tnved_scope_exclusions": tnved_scope_exclusions, "missing_skus": missing,
            "duplicate_skus": duplicates, "binding_identity_conflicts": identity_conflicts,
            "issues": issues, "targets": target_rows}
    plan["ready_for_wb_full_read_and_ozon_create_or_bind"] = (
        len(target_rows) == 368 and len(eligible_targets) > 0 and not issues and not duplicates and not identity_conflicts
        and group.get("issues") == [] and len(assignments) == 368
        and all(x["model_families"] and set(x["model_families"]).issubset(FSA_SERIES) for x in target_rows))
    save(OUT, plan)
    wb_targets = {"created_at": now(), "number": NUMBER, "target_count": len(eligible_targets),
                  "source_product_count": len(target_rows),
                  "tnved_scope_exclusions": tnved_scope_exclusions,
                  "updates": [{"offer_id": x["offer_id"], "nmID": x["wb_nmID"]} for x in eligible_targets]}
    save(WB_TARGET_LIST, wb_targets)
    print(json.dumps({"path": str(OUT), "target_count": len(target_rows),
                      "ready_for_wb_full_read_and_ozon_create_or_bind": plan["ready_for_wb_full_read_and_ozon_create_or_bind"],
                      "existing_exact_record_count": 1 if exact_record else 0,
                      "existing_binding_count": len(bindings), "missing_sku_count": len(missing),
                      "issue_count": len(issues), "issue_sample": issues[:12],
                      "eligible_target_count": len(eligible_targets),
                      "tnved_scope_exclusion_count": len(tnved_scope_exclusions),
                      "ozon_brand_counts": dict(brands), "ozon_tnved_counts": dict(tnveds),
                      "matched_model_family_counts": dict(families)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
