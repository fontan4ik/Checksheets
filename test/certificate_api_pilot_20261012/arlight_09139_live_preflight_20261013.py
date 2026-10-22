"""Read-only exact-scope reconciliation for Arlight certificate 09139/24."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "arlight_09139_live_preflight_20261013.json"
MATRIX = BASE / "brand_certificate_coverage_recheck_20261013_1200.json"
NUMBER = "ЕАЭС RU С-HK.АБ53.В.09139/24"
ISSUE = "2024-01-30"
WB_EXPIRY = "2028-01-29"
FSA_EXPIRY = "2029-01-29"
FSA_RECORD_ID = 3381287
TNVED = "8536508008"

sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from feron_53483_crossplatform_20261013 import norm, wb_tnved_codes  # noqa: E402


def main() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    matches = [x for x in matrix.get("documents", []) if norm(x.get("number")) == norm(NUMBER)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Ozon document group for {NUMBER}; got {len(matches)}")
    doc = matches[0]
    targets = doc.get("targets") or []
    if (len(targets) != 46 or doc.get("issue_date") != ISSUE or doc.get("expire_date") != FSA_EXPIRY
            or doc.get("certificate_ids") != ["5445194"]
            or doc.get("wb_status_counts") != {"date_conflict": 46}
            or any(x.get("wb_status") != "date_conflict" for x in targets)):
        raise RuntimeError("Saved exact-scope matrix no longer matches the FSA-date-conflict case")

    client = Client()
    offers = [str(x["offer_id"]) for x in targets]
    product_body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    product_items = product_body.get("items") or product_body.get("result", {}).get("items")
    if not isinstance(product_items, list) or len(product_items) != 46:
        raise RuntimeError("Ozon current product readback is incomplete")
    products = {}
    for row in product_items:
        offer = str(row.get("offer_id") or "")
        if not offer or offer in products:
            raise RuntimeError("Ozon returned a missing or duplicate offer")
        products[offer] = row
    attr_body = client.call("ozon", "/v4/product/info/attributes",
                            {"filter": {"offer_id": offers}, "limit": 100})
    attr_items = attr_body.get("result") or attr_body.get("items")
    if not isinstance(attr_items, list) or len(attr_items) != 46:
        raise RuntimeError("Ozon current product attributes are incomplete")
    attributes = {}
    for row in attr_items:
        offer = str(row.get("offer_id") or "")
        attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
        brand = [str(x.get("value") or "") for x in (attrs.get("85") or {}).get("values") or []]
        tnved = [str(x.get("value") or "") for x in (attrs.get("22232") or {}).get("values") or []]
        codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved if x.strip()})
        if not offer or offer in attributes:
            raise RuntimeError("Ozon attributes returned a missing or duplicate offer")
        attributes[offer] = {"brand_values": brand, "tnved_values": tnved, "tnved_codes": codes}

    ozon_results = []
    expected_by_offer = {str(x["offer_id"]): x for x in targets}
    for offer, target in expected_by_offer.items():
        row = products.get(offer) or {}
        attr = attributes.get(offer) or {}
        item = {"offer_id": offer, "expected_product_id": str(target["product_id"]),
                "product_id": str(row.get("id") or row.get("product_id") or ""),
                "expected_sku": str(target["sku"]), "sku": str(row.get("sku") or ""),
                "is_archived": bool(row.get("is_archived")), "name": row.get("name"),
                **attr}
        item["identity_exact"] = (item["product_id"] == item["expected_product_id"]
                                  and item["sku"] == item["expected_sku"] and not item["is_archived"])
        item["in_scope"] = (item.get("brand_values") == ["Arlight"]
                            and item.get("tnved_codes") == [TNVED])
        ozon_results.append(item)

    wb_results = []
    for target in targets:
        offer = str(target["offer_id"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            wb_results.append({"offer_id": offer, "card_count": len(cards), "identity_exact": False})
            continue
        card = cards[0]
        docs = card.get("documents") or card.get("docs") or {}
        items = docs.get("items") or []
        matches = [x for x in items if int(x.get("type") or 0) == 1 and norm(x.get("number")) == norm(NUMBER)]
        doc_chars = {}
        for char in card.get("characteristics") or []:
            if int(char.get("id", -1)) in {15001135, 15001136, 15001137, 15001138}:
                doc_chars.setdefault(str(char.get("id")), []).append(char)
        row = {"offer_id": offer, "expected_nmID": str(target["wb_nmID"]),
               "nmID": str(card.get("nmID") or ""), "vendorCode": str(card.get("vendorCode") or ""),
               "brand": card.get("brand"), "updatedAt": card.get("updatedAt"),
               "identity_exact": str(card.get("nmID") or "") == str(target["wb_nmID"])
                                 and str(card.get("vendorCode") or "") == offer,
               "tnved_codes": sorted(wb_tnved_codes(card)), "excludeDocuments": docs.get("excludeDocuments"),
               "target_document_rows": matches, "document_count": len(items),
               "document_characteristics": doc_chars, "card": card}
        row["document_date_matches_expected_current_stored_date"] = (
            len(matches) == 1 and str(matches[0].get("startDate") or "")[:10] == ISSUE
            and str(matches[0].get("endDate") or "")[:10] == WB_EXPIRY)
        row["safe_date_correction"] = (
            row["identity_exact"] and row["brand"] == "Arlight" and row["tnved_codes"] == [TNVED]
            and docs.get("excludeDocuments") is False and len(items) == 1 and len(matches) == 1
            and row["document_date_matches_expected_current_stored_date"]
            and len(doc_chars.get("15001138", [])) <= 1)
        wb_results.append(row)

    out = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
           "fsa_record_id": FSA_RECORD_ID,
           "fsa_official_record": {"url": f"https://pub.fsa.gov.ru/rss/certificate/view/{FSA_RECORD_ID}/product",
                                   "status": "Действует", "issue_date": ISSUE, "expiry_date": FSA_EXPIRY,
                                   "applicant": "ООО ТРАНЗИСТОР.РУ", "series": "Arlight SWT",
                                   "tnved_codes": [TNVED], "production_from": "2023-11"},
           "target_count": len(targets), "targets": targets,
           "ozon": {"products": ozon_results,
                    "all_identities_exact": len(ozon_results) == 46 and all(x.get("identity_exact") for x in ozon_results),
                    "all_in_scope": len(ozon_results) == 46 and all(x.get("in_scope") for x in ozon_results)},
           "wb": {"products": wb_results,
                  "all_identities_exact": len(wb_results) == 46 and all(x.get("identity_exact") for x in wb_results),
                  "all_in_scope": len(wb_results) == 46 and all(x.get("brand") == "Arlight"
                                                                  and x.get("tnved_codes") == [TNVED] for x in wb_results),
                  "all_dates_show_2028": len(wb_results) == 46 and all(x.get("document_date_matches_expected_current_stored_date") for x in wb_results),
                  "all_safe_to_update": len(wb_results) == 46 and all(x.get("safe_date_correction") for x in wb_results)}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": out["checked_at_utc"],
                      "ozon_all_identities_exact": out["ozon"]["all_identities_exact"],
                      "ozon_all_in_scope": out["ozon"]["all_in_scope"],
                      "wb_all_identities_exact": out["wb"]["all_identities_exact"],
                      "wb_all_in_scope": out["wb"]["all_in_scope"],
                      "wb_all_dates_show_2028": out["wb"]["all_dates_show_2028"],
                      "wb_all_safe_to_update": out["wb"]["all_safe_to_update"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
