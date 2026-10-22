"""Build a preserve-all-fields WB plan for the verified Arlight declaration/certificate pair."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
PREFLIGHT = BASE / "arlight_41382_ozon_preflight_scoped_v2_20261012.json"
OZON_DECLARATION = BASE / "arlight_41382_ozon_verification_20261012.json"
OZON_CERTIFICATE = BASE / "arlight_00356_ozon_verification_20261012.json"
WB_BEFORE = BASE / "arlight_crosscert_wb_fullcards_prewrite_20261012.json"
FSA_CERT = BASE / "arlight_00356_fsa_official_ui_readback_20261012.json"
OUT = BASE / "arlight_crosscert_wb_plan_prewrite_20261012.json"
DECLARATION = {"number": "ЕАЭС N RU Д-RU.РА08.В.41382/26", "type": 2,
               "issue": "2026-09-16", "expiry": "2031-09-15"}
CERTIFICATE = {"number": "ЕАЭС RU С-RU.НК50.В.00356/26", "type": 1,
               "issue": "2026-09-16", "expiry": "2031-09-15"}
FSA_CODES = {"9405110039", "9405110013", "9405110033", "9405420039"}
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
    declaration_ozon = json.loads(OZON_DECLARATION.read_text())
    certificate_ozon = json.loads(OZON_CERTIFICATE.read_text())
    wb = json.loads(WB_BEFORE.read_text())
    fsa = json.loads(FSA_CERT.read_text())
    targets = [x for x in preflight.get("targets", []) if x.get("tnved_in_scope")]
    if (len(targets) != 339 or not declaration_ozon.get("all_bindings_confirmed")
            or declaration_ozon.get("certificate_approved") is not True
            or declaration_ozon.get("covered_target_sku_count") != 339
            or not certificate_ozon.get("all_bindings_confirmed")
            or certificate_ozon.get("certificate_approved") is not True
            or certificate_ozon.get("covered_target_sku_count") != 339):
        raise RuntimeError("WB update requires exact, approved Ozon records and all 339 target bindings")
    if (fsa.get("record_id") != 3729012 or fsa.get("canonical_number") != CERTIFICATE["number"]
            or fsa.get("status") != "Действует" or fsa.get("tnved_codes") is None
            or set(fsa["tnved_codes"]) != FSA_CODES):
        raise RuntimeError("Official FSA certificate evidence is missing or differs from the WB plan")
    if (not wb.get("complete") or wb.get("target_count") != 339 or wb.get("targets_found") != 339
            or wb.get("duplicate_nmids") != 0):
        raise RuntimeError("WB full-card read is incomplete or ambiguous")
    cards = wb.get("cards_by_offer") or {}
    expected_offers = {str(x["offer_id"]) for x in targets}
    if set(cards) != expected_offers:
        raise RuntimeError("Full WB exact offer set differs from the approved Ozon set")

    updates, already_present, excluded, conflicts = [], [], [], []
    wb_tnved_counts = Counter()
    declarations = (DECLARATION, CERTIFICATE)
    for target in targets:
        offer = str(target["offer_id"])
        card = cards[offer]
        if card.get("vendorCode") != offer or str(card.get("nmID")) != str(target["wb_nmID"]):
            raise RuntimeError("WB card identity changed for " + offer)
        if card.get("brand") != "Arlight":
            conflicts.append({"offer_id": offer, "reason": "WB_brand_differs_from_verified_Ozon_brand",
                              "wb_brand": card.get("brand")})
            continue
        missing_fields = [field for field in CARD_FIELDS[:-1] if field not in card]
        if missing_fields:
            raise RuntimeError(f"WB full card omitted {missing_fields} for {offer}")
        docs_container = card.get("documents") or {}
        docs = docs_container.get("items") or []
        codes = tnved_codes(card)
        for code in codes:
            wb_tnved_counts[code] += 1
        ozon_codes = {str(x).split(" - ", 1)[0].strip()
                      for x in (target.get("tnved_values") or []) if str(x).strip()}
        if not ozon_codes or not ozon_codes.issubset(FSA_CODES):
            raise RuntimeError("Preflight Ozon TN VED changed unexpectedly for " + offer)
        if codes and not codes.issubset(FSA_CODES):
            excluded.append({"offer_id": offer, "nmID": str(card["nmID"]),
                             "reason": "WB_TNVED_conflicts_with_official_FSA_codes",
                             "ozon_tnved_codes": sorted(ozon_codes), "wb_tnved_codes": sorted(codes)})
            continue

        clean_existing = [clean_doc(item) for item in docs]
        additions = []
        for spec in declarations:
            exact = [doc for doc in docs if normalize(doc.get("number")) == normalize(spec["number"])]
            if len(exact) > 1:
                conflicts.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                  "reason": "duplicate_exact_document_rows", "number": spec["number"]})
                continue
            if exact:
                doc = exact[0]
                if (int(doc.get("type", -1)) != spec["type"]
                        or str(doc.get("startDate", ""))[:10] != spec["issue"]
                        or str(doc.get("endDate", ""))[:10] != spec["expiry"]
                        or doc.get("isEndless") is not False):
                    conflicts.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                      "reason": "exact_number_date_or_type_conflict", "row": doc})
                continue
            additions.append({"type": spec["type"], "number": spec["number"],
                              "startDate": spec["issue"] + "T00:00:00Z",
                              "endDate": spec["expiry"] + "T00:00:00Z", "isEndless": False})

        if additions:
            old_numbers = {normalize(d.get("number")) for d in docs}
            if any(normalize(x["number"]) in old_numbers for x in additions):
                raise RuntimeError("WB plan would duplicate an existing document for " + offer)
            new_docs = clean_existing + additions
            payload = {field: card[field] for field in CARD_FIELDS if field in card}
            payload["documents"] = {"items": new_docs, "excludeDocuments": False}
            if len(new_docs) != len(docs) + len(additions):
                raise RuntimeError("WB plan did not append exactly the missing document rows for " + offer)
            if new_docs[:len(docs)] != clean_existing:
                raise RuntimeError("WB plan altered an existing document for " + offer)
            if any(payload.get(field) != card.get(field) for field in CARD_FIELDS):
                raise RuntimeError("WB full-card plan altered a non-document field for " + offer)
            updates.append({"offer_id": offer, "nmID": str(card["nmID"]),
                            "product_id": str(target["product_id"]), "sku": str(target["sku"]),
                            "ozon_tnved_codes": sorted(ozon_codes), "wb_tnved_codes": sorted(codes),
                            "wb_tnved_not_listed": not bool(codes),
                            "set_exclude_documents_false": docs_container.get("excludeDocuments") is not False,
                            "before": card,
                            "payload": payload, "added_documents": additions})
        else:
            already_present.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                    "documents": [x["number"] for x in declarations]})

    if conflicts:
        raise RuntimeError(f"WB exact identity/document conflicts require reconciliation: {len(conflicts)}")
    payloads = [x["payload"] for x in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payloads) > 1000 or len(encoded) > 10_000_000:
        raise RuntimeError(f"WB update limits exceeded: {len(payloads)} cards / {len(encoded)} bytes")
    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": [DECLARATION, CERTIFICATE], "fsa_tnved_codes": sorted(FSA_CODES),
        "ozon_declaration_id": declaration_ozon.get("certificate_id"),
        "ozon_certificate_id": certificate_ozon.get("certificate_id"),
        "evidence": {"ozon_declaration_readback": OZON_DECLARATION.name,
                     "ozon_certificate_readback": OZON_CERTIFICATE.name,
                     "wb_fullcard_read": WB_BEFORE.name, "fsa_official_ui": FSA_CERT.name,
                     "preflight": PREFLIGHT.name},
        "counts": {"source_targets": len(targets), "wb_cards_to_update": len(updates),
                   "already_present": len(already_present), "excluded_wb_tnved_conflict": len(excluded),
                   "cards_where_documents_will_be_enabled": sum(bool(x["set_exclude_documents_false"]) for x in updates),
                   "wb_tnved_not_listed": sum(bool(x["wb_tnved_not_listed"]) for x in updates),
                   "document_rows_to_add": sum(len(x["added_documents"]) for x in updates),
                   "conflicts": len(conflicts), "payload_bytes": len(encoded)},
        "wb_tnved_counts": dict(wb_tnved_counts), "already_present": already_present,
        "excluded": excluded, "conflicts": conflicts,
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "Retain local files until every needed exact document is confirmed on both marketplaces.",
        "updates": updates,
    }
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(json.dumps({"path": str(OUT), "counts": plan["counts"],
                      "wb_tnved_counts": plan["wb_tnved_counts"],
                      "excluded_sample": excluded[:5], "payload_sha256": plan["payload_sha256"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
