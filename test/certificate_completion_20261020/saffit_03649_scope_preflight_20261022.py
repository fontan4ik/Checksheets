#!/usr/bin/env python3
"""Fresh scope and marketplace preflight for Saffit declaration 03649/23."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE / "saffit_03649_preflight_live_20261021.json"
SOURCE = ROOT / "output_to_user/certificates/group_2/SAFFIT/documents/FSA_extract_18059184_03649_23.pdf"
OUT = HERE / "saffit_03649_scope_preflight_v3_20261022.json"
SOURCE_SHA256 = "ded9250ca265af5cd86f2aba8baa66271e5f24cbc35ccdbd8203ee2c32c6a7c2"
NUMBER = "ЕАЭС N RU Д-CN.РА07.В.03649/23"
ISSUE = "2023-08-31"
EXPIRE = "2028-08-30"
TNVED = {"9405110033", "9405420032", "9405490036"}
EXPECTED = {
    "55232-1": {"product_id": "1558900265", "sku": "1990336973", "wb_nmID": "390667146", "model": "SSL10-30"},
    "55233-1": {"product_id": "1558900194", "sku": "1990604797", "wb_nmID": "390991811", "model": "SSL10-50"},
    "55234-1": {"product_id": "1558900211", "sku": "1990338594", "wb_nmID": "390586902", "model": "SSL10-100"},
    "55235-1": {"product_id": "1558900208", "sku": "1990608512", "wb_nmID": "390991831", "model": "SSL10-150"},
    "55236-1": {"product_id": "1558900117", "sku": "1990602682", "wb_nmID": "390667130", "model": "SSL10-200"},
}
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402


def product_attrs(row: dict) -> dict[str, list[str]]:
    return {str(x.get("id")): [str(v.get("value") or "").strip() for v in x.get("values") or []
                                 if str(v.get("value") or "").strip()]
            for x in row.get("attributes") or []}


def tnved_from_wb(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = item.get("value")
        values.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_first")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_pdf_missing_or_hash_mismatch")
    sys.path.insert(0, "/Users/vladimirgrebennikov/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages")
    from pypdf import PdfReader  # noqa: PLC0415
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(SOURCE)).pages)
    compact = re.sub(r"\s+", "", pdf_text).casefold()
    for required in (NUMBER, "31.08.2023", "30.08.2028", "9405490036", "SAFFIT", "SSL"):
        if re.sub(r"\s+", "", required).casefold() not in compact:
            raise RuntimeError("source_pdf_required_scope_text_missing:" + required)
    old = json.loads(OLD.read_text())
    if old.get("read_only") is not True or len(old.get("assigned_targets") or []) != 5:
        raise RuntimeError("prior_source_target_map_incomplete")
    client = Client()
    offers = sorted(EXPECTED)
    fresh_products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    fresh_attrs = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": offers}, "limit": len(offers)}).get("result") or []
    pmap = {str(x.get("offer_id")): x for x in fresh_products}
    amap = {str(x.get("offer_id")): x for x in fresh_attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("fresh_ozon_target_set_incomplete")
    records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        records.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_page_limit")
    matching = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matching) > 1:
        raise RuntimeError("duplicate_ozon_declaration_records")
    record = matching[0] if matching else None
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date", ""))[:10] != ISSUE
                   or str(record.get("expire_date", ""))[:10] != EXPIRE):
        raise RuntimeError("existing_ozon_document_metadata_conflict")
    bindings = client.ozon_bindings(record["certificate_id"]) if record else []
    binding_by_product = {str(x.get("product_id") or ""): x for x in bindings}
    if len(binding_by_product) != len(bindings):
        raise RuntimeError("duplicate_ozon_product_bindings")

    targets = []
    for offer in offers:
        expected = EXPECTED[offer]
        p = pmap[offer]
        attrs = product_attrs(amap[offer])
        brands = attrs.get("85", [])
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in attrs.get("22232", [])})
        name = str(p.get("name") or "")
        ozon_reasons = []
        if p.get("is_archived") is not False or str(p.get("product_id") or p.get("id")) != expected["product_id"] or str(p.get("sku")) != expected["sku"]:
            ozon_reasons.append("ozon_product_identity_conflict")
        if not brands or any("saffit" not in x.casefold() for x in brands) or expected["model"] not in name:
            ozon_reasons.append("ozon_brand_or_exact_series_model_conflict")
        if not tnved:
            ozon_reasons.append("ozon_tnved_missing")
        existing = binding_by_product.get(expected["product_id"])
        if existing and str(existing.get("sku")) != expected["sku"]:
            ozon_reasons.append("ozon_binding_identity_conflict")
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_card_count_conflict:" + offer)
        card = cards[0]
        wb_tnved = tnved_from_wb(card)
        wb_docs = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in wb_docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        wb_reasons = []
        description = str(card.get("description") or "")
        card_text = description + " " + str(card.get("title") or "")
        wattage = expected["model"].rsplit("-", 1)[-1]
        model_in_scope = (expected["model"].startswith("SSL10-") and expected["model"] in name
                          and re.search(r"(?<!\d)" + re.escape(wattage) + r"\s*W\b", card_text, re.I)
                          and "SSL" in pdf_text)
        if (str(card.get("vendorCode")) != offer or str(card.get("nmID")) != expected["wb_nmID"]
                or str(card.get("brand") or "").strip().casefold() != "saffit"
                or not model_in_scope):
            wb_reasons.append("wb_exact_identity_or_model_conflict")
        if wb_tnved and not (set(wb_tnved) <= TNVED) and not model_in_scope:
            wb_reasons.append("wb_tnved_out_of_document_scope")
        if same and any(int(x.get("type") or 0) != 2 or str(x.get("startDate", ""))[:10] != ISSUE
                        or str(x.get("endDate", ""))[:10] != EXPIRE for x in same):
            wb_reasons.append("wb_same_number_metadata_conflict")
        targets.append({
            "offer_id": offer, "product_id": expected["product_id"], "sku": expected["sku"],
            "wb_nmID": expected["wb_nmID"], "product_name": name, "wb_title": card.get("title"),
            "expected_model": expected["model"], "ozon_brand_values": brands, "ozon_tnved": tnved,
            "wb_tnved": wb_tnved, "ozon_tnved_differs_from_declaration": not set(tnved) <= TNVED,
            "wb_tnved_differs_from_declaration": bool(wb_tnved and not set(wb_tnved) <= TNVED),
            "ozon_existing_binding": existing,
            "ozon_eligible": not ozon_reasons,
            "ozon_conflicts": ozon_reasons,
            "wb_exact_document_count": len(same), "wb_eligible": not wb_reasons,
            "wb_conflicts": wb_reasons,
            "declaration_series_applies_to_exact_live_model": bool(model_in_scope),
            "wb_model_identity_crosswalk_uses_offer_nmID_and_wattage": expected["model"] not in card_text and bool(model_in_scope),
        })

    out = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/18059184/product",
        "source_pdf": str(SOURCE), "source_pdf_sha256": SOURCE_SHA256,
        "declaration_pdf_sha256": SOURCE_SHA256,
        "declaration_dates": [ISSUE, EXPIRE], "declaration_tnved": sorted(TNVED),
        "official_fsa_status_last_checked": old.get("fsa_status_last_checked_utc"),
        "official_fsa_status": old.get("official_fsa", {}).get("status"),
        "scope": {"brands": ["Feron", "SAFFIT"], "series": ["SP", "DH", "SSL", "SPL", "SAL"],
                  "target_series": "SSL", "all_five_models_match": all(x["declaration_series_applies_to_exact_live_model"] for x in targets)},
        "ozon_record_matches": [{k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")} ] if record else [],
        "ozon_existing_binding_count": len(bindings),
        "target_count": len(targets), "ozon_eligible_targets": sum(x["ozon_eligible"] for x in targets),
        "wb_eligible_targets": sum(x["wb_eligible"] for x in targets),
        "wb_declaration_valid": 0, "wb_certificate_valid": 0,
        "declaration_only_source_offers": [], "certificate_only_source_offers": [],
        "ozon_tnved_distribution": dict(collections.Counter(code for x in targets for code in x["ozon_tnved"])),
        "wb_tnved_distribution": dict(collections.Counter(code for x in targets for code in x["wb_tnved"])),
        "tnved_discrepancy_documented": True, "targets": targets, "local_source_files_deleted": False,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in ("checked_at_utc", "target_count", "ozon_eligible_targets",
        "wb_eligible_targets", "ozon_record_matches", "ozon_tnved_distribution", "wb_tnved_distribution")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
