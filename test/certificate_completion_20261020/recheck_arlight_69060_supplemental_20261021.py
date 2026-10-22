"""Freshly recheck the three supplemental 69060/25 product bindings."""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
CERTIFICATE_ID = 5624646
OFFERS = {"011750-1", "026058(1)-1", "029265(2)-1"}
CSV_PATH = HERE / "all_confirmed_source_assignments_live_20261021.csv"
BASE_OZON = HERE / "arlight_69060_crossplatform_preflight_live_20261021.json"
BASE_WB = HERE / "arlight_69060_wb_live_readback_20261021.json"
OUT = HERE / "arlight_69060_supplemental_live_readback_20261021.json"


def write(d: dict) -> None:
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT)


def main() -> None:
    base_ozon = json.loads(BASE_OZON.read_text())
    checked = dt.datetime.fromisoformat(base_ozon["checked_at_utc"].replace("Z", "+00:00"))
    age = (dt.datetime.now(dt.timezone.utc) - checked).total_seconds()
    if age < 0 or age > 1800 or base_ozon.get("complete") is not True:
        raise RuntimeError("Base Ozon preflight expired; refresh before continuing")
    base_wb = json.loads(BASE_WB.read_text())
    if base_wb.get("complete") is not True or base_wb.get("summary", {}).get("wb_exact_cards_with_valid_document") != 224:
        # `eligible_and_confirmed` additionally requires WB to expose TN VED.
        # Exact card identity + valid document rows are checked below separately.
        wbrows = base_wb.get("wildberries", {}).get("targets", [])
        if len(wbrows) != 549 or sum(bool(x.get("verdict_valid")) for x in wbrows) != 549:
            raise RuntimeError("Base WB exact-target readback incomplete")

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    source = {r["offer_id"]: r for r in rows if r.get("offer_id") in OFFERS and "69060" in r.get("number", "")}
    if set(source) != OFFERS:
        raise RuntimeError("Supplemental source crosswalk incomplete")
    if any(r.get("ozon_state") != "approved_link" or r.get("wb_state") != "valid" for r in source.values()):
        raise RuntimeError("One supplemental target was not confirmed by the latest complete inventory")

    client = Client()
    # Refresh the certificate metadata and complete binding list, including all 552 in-scope offers.
    cert_records = []
    page = 1
    while page <= 100:
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list incomplete")
        cert_records.extend(batch)
        if page >= int(body.get("page_count") or page):
            break
        page += 1
    certs = [c for c in cert_records if str(c.get("certificate_id")) == str(CERTIFICATE_ID)]
    if len(certs) != 1:
        raise RuntimeError("Ozon certificate identity missing or duplicated")
    cert = certs[0]
    if (runner.norm_number(cert.get("certificate_number")) != runner.norm_number(NUMBER)
            or cert.get("status_code") != "approved"
            or cert.get("type_code") != "declaration"
            or str(cert.get("issue_date", ""))[:10] != "2025-03-10"
            or str(cert.get("expire_date", ""))[:10] != "2030-03-09"):
        raise RuntimeError("Ozon certificate metadata conflict")
    bindings = client.ozon_bindings(CERTIFICATE_ID)
    binding_map = {str(x.get("product_id")): x for x in bindings}

    ozon_products = []
    for offer, row in source.items():
        product_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or []
        attrs_rows = client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": [offer]}, "limit": 1}).get("result") or []
        if len(product_rows) != 1 or len(attrs_rows) != 1:
            ozon_products.append({"offer_id": offer, "eligible": False, "reason": "product_or_attributes_missing_or_duplicate"})
            continue
        product, attrrow = product_rows[0], attrs_rows[0]
        attributes = {str(a.get("id")): a for a in attrrow.get("attributes") or []}
        brands = [str(v.get("value") or "").strip() for v in (attributes.get("85") or {}).get("values") or []]
        tnved = [str(v.get("value") or "").split(" - ", 1)[0].strip() for v in (attributes.get("22232") or {}).get("values") or []]
        binding = binding_map.get(str(row["ozon_product_id"]))
        problems = []
        if product.get("is_archived") is not False or str(product.get("product_id") or product.get("id")) != str(row["ozon_product_id"]) or str(product.get("sku")) != str(row["ozon_sku"]):
            problems.append("live_product_identity_changed")
        if len(brands) != 1 or brands[0].casefold().replace(" ", "") != "arlight":
            problems.append("brand_not_exact_arlight")
        if tnved != ["8504408300"]:
            problems.append("tnved_not_exactly_in_scope")
        if not binding or str(binding.get("sku")) != str(row["ozon_sku"]) or binding.get("product_status_code") != "approved":
            problems.append("certificate_binding_missing_or_not_approved")
        ozon_products.append({"offer_id": offer, "product_id": row["ozon_product_id"], "sku": row["ozon_sku"],
                              "brand_values": brands, "tnved_values": tnved,
                              "binding_status": binding.get("product_status_code") if binding else None,
                              "eligible": not problems, "problems": problems})

    wb_products = []
    expected_wb_type = runner.OZON_TO_WB_TYPE["declaration"]
    for offer, row in source.items():
        cards = client.wb_cards(offer)
        exact = [c for c in cards if str(c.get("vendorCode")) == offer and str(c.get("nmID")) == str(row["wb_nmID"])]
        problems = []
        card = exact[0] if len(cards) == 1 and len(exact) == 1 else {}
        if len(cards) != 1 or len(exact) != 1:
            problems.append("exact_wb_card_missing_duplicate_or_identity_changed")
        docs = ((card.get("documents") or {}).get("items") or []) if card else []
        exact_docs = [d for d in docs if runner.norm_number(d.get("number")) == runner.norm_number(NUMBER)]
        valid_docs = [d for d in exact_docs if d.get("type") == expected_wb_type
                      and str(d.get("startDate", ""))[:10] == "2025-03-10"
                      and str(d.get("endDate", ""))[:10] == "2030-03-09"
                      and (d.get("verdict") or {}).get("verified") is True
                      and (d.get("verdict") or {}).get("status") == 1
                      and (d.get("verdict") or {}).get("reason") == "valid"]
        if len(valid_docs) != 1:
            problems.append("exact_wb_document_or_valid_verdict_missing_or_conflicting")
        wb_products.append({"offer_id": offer, "wb_nmID": row["wb_nmID"],
                            "brand": card.get("brand") if card else None,
                            "exact_document_rows": valid_docs,
                            "valid": not problems, "problems": problems})

    result = {
        "checked_at_utc": now(), "read_only": True, "complete": True,
        "number": NUMBER, "certificate_id": CERTIFICATE_ID,
        "ozon_certificate_status": cert.get("status_code"),
        "ozon_total_bindings": len(bindings),
        "ozon_binding_status_counts": dict(Counter(str(x.get("product_status_code") or "unknown") for x in bindings)),
        "supplemental_target_count": len(OFFERS),
        "ozon_products": ozon_products, "wb_products": wb_products,
        "summary": {
            "ozon_supplemental_active_products_exact_scope_and_approved_binding": sum(x["eligible"] for x in ozon_products),
            "ozon_supplemental_targets": len(ozon_products),
            "wb_supplemental_exact_cards_with_valid_document": sum(x["valid"] for x in wb_products),
            "wb_supplemental_targets": len(wb_products),
            "problem_reasons": dict(Counter(p for r in ozon_products + wb_products for p in r.get("problems", []))),
        },
    }
    write(result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
