"""Read-only source, Ozon identity, and WB snapshot audit for Feron certificate 01324/22."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from api_client import Client, digest, now
from audit_feron_01315_53551 import FERON, norm
import build_feron_54301_ozon_plan as workbook_reader

BASE = Path(__file__).resolve().parent
OUT = BASE / "feron_01324_live_preflight.json"
SUFFIX = "01324/22"
NUMBER = "ЕАЭС RU С-CN.НВ85.В.01324/22"
REGISTRY_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3130797/product"
REGISTRY_STATUS = "Действует"
REGISTRY_ISSUE = "2022-08-17"
REGISTRY_EXPIRY = "2027-08-16"
SOURCE = FERON / "00_Оригиналы_файлов" / (
    "Сертификат__01324_Трансформаторы_(драйверы)_для_светодиодной_продукции,_тм_Feron,_"
    "серия_LB._Сертификат_по_004_и_020_1__11e4a243ee.pdf"
)


def read_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    ids: set[str] = set()
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list page")
        for cert in batch:
            key = str(cert.get("certificate_id"))
            if key in ids:
                raise RuntimeError("Duplicate Ozon certificate ID during pagination")
            ids.add(key)
        out.extend(batch)
        if len(batch) < 100:
            return out
    raise RuntimeError("Ozon certificate list pagination limit exceeded")


def main() -> None:
    workbook_reader.WORKBOOK_NUMBER_SUFFIX = SUFFIX
    rows = workbook_reader.read_target_rows()
    offers = sorted({x["offer_id"] for x in rows})
    if len(rows) != 103 or len(offers) != 103:
        raise RuntimeError(f"Expected 103 workbook offers; found {len(rows)}/{len(offers)}")
    if not SOURCE.is_file():
        raise RuntimeError("Original certificate PDF is missing")
    source_hash = digest(SOURCE)

    copies = []
    for row in rows:
        path = FERON / row["file_in_offer"]
        copies.append({"offer_id": row["offer_id"], "path": str(path),
                       "exists": path.is_file(), "sha256": digest(path) if path.is_file() else None,
                       "matches_original": path.is_file() and digest(path) == source_hash})

    client = Client()
    products: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[start:start + 100]})
        batch = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon product info response")
        for item in batch:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in products:
                raise RuntimeError("Duplicate or empty live Ozon offer identity")
            products[offer] = {"product_id": str(item.get("id", "")),
                               "sku": str(item.get("sku", "")),
                               "is_archived": bool(item.get("is_archived"))}

    identity_mismatches = []
    for row in rows:
        expected = {"product_id": row["workbook_product_id"], "sku": row["workbook_sku"]}
        live = products.get(row["offer_id"])
        if not live or any(live.get(k) != v for k, v in expected.items()):
            identity_mismatches.append({"offer_id": row["offer_id"], "expected": expected, "live": live})

    certificates = read_certificates(client)
    suffix = norm(SUFFIX)
    exact = [x for x in certificates if norm(x.get("certificate_number", "")) == norm(NUMBER)]
    same_suffix = [x for x in certificates if norm(x.get("certificate_number", "")).endswith(suffix)]

    prior_wb = json.loads((BASE / "wb_live.json").read_text(encoding="utf-8"))
    if not prior_wb.get("complete") or not isinstance(prior_wb.get("cards"), list):
        raise RuntimeError("Prior complete WB catalog snapshot is unavailable")
    wb_groups: dict[str, list[dict]] = {}
    for card in prior_wb["cards"]:
        offer = str(card.get("vendorCode", ""))
        if offer:
            wb_groups.setdefault(offer, []).append(card)
    wb_summary = {"snapshot_checked_at": prior_wb.get("checked_at"),
                  "snapshot_complete": prior_wb.get("complete"),
                  "target_cards_found": 0, "target_cards_missing": [], "duplicate_target_offers": [],
                  "matching_document_rows": 0, "matching_document_verdicts": {}, "rows": []}
    verdicts: dict[str, int] = {}
    for row in rows:
        candidates = wb_groups.get(row["offer_id"], [])
        if len(candidates) > 1:
            wb_summary["duplicate_target_offers"].append(row["offer_id"])
            wb_summary["rows"].append({"offer_id": row["offer_id"], "nmID": None, "documents": []})
            continue
        card = candidates[0] if candidates else None
        if not card:
            wb_summary["target_cards_missing"].append(row["offer_id"])
            wb_summary["rows"].append({"offer_id": row["offer_id"], "nmID": None, "documents": []})
            continue
        wb_summary["target_cards_found"] += 1
        matching = [d for d in ((card.get("documents") or {}).get("items") or [])
                    if norm(d.get("number", "")).endswith(suffix) and int(d.get("type") or 0) == 1]
        wb_summary["matching_document_rows"] += len(matching)
        for doc in matching:
            verdict = str((doc.get("verdict") or {}).get("reason", "pending"))
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
        wb_summary["rows"].append({"offer_id": row["offer_id"], "nmID": str(card.get("nmID")),
                                   "documents": [{k: d.get(k) for k in
                                                  ("id", "type", "number", "startDate", "endDate", "verdict")}
                                                 for d in matching]})
    wb_summary["matching_document_verdicts"] = verdicts

    report = {
        "checked_at": now(), "registry": {"url": REGISTRY_URL, "record_id": 3130797,
            "status": REGISTRY_STATUS, "number": NUMBER, "issue_date": REGISTRY_ISSUE,
            "expiry_date": REGISTRY_EXPIRY,
            "scope": "Electronic transformers/drivers for LED products; Feron series LB; TR TS 004/2011 and 020/2011"},
        "workbook_target_count": len(rows), "unique_offer_count": len(offers),
        "manual_flag_count": sum(x["manual_flag"].strip().lower() == "да" for x in rows),
        "source": {"path": str(SOURCE), "sha256": source_hash, "size": SOURCE.stat().st_size},
        "local_offer_copies_verified": sum(x["matches_original"] for x in copies),
        "local_offer_copies": copies,
        "ozon": {"product_count": len(products), "identity_mismatches": identity_mismatches,
                 "archived_offers": sorted(o for o, p in products.items() if p["is_archived"]),
                 "identities": [{"offer_id": r["offer_id"], **products.get(r["offer_id"], {})} for r in rows],
                 "certificate_list_count": len(certificates), "exact_matches": exact,
                 "same_suffix_records": same_suffix},
        "wb": wb_summary,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT), "offers": len(offers),
        "manual_flags": report["manual_flag_count"], "source_copies_verified": report["local_offer_copies_verified"],
        "ozon_identity_mismatches": len(identity_mismatches), "ozon_exact_matches": len(exact),
        "ozon_same_suffix_matches": len(same_suffix), "wb_found_in_prior_snapshot": wb_summary["target_cards_found"],
        "wb_missing_prior_snapshot": len(wb_summary["target_cards_missing"]),
        "wb_document_rows_in_prior_snapshot": wb_summary["matching_document_rows"],
        "wb_snapshot_at": prior_wb.get("checked_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
