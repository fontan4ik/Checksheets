"""Build a fresh exact Ozon plan for FERON declaration 53551/22."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from api_client import BASE, Client, digest, now, save
from audit_feron_01315_53551 import FERON, NUMBERS, read_rows, norm

PILOT = Path(__file__).resolve().parent
SOURCE = FERON / "00_Оригиналы_файлов" / "Декларация__53551_22_Светильники_стационарные,_тм_Feron,_серии_ML,_HL._Декларация_по_037_1__c6fe8119db.jpg"
UPLOAD = PILOT / "feron_53551_upload_files/decl_53551_22.pdf"
EXPECTED_SOURCE_SHA = "c6fe8119db0ca58bc4e604dc06b0db61a04e9a2c741122651558467d61917ad0"
EXPECTED_NUMBER = NUMBERS["53551"]
REGISTRY_EXPIRY = "2027-09-13"
SCAN_EXPIRY = "2027-09-14"
ISSUE_DATE = "2022-09-15"


def certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list response")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def main() -> None:
    if not SOURCE.is_file() or digest(SOURCE) != EXPECTED_SOURCE_SHA:
        raise RuntimeError("Original declaration scan is missing or changed")
    if not UPLOAD.is_file():
        raise RuntimeError("Prepared Ozon PDF is missing")
    preflight = json.loads((PILOT / "feron_01315_53551_live_preflight.json").read_text())
    if not preflight.get("wildberries", {}).get("complete_catalog_read") or not preflight.get("wildberries", {}).get("trash_complete"):
        raise RuntimeError("Fresh complete WB catalog/trash read is required")
    if preflight["wildberries"]["target_offers_missing"] != [
        "40511-1", "41200-1", "41201-1", "41455-1", "41456-1", "48442-1"
    ]:
        raise RuntimeError("WB missing-card set changed; rebuild plan")
    wb = preflight["wildberries"]["target_cards"]
    wb_verified = []
    for offer, cards in wb.items():
        if not cards:
            continue
        if len(cards) != 1:
            raise RuntimeError("Multiple WB cards for target offer " + offer)
        card = cards[0]
        docs = card["documents"]["53551"]
        if len(docs) != 1:
            raise RuntimeError("WB exact declaration row missing/duplicated for " + offer)
        row = docs[0]
        verdict = row.get("verdict") or {}
        if (row.get("type") != 2 or row.get("startDate", "")[:10] != ISSUE_DATE
                or row.get("endDate", "")[:10] != REGISTRY_EXPIRY
                or verdict.get("verified") is not True or verdict.get("status") != 1
                or card["overallVerdict"].get("isFullyChecked") is not True
                or card["overallVerdict"].get("status") != 1):
            raise RuntimeError("WB 53551 row is not finally verified for " + offer)
        wb_verified.append({"offer_id": offer, "nmID": card["nmID"], "document": row,
                            "overallVerdict": card["overallVerdict"]})
    if len(wb_verified) != 283:
        raise RuntimeError(f"Expected 283 verified WB cards, got {len(wb_verified)}")
    if preflight["wildberries"]["cards_in_trash"] != 0:
        raise RuntimeError("WB trash is nonempty; inspect all target offers before proceeding")

    groups = read_rows()
    rows = groups["53551"]
    if len(rows) != 289 or len({row["offer_id"] for row in rows}) != 289:
        raise RuntimeError("Workbook target set is no longer 289 unique offers")
    copies = []
    for row in rows:
        path = FERON / row["file_in_offer"]
        if not path.is_file() or digest(path) != EXPECTED_SOURCE_SHA:
            raise RuntimeError("Offer copy is missing/changed: " + str(path))
        copies.append({"path": str(path), "sha256": digest(path), "size": path.stat().st_size})
    if digest(UPLOAD) == EXPECTED_SOURCE_SHA:
        raise RuntimeError("Derived PDF unexpectedly has source JPEG hash")

    client = Client()
    offer_ids = [row["offer_id"] for row in rows]
    live: dict[str, dict] = {}
    for offset in range(0, len(offer_ids), 100):
        result = client.call("ozon", "/v3/product/info/list", {"offer_id": offer_ids[offset:offset + 100]})
        items = result.get("items") or result.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid live product info response")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live:
                raise RuntimeError("Duplicate/missing live offer identity")
            live[offer] = {"product_id": str(item.get("id", "")),
                           "sku": str(item.get("sku", "")),
                           "is_archived": item.get("is_archived")}
    targets = []
    for row in rows:
        offer = row["offer_id"]
        actual = live.get(offer)
        if not actual or actual["product_id"] != row["workbook_product_id"] or actual["sku"] != row["workbook_sku"]:
            raise RuntimeError("Workbook/live Ozon identity mismatch for " + offer)
        targets.append({"offer_id": offer, **actual})
    if len(live) != 289 or len({target["sku"] for target in targets}) != 289:
        raise RuntimeError("Ozon did not return exactly 289 unique target identities")

    records = certificates(client)
    norm_number = norm(EXPECTED_NUMBER)
    exact = [c for c in records if norm(c.get("certificate_number")) == norm_number]
    substring = [c for c in records if norm_number in norm(c.get("certificate_number"))]
    if exact or substring:
        raise RuntimeError("Ozon already has a matching certificate; reconcile instead of creating")

    summary = {
        "planned_at": now(), "number": EXPECTED_NUMBER, "document_type": "DECLARATION",
        "country": "RU", "accordance_type": "EAEU", "issue_date": ISSUE_DATE,
        "expire_date": REGISTRY_EXPIRY,
        "date_note": ("Original scan says validity through 2027-09-14 inclusive; FSA workbook snapshot dated "
                      "2026-09-23 and the already verified WB rows use 2027-09-13. Upload the registry/WB date "
                      "2027-09-13 and preserve the one-day discrepancy; direct FSA route timed out and official "
                      "Feron page returned 404 in this session."),
        "product_scope": "Stationary general-purpose Feron luminaires, series ML/HL; TR EAEU 037/2016.",
        "source_file": {"path": str(SOURCE), "sha256": digest(SOURCE), "size": SOURCE.stat().st_size},
        "upload_file": {"path": str(UPLOAD.resolve()), "sha256": digest(UPLOAD),
                        "size": UPLOAD.stat().st_size, "pages": 1},
        "source_workbook": {"path": str(FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx"),
                            "sha256": digest(FERON / "Сопоставление_артикулов_и_файлов_документов.xlsx")},
        "workbook_target_count": len(rows), "local_offer_copies": copies,
        "ozon_preflight": {"checked_at": preflight["checked_at"], "certificate_list_count": len(records),
                           "exact_matches": len(exact), "substring_matches": len(substring),
                           "target_identity_count": len(live), "identity_mismatch_count": 0,
                           "archived_target_count": sum(bool(x.get("is_archived")) for x in live.values())},
        "wb_snapshot": {"checked_at": preflight["wildberries"]["catalog_checked_at"],
                        "catalog_pages": preflight["wildberries"]["pages"],
                        "catalog_cards": preflight["wildberries"]["catalog_cards"],
                        "verified_rows_count": len(wb_verified),
                        "missing_target_offers": preflight["wildberries"]["target_offers_missing"],
                        "trash_complete": True, "cards_in_trash": 0},
        "wb_verified_rows": wb_verified, "targets": targets,
        "seed_offer": targets[0]["offer_id"], "seed_product_id": targets[0]["product_id"],
        "seed_sku": targets[0]["sku"],
    }
    save("feron_53551_ozon_plan.json", summary)
    print(json.dumps({"plan": str(PILOT / "feron_53551_ozon_plan.json"),
                      "target_count": len(targets), "seed_offer": targets[0]["offer_id"],
                      "Ozon_records": len(records), "WB_verified_cards": len(wb_verified),
                      "WB_missing": len(summary["wb_snapshot"]["missing_target_offers"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
