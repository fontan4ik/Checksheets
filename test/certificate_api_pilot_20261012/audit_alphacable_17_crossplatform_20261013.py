"""Fresh exact readback of all active AlphaCable catalog offers across Ozon and WB."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import Client, now
from execute_alphacable_02888_20261013 import CARD_FIELDS, wb_tnved_codes

BASE = Path(__file__).resolve().parent
OUT = BASE / "alphacable_17_crossplatform_readback_20261013.json"
CATALOG = BASE / "ozon_brand_tnved_inventory_recheck_20261013.json"
WB_SNAPSHOT = BASE / "wb_live_recheck_20261013_1500.json"

DOCS = {
    "ЕАЭС RU С-RU.АД38.В.00103/25": {
        "id": "5649888", "issue": "2025-05-21", "expiry": "2030-05-20",
        "offers": ["4237264-1", "7699117-1", "3137562-1", "4269981-1",
                   "7188787-1", "8966341-1", "1743162-1"],
    },
    "ЕАЭС RU С-RU.НА46.В.02888/22": {
        "id": "5524634", "issue": "2022-03-13", "expiry": "2027-03-12",
        "offers": ["8907600-1", "5928830-1", "6551655-1", "8971834-1",
                   "9075072-1", "5379943-1", "7253052-1"],
    },
    "ЕАЭС RU С-RU.НА46.В.02874/22": {
        "id": "5460768", "issue": "2022-03-13", "expiry": "2027-03-12",
        "offers": ["9569888-1", "8421448-1", "9969023-1"],
    },
}


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    snapshot = json.loads(WB_SNAPSHOT.read_text(encoding="utf-8"))
    if not catalog.get("complete") or not snapshot.get("complete"):
        raise RuntimeError("Complete Ozon and WB catalog snapshots are required")
    ozon_rows = {str(x["offer_id"]): x for x in catalog["products"]
                 if str(x.get("brand") or "").strip().casefold() == "альфакабель"}
    offers = sorted(offer for doc in DOCS.values() for offer in doc["offers"])
    if len(offers) != 17 or len(set(offers)) != 17 or set(offers) != set(ozon_rows):
        raise RuntimeError("Three document target sets do not cover the exact 17-row AlphaCable snapshot")
    wb_snapshot = {str(x.get("vendorCode") or ""): x for x in snapshot["cards"]}
    if len(wb_snapshot) != snapshot.get("unique_cards"):
        raise RuntimeError("WB complete snapshot is not unique by vendorCode")

    client = Client()
    product_body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    products = product_body.get("items") or product_body.get("result", {}).get("items")
    if not isinstance(products, list) or len(products) != len(offers):
        raise RuntimeError("Fresh Ozon product readback is incomplete")
    product_by_offer = {str(p.get("offer_id") or ""): p for p in products}
    if set(product_by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon offer identity set changed")

    attr_body = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)})
    attr_rows = attr_body.get("result") or attr_body.get("items")
    if not isinstance(attr_rows, list) or len(attr_rows) != len(offers):
        raise RuntimeError("Fresh Ozon attributes readback is incomplete")
    attr_by_offer = {str(x.get("offer_id") or ""): x for x in attr_rows}
    if set(attr_by_offer) != set(offers):
        raise RuntimeError("Fresh Ozon attribute identity set changed")

    result = {
        "checked_at_utc": now(), "read_only": True, "complete": False,
        "catalog_counts": {"ozon_active_alphacable": len(ozon_rows),
                           "wb_pages": snapshot.get("pages"),
                           "wb_unique_cards": snapshot.get("unique_cards"),
                           "wb_duplicate_nmids": snapshot.get("duplicate_nmids")},
        "documents": {}, "targets": [],
    }
    binding_by_document = {}
    for number, meta in DOCS.items():
        info_body = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": number})
        cert_info = info_body.get("result")
        if not isinstance(cert_info, dict) or str(cert_info.get("certificate_id")) != meta["id"]:
            raise RuntimeError("Ozon certificate identity changed for " + number)
        bindings = client.ozon_bindings(int(meta["id"]))
        expected_products = {str(ozon_rows[o]["product_id"]) for o in meta["offers"]}
        target_bindings = [b for b in bindings if str(b.get("product_id")) in expected_products]
        if len(target_bindings) != len(meta["offers"]):
            raise RuntimeError("Ozon target binding count changed for " + number)
        binding_by_document[number] = {str(b["product_id"]): b for b in target_bindings}
        result["documents"][number] = {
            "ozon_certificate_id": meta["id"],
            "ozon_status": cert_info.get("certificate_status", cert_info.get("status_code")),
            "ozon_issue_date": str(cert_info.get("issue_date") or "")[:10],
            "ozon_expiry_date": str(cert_info.get("expire_date") or "")[:10],
            "ozon_target_binding_count": len(target_bindings),
            "ozon_target_binding_status_counts": {},
        }
        result["documents"][number]["checks"] = {
            "ozon_document_approved": result["documents"][number]["ozon_status"] == "approved",
            "ozon_dates_match_fsa": result["documents"][number]["ozon_issue_date"] == meta["issue"]
                and result["documents"][number]["ozon_expiry_date"] == meta["expiry"],
            "exact_target_binding_count": len(target_bindings) == len(meta["offers"]),
        }
        statuses = result["documents"][number]["ozon_target_binding_status_counts"]
        for b in target_bindings:
            s = str(b.get("product_status_code") or "(missing)")
            statuses[s] = statuses.get(s, 0) + 1

    for number, meta in DOCS.items():
        for offer in meta["offers"]:
            expected = ozon_rows[offer]
            p = product_by_offer[offer]
            attrs = attr_by_offer[offer]
            values = {str(a.get("id")): a for a in attrs.get("attributes") or []}
            brands = [str(x.get("value") or "") for x in (values.get("85") or {}).get("values") or []]
            tnved_values = [str(x.get("value") or "") for x in (values.get("22232") or {}).get("values") or []]
            codes = sorted({x.split(" - ", 1)[0].strip() for x in tnved_values if x.strip()})
            pid = str(p.get("id") or p.get("product_id") or "")
            sku = str(p.get("sku") or "")
            binding = binding_by_document[number].get(pid)
            wb_matches = client.wb_cards(offer)
            if len(wb_matches) != 1:
                raise RuntimeError(f"WB exact card missing or ambiguous for {offer}")
            card = wb_matches[0]
            snap_card = wb_snapshot.get(offer)
            if snap_card is None or str(card.get("nmID")) != str(snap_card.get("nmID")):
                raise RuntimeError(f"WB exact nmID differs from latest complete snapshot for {offer}")
            docs = (card.get("documents") or {}).get("items") or []
            matches = [d for d in docs if str(d.get("number") or "") == number
                       and int(d.get("type") or 0) == 1
                       and str(d.get("startDate") or "")[:10] == meta["issue"]
                       and str(d.get("endDate") or "")[:10] == meta["expiry"]]
            if len(matches) != 1:
                raise RuntimeError(f"WB exact document row missing/duplicate for {offer}: {number}")
            wb_doc = matches[0]
            expected_nmid = str(snap_card.get("nmID"))
            target = {
                "offer_id": offer, "product_id": pid, "sku": sku,
                "expected_product_id": str(expected["product_id"]),
                "expected_sku": str(expected["sku"]),
                "ozon_active": not bool(p.get("is_archived")),
                "ozon_brand_values": brands, "ozon_tnved_codes": codes,
                "ozon_certificate_number": number,
                "ozon_binding_status": binding.get("product_status_code") if binding else None,
                "wb_nmID": str(card.get("nmID")), "wb_expected_nmID": expected_nmid,
                "wb_vendorCode": card.get("vendorCode"), "wb_brand": card.get("brand"),
                "wb_tnved_codes": sorted(wb_tnved_codes(card)),
                "wb_exclude_documents": (card.get("documents") or {}).get("excludeDocuments"),
                "wb_document_row": wb_doc,
                "checks": {
                    "ozon_identity_exact": pid == str(expected["product_id"]) and sku == str(expected["sku"]),
                    "ozon_brand_exact": brands == ["АЛЬФАКАБЕЛЬ"],
                    "ozon_tnved_in_scope": codes == ["8544499509"],
                    "ozon_binding_approved": bool(binding and binding.get("product_status_code") == "approved"),
                    "wb_identity_exact": str(card.get("vendorCode")) == offer and str(card.get("nmID")) == expected_nmid,
                    "wb_brand_exact": str(card.get("brand") or "").strip().casefold() == "альфакабель",
                    "wb_tnved_in_scope": wb_tnved_codes(card) == {"8544499509"},
                    "wb_documents_enabled": (card.get("documents") or {}).get("excludeDocuments") is False,
                    "wb_document_valid": (wb_doc.get("verdict") or {}).get("verified") is True
                        and (wb_doc.get("verdict") or {}).get("reason") == "valid"
                        and int((wb_doc.get("verdict") or {}).get("status") or 0) == 1,
                },
            }
            result["targets"].append(target)

    all_documents_approved = all(
        all(doc["checks"].values())
        and doc["ozon_target_binding_status_counts"] == {"approved": len(DOCS[number]["offers"])}
        for number, doc in result["documents"].items())
    result["all_17_complete_on_both_platforms"] = (
        len(result["targets"]) == 17
        and all_documents_approved
        and all(all(t["checks"].values()) for t in result["targets"]))
    result["complete"] = result["all_17_complete_on_both_platforms"]
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "complete": result["complete"], "targets": len(result["targets"]),
        "documents": result["documents"], "failed": [
            {"offer_id": t["offer_id"], "checks": [k for k, v in t["checks"].items() if not v]}
            for t in result["targets"] if not all(t["checks"].values())],
        "artifact": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
