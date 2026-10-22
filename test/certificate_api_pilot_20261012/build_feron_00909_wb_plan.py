"""Plan full-card corrections to WB using fresh target-card reads and FSA data."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from api_client import digest
from audit_feron_01315_53551 import norm
import build_feron_54301_ozon_plan as workbook_reader

BASE = Path(__file__).resolve().parent
NUMBER = "ЕАЭС N RU Д-CN.РА10.В.00909/23"
WORKBOOK_NUMBER = "ЕАЭС N RU Д-CN.PA010.В.00909/23"
ISSUE_DATE = "2023-11-23"
EXPIRY_DATE = "2028-11-22"
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")


def datepart(value) -> str:
    return str(value or "")[:10]


def clean_document(item: dict) -> dict:
    unexpected = set(item) - set(DOC_FIELDS) - {"verdict", "createdAt", "updatedAt"}
    if unexpected:
        raise RuntimeError("WB returned unexpected document fields: " + ", ".join(sorted(unexpected)))
    return {field: item[field] for field in DOC_FIELDS if field in item}


def main() -> None:
    workbook_reader.WORKBOOK_NUMBER_SUFFIX = "00909/23"
    rows = workbook_reader.read_target_rows()
    if len(rows) != 269 or len({x["offer_id"] for x in rows}) != 269:
        raise RuntimeError("Unexpected workbook target identity set")
    audit = json.loads((BASE / "feron_00909_wb_full_preflight.json").read_text(encoding="utf-8"))
    if (not audit.get("complete") or audit.get("target_count") != 269 or audit.get("read_count") != 269
            or audit.get("duplicate_offers") or audit.get("nmID_changes") or audit.get("failures")):
        raise RuntimeError("Fresh exact WB full-card read is incomplete or ambiguous")
    if audit.get("missing") != ["41185-1"] or len(audit.get("cards_by_offer", {})) != 268:
        raise RuntimeError("WB missing-card set changed; rebuild plan")
    recent_catalog = json.loads((BASE / "wb_live.json").read_text(encoding="utf-8"))
    if not recent_catalog.get("complete"):
        raise RuntimeError("Complete WB catalog read required")
    catalog_rows = {x.get("vendorCode"): x for x in recent_catalog.get("cards", [])}

    ozon_plan = json.loads((BASE / "feron_00909_ozon_plan.json").read_text(encoding="utf-8"))
    ozon_verification = json.loads((BASE / "feron_00909_ozon_verification.json").read_text(encoding="utf-8"))
    if (ozon_verification.get("certificate_id") != 5611254
            or ozon_verification.get("record_status") != "approved"
            or ozon_verification.get("binding_count") != 267
            or ozon_verification.get("missing_skus") or ozon_verification.get("outside_skus")
            or ozon_verification.get("duplicate_skus") or ozon_verification.get("product_id_mismatches")):
        raise RuntimeError("Exact Ozon declaration/binding evidence is incomplete")
    ozon_bindings = {x["offer_id"]: x for x in ozon_verification.get("bindings", [])}
    ozon_targets = {x["offer_id"]: x for x in ozon_plan["targets"]}

    updates, already_correct = [], []
    for row in rows:
        offer = row["offer_id"]
        card = audit["cards_by_offer"].get(offer)
        catalog_identity = catalog_rows.get(offer)
        if not card:
            continue
        if (card.get("vendorCode") != offer or not card.get("nmID")
                or not catalog_identity or str(catalog_identity.get("nmID")) != str(card.get("nmID"))):
            raise RuntimeError("WB exact vendorCode/nmID mismatch for " + offer)
        missing_fields = [f for f in CARD_FIELDS[:-1] if f not in card]
        if missing_fields:
            raise RuntimeError(f"Fresh WB full card omitted {missing_fields} for {offer}")
        if not card.get("sizes"):
            raise RuntimeError("Fresh WB card has no size row: " + offer)
        docs = ((card.get("documents") or {}).get("items") or [])
        if (card.get("documents") or {}).get("excludeDocuments") is not False:
            raise RuntimeError("WB documents are excluded for " + offer)
        related = [i for i, d in enumerate(docs) if int(d.get("type") or 0) == 2
                   and norm(d.get("number", "")) == norm(WORKBOOK_NUMBER)]
        canonical = [d for d in docs if int(d.get("type") or 0) == 2 and norm(d.get("number", "")) == norm(NUMBER)]
        if len(canonical) > 1 or (len(related) + len(canonical)) != 1:
            raise RuntimeError("Expected one exact existing/canonical declaration row for " + offer)
        if canonical:
            d = canonical[0]
            if datepart(d.get("startDate")) != ISSUE_DATE or datepart(d.get("endDate")) != EXPIRY_DATE:
                raise RuntimeError("Already canonical WB document has conflicting dates for " + offer)
            already_correct.append(offer)
            continue
        d = docs[related[0]]
        if (datepart(d.get("startDate")) != ISSUE_DATE or datepart(d.get("endDate")) != EXPIRY_DATE
                or d.get("isEndless") is not False):
            raise RuntimeError("Existing WB declaration dates/type conflict for " + offer)
        if not (d.get("verdict") or {}).get("reason") == "document_not_found":
            raise RuntimeError("WB rejection reason changed; stop for review: " + offer)

        new_docs = []
        for index, item in enumerate(docs):
            clean = clean_document(item)
            if index == related[0]:
                clean["number"] = NUMBER
            new_docs.append(clean)
        payload = {field: card[field] for field in CARD_FIELDS if field in card}
        payload["documents"] = {"items": new_docs, "excludeDocuments": False}
        before_docs = [clean_document(x) for x in docs]
        if len(before_docs) != len(new_docs):
            raise RuntimeError("WB document rows were dropped in planned update for " + offer)
        for index, before in enumerate(before_docs):
            expected = dict(before)
            if index == related[0]:
                expected["number"] = NUMBER
            if new_docs[index] != expected:
                raise RuntimeError("WB existing document fields changed in plan for " + offer)

        ozon_proof = ozon_bindings.get(offer)
        if offer in ozon_targets:
            target = ozon_targets[offer]
            if (not ozon_proof or str(ozon_proof["product_id"]) != target["product_id"]
                    or str(ozon_proof["sku"]) != target["sku"]):
                raise RuntimeError("Exact offer-to-Ozon-binding proof mismatches for " + offer)
        else:
            if not any(x["offer_id"] == offer for x in ozon_plan["archived_excluded_pending"]):
                raise RuntimeError("WB offer has no corresponding planned Ozon/archive identity: " + offer)

        updates.append({"offer_id": offer, "nmID": str(card["nmID"]),
                        "ozon_status": (ozon_proof or {}).get("status"),
                        "ozon_product_id": (ozon_proof or {}).get("product_id"),
                        "ozon_sku": (ozon_proof or {}).get("sku"),
                        "ozon_binding_missing_because_archived": offer in {x["offer_id"] for x in ozon_plan["archived_excluded_pending"]},
                        "before": card, "payload": payload})

    if len(updates) != 268 - len(already_correct) or len(updates) + len(already_correct) != 268:
        raise RuntimeError("WB full-card update target count changed")
    if len(already_correct) != 0:
        raise RuntimeError("WB already contains canonical rows; review before mutation")
    payloads = [x["payload"] for x in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payloads) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB update limit exceeded: {len(payloads)} cards, {len(encoded)} bytes")
    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(), "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/18390061/product",
        "number": NUMBER, "replaces_number": WORKBOOK_NUMBER, "document_type": 2,
        "issue_date": ISSUE_DATE, "expire_date": EXPIRY_DATE,
        "source_live_audit": {"checked_at": audit.get("checked_at"), "target_count": 269,
                              "cards_found": len(audit["cards_by_offer"]), "missing": audit["missing"]},
        "ozon_evidence": {"certificate_id": 5611254, "record_status": ozon_verification["record_status"],
                          "binding_statuses": ozon_verification["binding_statuses"],
                          "bindings_present": ozon_verification["binding_count"],
                          "all_bindings_approved": ozon_verification["all_bindings_approved"],
                          "archived_offers": [x["offer_id"] for x in ozon_plan["archived_excluded_pending"]]},
        "counts": {"workbook_targets": 269, "wb_cards_to_update": len(updates),
                   "wb_cards_missing": len(audit["missing"]), "already_canonical": len(already_correct),
                   "rejected_rows_to_correct": len(updates), "payload_bytes": len(encoded)},
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "WB document verification is pending, one WB card is missing, and two Ozon offers are archived.",
        "updates": updates,
    }
    out = BASE / "feron_00909_wb_plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"plan": str(out), "counts": plan["counts"],
                      "ozon_binding_statuses": plan["ozon_evidence"]["binding_statuses"],
                      "ozon_archived_offers": plan["ozon_evidence"]["archived_offers"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
