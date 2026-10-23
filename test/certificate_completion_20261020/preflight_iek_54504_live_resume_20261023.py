#!/usr/bin/env python3
"""Fresh read-only Ozon/WB preflight before resuming IEK 54504/26 targets."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(ROOT))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402
from run_all_found_certificates_20261014 import copy_documents  # noqa: E402

SOURCE = HERE / "iek_54504_preflight_adjudicated_20261021.json"
OUTPUT = HERE / "iek_54504_live_resume_preflight_20261023.json"
NUMBER = "RU Д-RU.РА08.В.54504/26"
ISSUE = "2026-09-18"
EXPIRY = "2031-09-17"
CERTIFICATE_ID = 5447909
ALLOWED_TNVED = {"9403700008"}


def attrs(row: dict, ident: str) -> list[str]:
    mapping = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (mapping.get(ident) or {}).get("values") or []]


def codes(values: list[str]) -> set[str]:
    return {str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()}


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    expected = {str(x["offer_id"]): x for x in source.get("ozon_targets", [])}
    if len(expected) != 76:
        raise RuntimeError("expected_76_targets")
    client = Client()
    certs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("certificate_list_incomplete")
        certs.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            break
    matches = [x for x in certs if norm_number(x.get("certificate_number")) == norm_number(NUMBER)
               and x.get("type_code") == "declaration"
               and x.get("accordance_type_code") == "EAEU"
               and str(x.get("issue_date") or "")[:10] == ISSUE
               and str(x.get("expire_date") or "")[:10] == EXPIRY]
    if (len(matches) != 1
            or str(matches[0].get("certificate_id")) != str(CERTIFICATE_ID)
            or matches[0].get("status_code") != "approved"):
        raise RuntimeError("current_ozon_record_not_unique_approved_exact")
    record = matches[0]
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    by_pid = {str(x.get("product_id") or ""): x for x in bindings}
    if len(by_pid) != len(bindings):
        raise RuntimeError("duplicate_binding_product_ids")

    offers = sorted(expected)
    products, attributes = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        ps = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        ats = client.call("ozon", "/v4/product/info/attributes",
                          {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(ps, list) or not isinstance(ats, list):
            raise RuntimeError("ozon_target_readback_incomplete")
        products.update({str(x.get("offer_id") or ""): x for x in ps})
        attributes.update({str(x.get("offer_id") or ""): x for x in ats})

    ozon = []
    for offer, target in expected.items():
        p = products.get(offer) or {}
        a = attributes.get(offer) or {}
        pid = str(p.get("product_id") or p.get("id") or "")
        sku = str(p.get("sku") or "")
        brand_values = attrs(a, "85")
        tnv_values = codes(attrs(a, "22232"))
        binding = by_pid.get(pid)
        ozon.append({"offer_id": offer, "product_id": pid, "sku": sku,
                     "product_identity_exact": (p.get("is_archived") is False
                        and pid == str(target["product_id"]) and sku == str(target["sku"])),
                     "brand_values": brand_values,
                     "brand_exact": (len(brand_values) == 1
                        and brand_values[0].casefold() == str(target.get("brand") or "IEK").casefold()),
                     "tnved_codes": sorted(tnv_values),
                     "tnved_in_scope": tnv_values == ALLOWED_TNVED,
                     "binding_exact": bool(binding and str(binding.get("sku") or "") == sku),
                     "binding_status": (binding or {}).get("product_status_code"),
                     "binding_product_id_conflict": bool(binding and str(binding.get("sku") or "") != sku)})

    wb = []
    for index, (offer, target) in enumerate(expected.items(), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb.append({"offer_id": offer, "card_count": len(cards), "exact_metadata": False,
                       "safe_for_update": False, "reason": "missing_or_duplicate_exact_card"})
            continue
        card = cards[0]
        card_codes = set()
        for char in card.get("characteristics") or []:
            label = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
            if "тнвэд" in label or "тнвед" in label:
                raw = char.get("value")
                vals = raw if isinstance(raw, list) else [raw]
                card_codes.update(str(v).split(" - ", 1)[0].strip() for v in vals if v)
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if str(d.get("type")) == "2"
                 and str(d.get("startDate") or "")[:10] == ISSUE
                 and str(d.get("endDate") or "")[:10] == EXPIRY
                 and d.get("isEndless") is False]
        card_brand = str(card.get("brand") or "")
        brand_alias_ok = card_brand.casefold() in {
            str(target.get("brand") or "IEK").casefold(), "iek", "generica"}
        code_ok = not card_codes or card_codes == ALLOWED_TNVED
        conflict = bool(same and len(exact) != 1)
        wb.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                   "brand": card_brand, "brand_in_scope": brand_alias_ok,
                   "tnved_codes": sorted(card_codes), "tnved_in_scope_or_blank": code_ok,
                   "exact_metadata": len(exact) == 1, "same_number_conflict": conflict,
                   "safe_for_update": brand_alias_ok and code_ok and not conflict,
                   "verdict": ((exact[0].get("verdict") or {}).get("reason")
                               or "pending_or_missing") if len(exact) == 1 else None})
        if index % 25 == 0:
            print(json.dumps({"phase": "wb_preflight", "checked": index, "total": 76}, ensure_ascii=False), flush=True)

    counts = {
        "targets": len(expected),
        "ozon_identity_exact": sum(x["product_identity_exact"] for x in ozon),
        "ozon_brand_exact": sum(x["brand_exact"] for x in ozon),
        "ozon_tnved_in_scope": sum(x["tnved_in_scope"] for x in ozon),
        "ozon_binding_exact": sum(x["binding_exact"] for x in ozon),
        "ozon_binding_status_counts": dict(collections.Counter(str(x.get("binding_status") or "missing") for x in ozon)),
        "ozon_missing_bindings": sum(not x["binding_exact"] for x in ozon),
        "ozon_declined_bindings": sum(x.get("binding_status") == "declined" for x in ozon),
        "ozon_product_conflicts": sum(x["binding_product_id_conflict"] for x in ozon),
        "wb_exact_cards": sum("card_count" not in x for x in wb),
        "wb_exact_metadata": sum(x.get("exact_metadata", False) for x in wb),
        "wb_safe_missing_metadata": sum(x.get("safe_for_update") and not x.get("exact_metadata") for x in wb),
        "wb_missing_cards": sum(x.get("reason") == "missing_or_duplicate_exact_card" for x in wb),
        "wb_scope_or_conflict_blocks": sum(not x.get("safe_for_update", False) and "reason" not in x for x in wb),
    }
    result = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
              "certificate_id": CERTIFICATE_ID, "source_number_record_number": record.get("certificate_number"),
              "record_status": record.get("status_code"), "record_issue_date": str(record.get("issue_date"))[:10],
              "record_expire_date": str(record.get("expire_date"))[:10], "existing_binding_count": len(bindings),
              "counts": counts, "ozon_targets": ozon, "wb_targets": wb}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("ozon_targets", "wb_targets")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
