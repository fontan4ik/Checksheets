"""Prepare preserve-all-fields WB updates for the three supplemental Arlight offers."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

PRECHECK = BASE / "arlight_69060_extras_preflight_20261012.json"
OZON = BASE / "arlight_69060_aggregate_verification_20261012.json"
OUT = BASE / "arlight_69060_wb_extras_plan_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
ISSUE_DATE = "2025-03-10"
EXPIRY_DATE = "2030-03-09"
TARGETS = {
    "011750-1": {"product_id": "4021378835", "sku": "3851174714", "nmID": "946113633"},
    "026058(1)-1": {"product_id": "5140430749", "sku": "4773472600", "nmID": "1178002281"},
    "029265(2)-1": {"product_id": "4021379031", "sku": "3851174775", "nmID": "946113547"},
}
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def clean_doc(item: dict) -> dict:
    unexpected = set(item) - set(DOC_FIELDS) - {"verdict", "createdAt", "updatedAt"}
    if unexpected:
        raise RuntimeError("Unknown WB document fields: " + ", ".join(sorted(unexpected)))
    return {key: item[key] for key in DOC_FIELDS if key in item}


def tnved_codes(card: dict) -> set[str]:
    rows = [x for x in card.get("characteristics") or [] if int(x.get("id", -1)) == 15000001]
    if len(rows) > 1:
        raise RuntimeError("Duplicate WB TN VED characteristic")
    values = rows[0].get("value") if rows else []
    return {str(x).strip().split(" ", 1)[0] for x in values or [] if str(x).strip()}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Supplemental WB plan already exists; inspect it before rebuilding")
    pre = json.loads(PRECHECK.read_text())
    ozon = json.loads(OZON.read_text())
    if (not pre.get("ready_to_bind_three") or not ozon.get("all_bindings_confirmed")
            or ozon.get("target_sku_count") != 552 or ozon.get("certificate_approved") is not True
            or ozon.get("certificate_id") != 5624646):
        raise RuntimeError("Exact Ozon declaration bindings are not confirmed for all 552 products")

    client = Client()
    updates = []
    for offer, target in TARGETS.items():
        matches = client.wb_cards(offer)
        if len(matches) != 1:
            raise RuntimeError(f"WB exact card lookup is not unique: {offer}")
        card = matches[0]
        if card.get("vendorCode") != offer or str(card.get("nmID")) != target["nmID"]:
            raise RuntimeError(f"WB card identity mismatch: {offer}")
        if card.get("brand") != "Arlight":
            raise RuntimeError(f"WB live brand changed for {offer}")
        if card.get("documents", {}).get("excludeDocuments") is not False:
            raise RuntimeError(f"WB excludes compliance documents for {offer}")
        codes = tnved_codes(card)
        if codes and not codes.issubset({"8504408300"}):
            raise RuntimeError(f"WB TN VED conflicts with the active FSA declaration for {offer}: {sorted(codes)}")
        docs = (card.get("documents") or {}).get("items") or []
        if any(norm(d.get("number")) == norm(NUMBER) for d in docs):
            raise RuntimeError(f"WB declaration already appears for {offer}; reconcile before writing")
        missing = [field for field in CARD_FIELDS[:-1] if field not in card]
        if missing:
            raise RuntimeError(f"WB full card omitted {missing} for {offer}")
        cleaned_docs = [clean_doc(d) for d in docs]
        new_doc = {"type": 2, "number": NUMBER, "startDate": ISSUE_DATE + "T00:00:00Z",
                   "endDate": EXPIRY_DATE + "T00:00:00Z", "isEndless": False}
        payload = {field: card[field] for field in CARD_FIELDS if field in card}
        payload["documents"] = {"items": cleaned_docs + [new_doc], "excludeDocuments": False}
        if any(payload.get(field) != card.get(field) for field in CARD_FIELDS):
            raise RuntimeError(f"WB payload changes a non-document field: {offer}")
        updates.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                        "nmID": target["nmID"], "wb_tnved_codes": sorted(codes), "before": card,
                        "payload": payload})

    payloads = [x["payload"] for x in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    plan = {"created_at": datetime.now(timezone.utc).isoformat(), "number": NUMBER,
            "document_type": 2, "issue_date": ISSUE_DATE, "expire_date": EXPIRY_DATE,
            "ozon_certificate_id": 5624646, "ozon_target_pairs_confirmed": 552,
            "fsa_registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product",
            "fullcard_count": len(updates), "payload_bytes": len(encoded),
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
            "preserves_existing_documents": True, "preserves_all_non_document_fields": True,
            "local_cleanup_allowed": False, "updates": updates}
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(json.dumps({k: plan[k] for k in (
        "number", "document_type", "fullcard_count", "payload_bytes", "payload_sha256",
        "preserves_existing_documents", "preserves_all_non_document_fields", "local_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
