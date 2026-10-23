"""Fresh read-only live reconciliation for IEK/Generica declaration 27570/26."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import csv

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402

MANIFEST = HERE / "ready_found_documents_manifest_20261023.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = HERE / "iek_27570_81_targets_live_reconciliation_20261023.json"
NUMBER = "ЕАЭС N RU Д-RU.РА04.В.27570/26"
ISSUE = "2026-05-18"
EXPIRY = "2027-08-30"
FSA_ID = 21426775
SOURCE_SHA256 = "0922e8a7ed5712f9fc4deee7e7edac6726d1e931bd56f68c5c66cbc822815e0a"
ALLOWED_TNVED = {"9403700008"}
ALLOWED_BRANDS = {"IEK", "Generica"}


def read_certificates(client: Client) -> list[dict]:
    result = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list",
                           {"page": page, "page_size": 100}).get("result") or {}
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        result.extend(batch)
        if not batch or page >= int(data.get("page_count") or 0):
            return result
    raise RuntimeError("ozon_certificate_page_limit")


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def codes(values: list[str]) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def card_tnved(card: dict) -> list[str]:
    out = []
    for row in card.get("characteristics") or []:
        name = "".join(str(row.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = row.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                out.append(str(value).split(" - ", 1)[0].strip())
    return sorted(set(out))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    group = next(g for g in manifest["groups"] if norm_number(g["number"]) == norm_number(NUMBER))
    targets = group.get("targets") or []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        assignment_rows = list(csv.DictReader(stream))
    assignment_rows = [row for row in assignment_rows
                       if "27570/26" in str(row.get("Номер/название документа") or "")
                       and row.get("SHA256 фактический") == SOURCE_SHA256]
    target_map = {}
    for row in assignment_rows:
        offer = str(row.get("Артикул продавца") or "").strip()
        if not offer:
            raise RuntimeError("assignment_missing_offer")
        target_map[offer] = {"offer_id": offer, "brand_assignment": row.get("Бренд подтвержденный"),
                             "assignment_applicability": row.get("Применимость"),
                             "scope_evidence": row.get("Основание сопоставления"),
                             "expected_product_id": "", "expected_sku": ""}
    for target in targets:
        offer = str(target["offer_id"])
        value = target_map.setdefault(offer, {"offer_id": offer,
                                              "brand_assignment": target.get("brand"),
                                              "assignment_applicability": "expanded current-catalog target",
                                              "scope_evidence": target.get("scope_evidence"),
                                              "expected_product_id": "", "expected_sku": ""})
        value["expected_product_id"] = str(target.get("product_id") or "")
        value["expected_sku"] = str(target.get("sku") or "")
    offers = sorted(target_map)
    if len(offers) != 81:
        raise RuntimeError(f"union_target_count_changed:{len(offers)}")
    source = pathlib.Path(group["upload_file"]["path"])
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_hash_check_failed")

    client = Client()
    product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attr_rows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(product_rows, list) or not isinstance(attr_rows, list):
        raise RuntimeError("ozon_live_products_incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in product_rows}
    amap = {str(x.get("offer_id") or ""): x for x in attr_rows}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("ozon_live_offer_set_mismatch")

    matching = [x for x in read_certificates(client)
                if norm_number(x.get("certificate_number")) == norm_number(NUMBER)
                and x.get("type_code") == "declaration"]
    if not matching:
        raise RuntimeError("ozon_exact_record_not_found")
    records_with_bindings = []
    binding_map = {}
    for record in matching:
        bindings = client.ozon_bindings(record["certificate_id"])
        records_with_bindings.append({"record": record, "bindings": bindings})
        for binding in bindings:
            product_id = str(binding.get("product_id") or "")
            binding_map.setdefault(product_id, []).append({**binding,
                "certificate_id": record.get("certificate_id"),
                "certificate_status": record.get("status_code"),
                "certificate_type": record.get("type_code"),
                "certificate_issue_date": str(record.get("issue_date", ""))[:10],
                "certificate_expiry_date": str(record.get("expire_date", ""))[:10],
            })

    live_targets = []
    for offer in offers:
        target = target_map[offer]
        product = pmap[offer]
        attr = amap[offer]
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        brand_values = attr_values(attr, 85)
        tnved_values = attr_values(attr, 22232)
        tnved_codes = codes(tnved_values)
        bindings_for_product = binding_map.get(product_id, [])
        exact_approved = [binding for binding in bindings_for_product
                          if str(binding.get("sku") or "") == sku
                          and binding.get("product_status_code") == "approved"
                          and binding.get("certificate_status") == "approved"
                          and binding.get("certificate_type") == "declaration"
                          and binding.get("certificate_issue_date") == ISSUE
                          and binding.get("certificate_expiry_date") == EXPIRY]
        binding_ok = len(exact_approved) == 1

        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        card_results = []
        for card in cards:
            same = [d for d in copy_documents(card)
                    if norm_number(d.get("number")) == norm_number(NUMBER)]
            exact = (len(same) == 1 and int(same[0].get("type") or 0) == 2
                     and str(same[0].get("startDate", ""))[:10] == ISSUE
                     and str(same[0].get("endDate", ""))[:10] == EXPIRY)
            wb_codes = card_tnved(card)
            wb_brand = str(card.get("brand") or "").strip()
            card_results.append({"nmID": str(card.get("nmID") or ""), "brand": wb_brand,
                                 "tnved_codes": wb_codes, "same_number_rows": same,
                                 "exact_metadata_present": exact,
                                 "brand_matches": wb_brand.casefold() in {"iek", "generica"},
                                 "tnved_matches_fsa_or_blank": not wb_codes or set(wb_codes) <= ALLOWED_TNVED})
        expected_product_id = str(target.get("expected_product_id") or "")
        expected_sku = str(target.get("expected_sku") or "")
        live_targets.append({"offer_id": offer, "expected_product_id": expected_product_id,
                             "expected_sku": expected_sku, "brand_assignment": target.get("brand_assignment"),
                             "assignment_applicability": target.get("assignment_applicability"),
                             "scope_evidence": target.get("scope_evidence"),
                             "live_product_id": product_id, "live_sku": sku,
                             "live_name": product.get("name"), "archived": product.get("is_archived"),
                             "brand_values": brand_values, "tnved_values": tnved_values,
                             "tnved_codes": tnved_codes,
                             "ozon_identity_and_scope_match": (
                                 (not expected_product_id or product_id == expected_product_id)
                                 and (not expected_sku or sku == expected_sku)
                                 and product.get("is_archived") is False
                                 and len(brand_values) == 1 and brand_values[0] in ALLOWED_BRANDS
                                 and bool(tnved_codes and set(tnved_codes) <= ALLOWED_TNVED)),
                             "ozon_bindings": bindings_for_product,
                             "ozon_exact_approved_binding": binding_ok,
                             "wb_exact_card_count": len(cards), "wb_cards": card_results})

    checks = {
        "official_record_exact_and_approved": all(
            x.get("status_code") == "approved" and x.get("type_code") == "declaration"
            and str(x.get("issue_date", ""))[:10] == ISSUE
            and str(x.get("expire_date", ""))[:10] == EXPIRY for x in matching),
        "all_targets_exist_and_in_scope_on_ozon": all(x["ozon_identity_and_scope_match"] for x in live_targets),
        "all_targets_exact_approved_ozon_binding": all(x["ozon_exact_approved_binding"] for x in live_targets),
        "all_targets_one_exact_wb_card": all(x["wb_exact_card_count"] == 1 for x in live_targets),
        "all_wb_cards_have_exact_document_metadata": all(
            len(x["wb_cards"]) == 1 and x["wb_cards"][0]["exact_metadata_present"] for x in live_targets),
        "all_wb_cards_brand_and_tnved_safe": all(
            len(x["wb_cards"]) == 1 and x["wb_cards"][0]["brand_matches"] and
            x["wb_cards"][0]["tnved_matches_fsa_or_blank"] for x in live_targets),
    }
    result = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "official_fsa": {"record_id": FSA_ID, "status": "Действует", "issue_date": ISSUE,
                         "expiry_date": EXPIRY, "applicant": "ПАО ИЭК ХОЛДИНГ",
                         "product_scope": "IEK/Generica plastic cabinets and enclosures; serial production; TR TS 025/2012",
                         "tnved": sorted(ALLOWED_TNVED),
                         "url": f"https://pub.fsa.gov.ru/rds/declaration/view/{FSA_ID}/product"},
        "source_file": str(source), "source_file_sha256": SOURCE_SHA256,
        "ozon_records": records_with_bindings,
        "ozon_total_binding_count": sum(len(x["bindings"]) for x in records_with_bindings),
        "assignment_row_count": len(assignment_rows),
        "manifest_expanded_target_count": len(targets),
        "target_count": len(live_targets), "target_readbacks": live_targets,
        "conditions": checks, "all_linkages_confirmed": all(checks.values()),
        "wb_verdict_limitation": "WB card read endpoint confirms metadata but does not return the moderation verdict; recent edge snapshot reports these 22 as valid.",
        "local_file_deleted": False,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)
    print(json.dumps({"checked_at_utc": result["checked_at_utc"], "number": NUMBER,
                      "ozon_records": [{"id": x["record"].get("certificate_id"),
                                        "status": x["record"].get("status_code"),
                                        "product_count": x["record"].get("products_count"),
                                        "bindings": len(x["bindings"])} for x in records_with_bindings],
                      "total_bindings": result["ozon_total_binding_count"],
                      "target_count": len(live_targets), "conditions": checks,
                      "all_linkages_confirmed": result["all_linkages_confirmed"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
