"""Read-only live preflight for Arlight declaration 69060/25."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402
import run_all_found_certificates_20261014 as runner_module  # noqa: E402

MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
OUT = HERE / "arlight_69060_crossplatform_preflight_live_20261021.json"
NUMBER = "RU Д-НK.PА02.B.69060/25"
FSA = {
    "record_id": "19978046",
    "url": "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product",
    "checked_at_utc": now(),
    "status": "Действует",
    "issue_date": "2025-03-10",
    "expiry_date": "2030-03-09",
    "applicant": "ООО \"ТРАНЗИСТОР.РУ\"",
    "tnved": ["8504408300"],
    "product_scope": "Блоки питания серий ARPV, ARDV, HTS, ARV, ARS, JTS, HTPS, ARJ, ARPJ; аварийные блоки ARJ; шины KNX, DALI, SMART торговой марки INTELLIGENT ARLIGHT.",
    "manufacture_scope_note": "Распространяется на продукцию, изготовленную с даты изготовления отобранных образцов, указанной в акте отбора.",
}
MODEL_FAMILIES = ("ARPV", "ARDV", "HTS", "ARV", "ARS", "JTS", "HTPS", "ARJ", "ARPJ")


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save(data: dict) -> None:
    data["updated_at_utc"] = stamp()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def tnved_values(attrs: dict) -> list[str]:
    values = []
    for item in attrs.get("22232", {}).get("values", []) or []:
        raw = str(item.get("value") or "")
        values.append(raw.split(" - ", 1)[0].strip())
    return values


def brand_values(attrs: dict) -> list[str]:
    return [str(item.get("value") or "").strip()
            for item in attrs.get("85", {}).get("values", []) or []]


def exact_families(text: str) -> list[str]:
    return re.findall(r"(?<![A-Z0-9])(" + "|".join(MODEL_FAMILIES) + r")(?![A-Z0-9])",
                      str(text or "").upper())


def wb_cards(client: Client) -> list[dict]:
    cards: list[dict] = []
    cursor: dict = {"limit": 100}
    seen: set[tuple] = set()
    pages = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        batch = body.get("cards")
        returned = body.get("cursor") or {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("WB catalog page incomplete")
        pages += 1
        cards.extend(batch)
        if pages % 30 == 0:
            print(json.dumps({"phase": "wb_catalog", "pages": pages, "cards": len(cards)}, ensure_ascii=False), flush=True)
        if len(batch) < 100:
            break
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB cursor missing or repeated")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
        time.sleep(0.65)
    cards, duplicate_count = runner_module.deduplicate_equivalent_wb_rows(cards)
    print(json.dumps({"phase": "wb_catalog_complete", "pages": pages,
                      "cards": len(cards), "equivalent_duplicates_removed": duplicate_count}, ensure_ascii=False), flush=True)
    return cards


def main() -> None:
    doc = json.loads(MANIFEST.read_text())
    groups = [g for g in doc.get("groups", []) if g.get("number") == NUMBER]
    if len(groups) != 1:
        raise RuntimeError(f"Expected one manifest group, got {len(groups)}")
    group = groups[0]
    file = group.get("upload_file") or {}
    source_path = Path(file.get("path") or "")
    if not source_path.is_file() or digest(source_path) != file.get("sha256"):
        raise RuntimeError("Source PDF is absent or hash changed")
    if not (dt.date.fromisoformat(group["issue_date"]) <= dt.datetime.now(dt.timezone.utc).date()
            <= dt.date.fromisoformat(group["expire_date"])):
        raise RuntimeError("Document date range is not current")
    if group.get("allowed_tnved") != FSA["tnved"] or group.get("source_evidence_verified") is not True:
        raise RuntimeError("Manifest source scope is not verified")

    targets = group.get("targets") or []
    offers = [str(t["offer_id"]) for t in targets]
    if len(set(offers)) != len(offers):
        raise RuntimeError("Duplicate offer in manifest")
    family_checks = {str(t["offer_id"]): exact_families(t.get("name")) for t in targets}
    bad_family = [offer for offer, families in family_checks.items() if not families]

    client = Client()
    result: dict = {
        "checked_at_utc": stamp(), "read_only": True, "complete": False,
        "document_number": NUMBER, "fsa_registry": FSA,
        "source_pdf": {"path": str(source_path), "sha256": digest(source_path), "size": source_path.stat().st_size},
        "manifest_target_count": len(targets),
        "model_family_counts": dict(Counter(f for values in family_checks.values() for f in set(values))),
        "targets_without_declared_model_family": bad_family,
        "ozon": {"complete": False, "targets": []},
        "wildberries": {"complete": False, "targets": []},
        "errors": [],
    }
    save(result)

    # Exact current Ozon product identities and regulatory attributes.
    products_by_offer: dict[str, list[dict]] = {}
    attrs_by_offer: dict[str, list[dict]] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        for row in body.get("items") or []:
            products_by_offer.setdefault(str(row.get("offer_id") or ""), []).append(row)
        attr_body = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": 100,
        })
        for row in attr_body.get("result") or []:
            attrs_by_offer.setdefault(str(row.get("offer_id") or ""), []).append(row)
        print(json.dumps({"phase": "ozon_target_preflight", "offers_checked": min(start + 100, len(offers)),
                          "total": len(offers)}, ensure_ascii=False), flush=True)

    ozon_rows = []
    for target in targets:
        offer = str(target["offer_id"])
        products = products_by_offer.get(offer, [])
        attrrows = attrs_by_offer.get(offer, [])
        problems = []
        product = products[0] if len(products) == 1 else {}
        attrrow = attrrows[0] if len(attrrows) == 1 else {}
        attrs = {str(a.get("id")): a for a in attrrow.get("attributes") or []}
        if len(products) != 1:
            problems.append("product_missing_or_duplicate")
        elif (product.get("is_archived") is not False or
              str(product.get("product_id") or product.get("id") or "") != str(target["product_id"]) or
              str(product.get("sku") or "") != str(target["sku"])):
            problems.append("product_identity_or_active_state_changed")
        if len(attrrows) != 1:
            problems.append("attributes_missing_or_duplicate")
        else:
            if str(attrrow.get("id") or attrrow.get("product_id") or "") != str(target["product_id"]):
                problems.append("attribute_product_id_changed")
            if len(brand_values(attrs)) != 1 or brand_values(attrs)[0].casefold().replace(" ", "") != "arlight":
                problems.append("brand_not_exact_arlight")
            if tnved_values(attrs) != FSA["tnved"]:
                problems.append("tnved_missing_or_out_of_scope")
        ozon_rows.append({
            "offer_id": offer, "product_id": str(target["product_id"]), "sku": str(target["sku"]),
            "manifest_name": target.get("name"), "live_name": product.get("name"),
            "brand_values": brand_values(attrs), "tnved_values": tnved_values(attrs),
            "identity_active_match": not any(p.startswith(("product_missing", "product_identity")) for p in problems),
            "eligible": not problems, "problems": problems,
        })
    result["ozon"].update({"complete": True, "checked_at_utc": stamp(), "targets": ozon_rows,
                           "eligible": sum(x["eligible"] for x in ozon_rows),
                           "problem_count": sum(not x["eligible"] for x in ozon_rows),
                           "problem_reasons": dict(Counter(p for x in ozon_rows for p in x["problems"]))})
    save(result)

    # Current exact Ozon document record and binding state.
    metadata = []
    page = 1
    while page <= 100:
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list incomplete")
        metadata.extend(batch)
        if page >= int(body.get("page_count") or page):
            break
        page += 1
    exact_records = [c for c in metadata if runner_module.norm_number(c.get("certificate_number")) == runner_module.norm_number(NUMBER)]
    result["ozon"]["exact_document_records"] = [{k: c.get(k) for k in (
        "certificate_id", "certificate_number", "type_code", "accordance_type_code", "issue_date", "expire_date", "status_code")}
        for c in exact_records]
    if len(exact_records) == 1:
        record = exact_records[0]
        bindings = client.ozon_bindings(record["certificate_id"])
        result["ozon"]["exact_document_binding_count"] = len(bindings)
        binding_map = {str(b.get("product_id")): b for b in bindings}
        result["ozon"]["target_binding_status_counts"] = dict(Counter(
            str(binding_map.get(str(t["product_id"]), {}).get("product_status_code") or "missing") for t in targets))
        result["ozon"]["target_missing_binding_count"] = sum(str(t["product_id"]) not in binding_map for t in targets)
    elif len(exact_records) > 1:
        result["ozon"]["exact_document_conflict"] = "duplicate_exact_records"
    else:
        result["ozon"]["exact_document_record_absent"] = True
    save(result)

    # Read the complete WB catalog once, then match exact offer and nmID.
    cards = wb_cards(client)
    by_offer: dict[str, list[dict]] = {}
    for card in cards:
        by_offer.setdefault(str(card.get("vendorCode") or ""), []).append(card)
    wb_rows = []
    desired = {"type": runner_module.OZON_TO_WB_TYPE["declaration"], "number": NUMBER, "startDate": "2025-03-10T00:00:00Z",
               "endDate": "2030-03-09T00:00:00Z", "isEndless": False}
    for target in targets:
        offer = str(target["offer_id"])
        matches = by_offer.get(offer, [])
        exact = [c for c in matches if str(c.get("nmID")) == str(target.get("wb_nmID"))]
        problems = []
        if len(matches) != 1 or len(exact) != 1:
            problems.append("wb_card_missing_duplicate_or_identity_changed")
            card = exact[0] if len(exact) == 1 else {}
        else:
            card = exact[0]
        if card:
            scope_error = runner_module.wb_scope_error(card, group, target)
            if scope_error:
                problems.append(scope_error)
            docs = ((card.get("documents") or {}).get("items") or [])
            same_num = [x for x in docs if runner_module.norm_number(x.get("number")) == runner_module.norm_number(NUMBER)]
            if same_num:
                if any(runner_module.doc_key(x) != runner_module.doc_key(desired) or
                       (str(x.get("startDate", ""))[:10], str(x.get("endDate", ""))[:10]) !=
                       (desired["startDate"][:10], desired["endDate"][:10]) for x in same_num):
                    problems.append("wb_same_number_type_or_date_conflict")
                else:
                    present = True
            else:
                present = False
        else:
            present = False
        wb_rows.append({
            "offer_id": offer, "wb_nmID": target.get("wb_nmID"),
            "brand": card.get("brand") if card else None,
            "tnved_values": [str(c.get("value")) for c in (card.get("characteristics") or [])
                             if "тнвэд" in "".join(str(c.get("name") or "").casefold().split())
                             or "тнвед" in "".join(str(c.get("name") or "").casefold().split())] if card else [],
            "exact_document_present": present,
            "eligible": bool(card) and not problems,
            "problems": problems,
        })
    result["wildberries"].update({"complete": True, "checked_at_utc": stamp(), "catalog_cards": len(cards),
                                  "targets": wb_rows,
                                  "exact_cards": sum(bool(x["eligible"]) for x in wb_rows),
                                  "document_already_present": sum(x["exact_document_present"] for x in wb_rows),
                                  "missing_documents_to_add": sum(x["eligible"] and not x["exact_document_present"] for x in wb_rows),
                                  "problem_count": sum(not x["eligible"] for x in wb_rows),
                                  "problem_reasons": dict(Counter(p for x in wb_rows for p in x["problems"]))})
    result["complete"] = True
    result["summary"] = {
        "ozon_eligible_targets": result["ozon"]["eligible"],
        "ozon_total_targets": len(targets),
        "ozon_exact_record_count": len(exact_records),
        "ozon_target_binding_states": result["ozon"].get("target_binding_status_counts", {}),
        "wb_exact_eligible_cards": result["wildberries"]["exact_cards"],
        "wb_total_targets": len(targets),
        "wb_documents_already_present": result["wildberries"]["document_already_present"],
        "wb_documents_missing_but_eligible": result["wildberries"]["missing_documents_to_add"],
        "wb_problem_reasons": result["wildberries"]["problem_reasons"],
        "source_model_family_unmatched": len(bad_family),
        "source_assignment_excluded_tnved_count": 1,
    }
    save(result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
