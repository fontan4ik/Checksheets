"""Plan exact-number WB corrections only for products inside the FSA TNVED scope."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from api_client import digest

BASE = Path(__file__).resolve().parent
WORKBOOK_PLAN = BASE / "feron_01854_ozon_plan.json"
OZON_AUDIT = BASE / "feron_01854_ozon_reconciliation_20261012.json"
WB_AUDIT = BASE / "feron_01854_wb_fullcards_20261012.json"
OUT = BASE / "feron_01854_wb_plan.json"
NUMBER = "ЕАЭС RU С-CN.НА83.В.01854/22"
OLD_NUMBER = "ЕАЭС RU C-CN.HA83.B.01854/22"
ISSUE_DATE = "2022-04-11"
EXPIRY_DATE = "2027-04-10"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3074630/product"
FSA_CODES = {"9405190029", "9405190039", "9405190015"}
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def clean_document(item: dict) -> dict:
    unexpected = set(item) - set(DOC_FIELDS) - {"verdict", "createdAt", "updatedAt"}
    if unexpected:
        raise RuntimeError("Unexpected WB document fields: " + ", ".join(sorted(unexpected)))
    return {field: item[field] for field in DOC_FIELDS if field in item}


def card_tnved(card: dict) -> set[str]:
    rows = [x for x in card.get("characteristics") or [] if int(x.get("id", -1)) == 15000001]
    if len(rows) > 1:
        raise RuntimeError("Duplicate WB TNVED characteristic")
    values = rows[0].get("value") if rows else []
    return {str(x).strip().split(" ", 1)[0] for x in (values or []) if str(x).strip()}


def char_rows(card: dict) -> dict[int, tuple[str, str]]:
    return {int(row.get("id", -1)): (str(row.get("name", "")),
            json.dumps(row.get("value"), ensure_ascii=False, sort_keys=True))
            for row in card.get("characteristics") or []
            if int(row.get("id", -1)) in DOC_CHAR_IDS}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("WB plan already exists; inspect it before rebuilding")
    workbook_plan = json.loads(WORKBOOK_PLAN.read_text(encoding="utf-8"))
    ozon = json.loads(OZON_AUDIT.read_text(encoding="utf-8"))
    audit = json.loads(WB_AUDIT.read_text(encoding="utf-8"))
    targets = workbook_plan.get("targets") or []
    if (len(targets) != 188 or not audit.get("complete") or audit.get("target_count") != 188
            or audit.get("read_count") != 188 or audit.get("missing") or audit.get("duplicates")
            or audit.get("failures")):
        raise RuntimeError("Fresh exact WB full-card read is incomplete or ambiguous")
    if set(audit.get("cards_by_offer", {})) != {x["offer_id"] for x in targets}:
        raise RuntimeError("WB exact offer set differs from the workbook target set")
    ozon_codes = {str(row["offer_id"]): row.get("tnved_attribute_22232", [])
                  for row in ozon.get("tnved_attribute_rows", [])}
    if set(ozon_codes) != {x["offer_id"] for x in targets}:
        raise RuntimeError("Ozon TNVED attribute audit is incomplete")

    updates, excluded = [], []
    for target in targets:
        offer = target["offer_id"]
        card = audit["cards_by_offer"][offer]
        if card.get("vendorCode") != offer or not card.get("nmID"):
            raise RuntimeError("WB exact identity mismatch for " + offer)
        for field in CARD_FIELDS[:-1]:
            if field not in card:
                raise RuntimeError(f"Fresh WB card omitted {field} for {offer}")
        if not card.get("sizes") or (card.get("documents") or {}).get("excludeDocuments") is not False:
            raise RuntimeError("WB card is missing sizes or excludes documents: " + offer)

        wb_codes = card_tnved(card)
        ozon_codes_for_offer = {str(value).split(" ", 1)[0] for value in ozon_codes[offer] if str(value).strip()}
        outside_wb = sorted(wb_codes - FSA_CODES)
        outside_ozon = sorted(ozon_codes_for_offer - FSA_CODES)
        if outside_wb or outside_ozon or not ozon_codes_for_offer:
            excluded.append({"offer_id": offer, "nmID": str(card["nmID"]),
                             "reason": "tnved_outside_or_missing_from_fsa_scope",
                             "wb_tnved": sorted(wb_codes), "ozon_tnved": sorted(ozon_codes_for_offer)})
            continue

        docs = (card.get("documents") or {}).get("items") or []
        related = [index for index, doc in enumerate(docs)
                   if int(doc.get("type") or 0) == 1 and norm(doc.get("number", "")).endswith("0185422")]
        exact = [doc for doc in docs if int(doc.get("type") or 0) == 1
                 and norm(doc.get("number", "")) == norm(NUMBER)]
        if len(related) != 1 or exact or docs[related[0]].get("number") != OLD_NUMBER:
            raise RuntimeError("Expected exactly one old-number certificate row and no canonical duplicate for " + offer)
        old = docs[related[0]]
        if (str(old.get("startDate", ""))[:10] != ISSUE_DATE
                or str(old.get("endDate", ""))[:10] != EXPIRY_DATE
                or old.get("isEndless") is not False
                or (old.get("verdict") or {}).get("reason") != "document_not_found"
                or (old.get("verdict") or {}).get("verified") is not False):
            raise RuntimeError("WB certificate row or verdict changed for " + offer)

        new_docs = []
        for index, doc in enumerate(docs):
            clean = clean_document(doc)
            if index == related[0]:
                clean["number"] = NUMBER
            new_docs.append(clean)
        payload = {field: card[field] for field in CARD_FIELDS if field in card}
        payload["documents"] = {"items": new_docs, "excludeDocuments": False}
        for index, doc in enumerate(docs):
            expected = clean_document(doc)
            if index == related[0]:
                expected["number"] = NUMBER
            if new_docs[index] != expected:
                raise RuntimeError("Plan changes non-number document data for " + offer)
        updates.append({"offer_id": offer, "nmID": str(card["nmID"]),
                        "wb_tnved": sorted(wb_codes), "ozon_tnved": sorted(ozon_codes_for_offer),
                        "before": card, "payload": payload,
                        "document_characteristics_before": char_rows(card)})

    if len(updates) != 172 or len(excluded) != 16:
        raise RuntimeError(f"Unexpected in-scope/out-of-scope counts: {len(updates)} / {len(excluded)}")
    payloads = [item["payload"] for item in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payloads) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB update limit exceeded: {len(payloads)} cards, {len(encoded)} bytes")

    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "registry_url": FSA_URL,
        "fsa_record_id": 3074630,
        "number": NUMBER,
        "replaces_number": OLD_NUMBER,
        "document_type": 1,
        "issue_date": ISSUE_DATE,
        "expire_date": EXPIRY_DATE,
        "fsa_tnved_codes": sorted(FSA_CODES),
        "evidence": {
            "wb_fullcard_read": {"checked_at": audit.get("updated_at"), "cards_found": len(audit["cards_by_offer"])},
            "ozon_attribute_read": {"checked_at": ozon.get("checked_at_utc"), "products_read": len(ozon.get("tnved_attribute_rows", []))},
            "fsa_ui_status": "Действует",
            "fsa_valid_from": ISSUE_DATE,
            "fsa_valid_until": EXPIRY_DATE,
        },
        "counts": {"workbook_targets": 188, "wb_cards_to_update": len(updates),
                   "out_of_scope_or_conflicting_tnved": len(excluded),
                   "payload_bytes": len(encoded)},
        "excluded": excluded,
        "ozon_limitation": {
            "certificate_id": 5615253,
            "record_status": "declined",
            "rejection_reason_code": "not_found",
            "bound_skus": 1,
            "mass_bind_permitted": False,
        },
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "Ozon rejected the certificate, WB confirmation is pending, and 16 offers have TNVED data outside the FSA scope.",
        "updates": updates,
    }
    plan["payload_sha256"] = hashlib.sha256(encoded).hexdigest()
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"plan": str(OUT), "counts": plan["counts"],
                      "wb_tnved_counts": audit.get("tnved_counts_by_offer"),
                      "ozon_tnved_counts": ozon.get("tnved_attribute_counts"),
                      "excluded_offers": [x["offer_id"] for x in excluded],
                      "payload_sha256": plan["payload_sha256"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
