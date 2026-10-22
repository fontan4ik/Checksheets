"""Build a preserve-all-fields WB card update plan for Arlight declaration 69060/25."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
PREFLIGHT = BASE / "arlight_69060_preflight_20261012.json"
OZON = BASE / "arlight_69060_ozon_verification_20261012.json"
WB_FULL = BASE / "arlight_69060_wb_fullcards_before_20261012.json"
OUT = BASE / "arlight_69060_wb_plan_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
ISSUE_DATE = "2025-03-10"
EXPIRY_DATE = "2030-03-09"
FSA_CODES = {"8504408300"}
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def clean_doc(item: dict) -> dict:
    allowed_extras = {"verdict", "createdAt", "updatedAt"}
    unexpected = set(item) - set(DOC_FIELDS) - allowed_extras
    if unexpected:
        raise RuntimeError("Unknown WB document fields; stop before overwriting: " + ", ".join(sorted(unexpected)))
    return {key: item[key] for key in DOC_FIELDS if key in item}


def tnved_codes(card: dict) -> set[str]:
    rows = [x for x in card.get("characteristics") or [] if int(x.get("id", -1)) == 15000001]
    if len(rows) > 1:
        raise RuntimeError("Duplicate TN VED characteristic in WB card")
    values = rows[0].get("value") if rows else []
    return {str(x).strip().split(" ", 1)[0] for x in values or [] if str(x).strip()}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("WB plan already exists; inspect it before rebuilding")
    preflight = json.loads(PREFLIGHT.read_text())
    ozon = json.loads(OZON.read_text())
    wb = json.loads(WB_FULL.read_text())
    targets = preflight.get("targets") or []
    if (not preflight.get("ready_for_ozon_create_and_binding") or len(targets) != 549
            or not ozon.get("all_bindings_confirmed") or ozon.get("certificate_approved") is not True
            or ozon.get("target_offer_count") != 549 or ozon.get("covered_target_sku_count") != 549):
        raise RuntimeError("WB update requires complete exact-scope Ozon bindings first")
    if (not wb.get("complete") or wb.get("target_count") != 549 or wb.get("targets_found") != 549
            or wb.get("duplicate_nmids") != 0):
        raise RuntimeError("WB full-card read is incomplete or ambiguous")
    cards = wb.get("cards_by_offer") or {}
    if set(cards) != {x["offer_id"] for x in targets}:
        raise RuntimeError("Full WB exact offer set differs from the approved Ozon set")

    updates, already_present, excluded, conflicts = [], [], [], []
    wb_tnved_counts = Counter()
    for target in targets:
        offer = str(target["offer_id"])
        card = cards[offer]
        if card.get("vendorCode") != offer or str(card.get("nmID")) != str(target["wb_nmID"]):
            raise RuntimeError("WB card identity changed for " + offer)
        missing_fields = [field for field in CARD_FIELDS[:-1] if field not in card]
        if missing_fields:
            raise RuntimeError(f"WB full card omitted {missing_fields} for {offer}")
        docs_container = card.get("documents") or {}
        if docs_container.get("excludeDocuments") is not False:
            raise RuntimeError("WB card excludes compliance documents: " + offer)
        docs = docs_container.get("items") or []
        codes = tnved_codes(card)
        for code in codes:
            wb_tnved_counts[code] += 1
        ozon_codes = {str(x).split(" - ", 1)[0].strip()
                      for x in (target.get("ozon_attributes") or {}).get("tnved", []) if str(x).strip()}
        if "8504408300" not in ozon_codes or (codes and not codes.issubset(FSA_CODES)):
            excluded.append({"offer_id": offer, "nmID": str(card["nmID"]),
                             "reason": "Ozon_TNVED_outside_or_WB_TNVED_conflicts_with_FSA_scope",
                             "ozon_tnved_codes": sorted(ozon_codes), "wb_tnved_codes": sorted(codes)})
            continue
        existing_exact = [doc for doc in docs if normalize(doc.get("number")) == normalize(NUMBER)]
        if len(existing_exact) > 1:
            conflicts.append({"offer_id": offer, "nmID": str(card["nmID"]),
                              "reason": "duplicate_exact_document_rows", "rows": existing_exact})
            continue
        if existing_exact:
            doc = existing_exact[0]
            if (int(doc.get("type", -1)) != 2
                    or str(doc.get("startDate", ""))[:10] != ISSUE_DATE
                    or str(doc.get("endDate", ""))[:10] != EXPIRY_DATE
                    or doc.get("isEndless") is not False):
                conflicts.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                  "reason": "exact_number_date_or_type_conflict", "row": doc})
            else:
                already_present.append({"offer_id": offer, "nmID": str(card["nmID"]), "row": doc})
            continue
        cleaned_docs = [clean_doc(item) for item in docs]
        new_doc = {"type": 2, "number": NUMBER, "startDate": ISSUE_DATE + "T00:00:00Z",
                   "endDate": EXPIRY_DATE + "T00:00:00Z", "isEndless": False}
        new_docs = cleaned_docs + [new_doc]
        payload = {field: card[field] for field in CARD_FIELDS if field in card}
        payload["documents"] = {"items": new_docs, "excludeDocuments": False}
        if len(new_docs) != len(docs) + 1:
            raise RuntimeError("WB plan did not append exactly one declaration row for " + offer)
        for index, old_doc in enumerate(docs):
            if new_docs[index] != clean_doc(old_doc):
                raise RuntimeError("WB plan altered an existing document for " + offer)
        if any(payload.get(field) != card.get(field) for field in CARD_FIELDS):
            raise RuntimeError("WB full-card plan altered a non-document field for " + offer)
        updates.append({"offer_id": offer, "nmID": str(card["nmID"]),
                        "product_id": str(target["product_id"]), "sku": str(target["sku"]),
                        "ozon_tnved_codes": sorted(ozon_codes), "wb_tnved_codes": sorted(codes),
                        "wb_tnved_not_listed": not bool(codes), "before": card, "payload": payload})

    if conflicts:
        raise RuntimeError(f"WB exact document conflicts require reconciliation: {len(conflicts)}")
    payloads = [x["payload"] for x in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payloads) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB update limits exceeded: {len(payloads)} cards / {len(encoded)} bytes")
    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "number": NUMBER, "document_type": 2, "issue_date": ISSUE_DATE, "expire_date": EXPIRY_DATE,
        "fsa_registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product",
        "fsa_registry_status": "Действует", "fsa_tnved_codes": sorted(FSA_CODES),
        "ozon_certificate_id": ozon.get("certificate_id"),
        "evidence": {"ozon_readback": OZON.name, "wb_fullcard_read": WB_FULL.name,
                     "preflight": PREFLIGHT.name},
        "counts": {"source_targets": len(targets), "wb_cards_to_update": len(updates),
                   "already_present_exact": len(already_present), "excluded_scope": len(excluded),
                   "wb_tnved_not_listed": sum(bool(x["wb_tnved_not_listed"]) for x in updates),
                   "conflicts": len(conflicts), "payload_bytes": len(encoded)},
        "wb_tnved_counts": dict(wb_tnved_counts), "already_present": already_present,
        "excluded": excluded, "conflicts": conflicts, "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "WB is being sent for document verification; no local file may be removed until both marketplaces confirm every binding.",
        "updates": updates,
    }
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(json.dumps({"path": str(OUT), "counts": plan["counts"],
                      "wb_tnved_counts": plan["wb_tnved_counts"],
                      "already_present": len(already_present), "excluded": excluded,
                      "payload_sha256": plan["payload_sha256"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
