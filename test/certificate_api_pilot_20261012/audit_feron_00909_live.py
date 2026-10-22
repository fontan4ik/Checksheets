"""Fresh read-only identity, source-copy, Ozon, and existing WB status audit for Feron 00909/23."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import Client, digest, now
import build_feron_54301_ozon_plan as workbook_reader
from audit_feron_01315_53551 import FERON, norm

BASE = Path(__file__).resolve().parent
SOURCE = FERON / "00_Оригиналы_файлов" / "Декларация__00909_Трековые_светильникиТМ_Feron,_серия_AL._Декларация_по_ТР_ТС_037__0f451f610d.jpg"
SOURCE_SHA256 = "0f451f610d71ff6bb93297c831169f3a9c131af58ac04c5fbf77a271ac918430"
OFFICIAL_NUMBER = "ЕАЭС N RU Д-CN.РА10.В.00909/23"
WORKBOOK_SUFFIX = "00909/23"


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list page")
        ids = [str(x.get("certificate_id")) for x in batch]
        if seen.intersection(ids):
            raise RuntimeError("Duplicate Ozon certificate IDs during pagination")
        seen.update(ids)
        out.extend(batch)
        if len(batch) < 100:
            return out
    raise RuntimeError("Ozon certificate list pagination limit exceeded")


def main() -> None:
    workbook_reader.WORKBOOK_NUMBER_SUFFIX = WORKBOOK_SUFFIX
    rows = workbook_reader.read_target_rows()
    offers = sorted({r["offer_id"] for r in rows})
    if len(rows) != 269 or len(offers) != 269:
        raise RuntimeError(f"Expected 269 unique Feron offers, found {len(rows)}/{len(offers)}")
    if not SOURCE.is_file() or digest(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("Original JPG missing or its name-derived hash does not match")

    copies = []
    for row in rows:
        path = FERON / row["file_in_offer"]
        copied = path.is_file()
        copies.append({"offer_id": row["offer_id"], "path": str(path), "exists": copied,
                       "sha256": digest(path) if copied else None,
                       "matches_original": copied and digest(path) == SOURCE_SHA256})

    client = Client()
    live_products: dict[str, dict] = {}
    for offset in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[offset:offset + 100]})
        batch = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon product info page")
        for item in batch:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live_products:
                raise RuntimeError("Duplicate or empty live Ozon offer identity")
            live_products[offer] = {"product_id": str(item.get("id", "")), "sku": str(item.get("sku", "")),
                                    "is_archived": bool(item.get("is_archived"))}

    identity_mismatches = []
    for row in rows:
        actual = live_products.get(row["offer_id"])
        expected = {"product_id": row["workbook_product_id"], "sku": row["workbook_sku"], "is_archived": False}
        if actual != expected:
            identity_mismatches.append({"offer_id": row["offer_id"], "expected": expected, "live": actual})

    records = list_certificates(client)
    suffix = norm(WORKBOOK_SUFFIX)
    matching_records = [r for r in records if norm(r.get("certificate_number", "")).endswith(suffix)]
    exact_records = [r for r in records if norm(r.get("certificate_number")) == norm(OFFICIAL_NUMBER)]
    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": OFFICIAL_NUMBER}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}

    wb = json.loads((BASE / "feron_full_wb_snapshot.json").read_text(encoding="utf-8"))
    if not wb.get("complete"):
        raise RuntimeError("Saved WB catalog audit is incomplete")
    cards = wb.get("cards_by_offer", {})
    wb_rows = []
    for row in rows:
        card = cards.get(row["offer_id"])
        docs = ((card.get("documents") or {}).get("items") or []) if card else []
        matching = [d for d in docs if norm(d.get("number", "")).endswith(suffix) and int(d.get("type") or 0) == 2]
        wb_rows.append({"offer_id": row["offer_id"], "nmID": str(card.get("nmID")) if card else None,
                        "card_count": 1 if card else 0,
                        "documents": [{k: d.get(k) for k in ("id", "type", "number", "startDate", "endDate", "verdict")} for d in matching]})

    out = {
        "checked_at": now(), "number_from_scan_and_workbook": "ЕАЭС N RU Д-CN.PA010.В.00909/23",
        "canonical_fsa_number": OFFICIAL_NUMBER,
        "number_discrepancy": "The original scan and Excel add an extra zero after PA; live FSA record 18390061 displays PA10 (without the extra zero). Use the live FSA number.",
        "registry_evidence": {"url": "https://pub.fsa.gov.ru/rds/declaration/view/18390061/product",
                              "record_id": 18390061, "status": "Действует",
                              "registration_date": "2023-11-23", "valid_until": "2028-11-22",
                              "scope": "General-purpose track luminaires; Feron series AL; TR EAEU 037/2016"},
        "source": {"path": str(SOURCE), "sha256": digest(SOURCE), "size": SOURCE.stat().st_size},
        "target_count": len(rows), "workbook_manual_flag_count": sum(r["manual_flag"].strip().lower() == "да" for r in rows),
        "local_offer_copies_verified": sum(x["matches_original"] for x in copies), "local_offer_copies": copies,
        "ozon_product_identities": {"live_count": len(live_products), "mismatches": identity_mismatches,
                                   "archived": sorted(k for k,v in live_products.items() if v["is_archived"]),
                                   "identities": [{"offer_id": r["offer_id"], "product_id": live_products.get(r["offer_id"], {}).get("product_id"),
                                                   "sku": live_products.get(r["offer_id"], {}).get("sku")} for r in rows]},
        "ozon": {"certificate_list_count": len(records), "exact_matches": exact_records,
                 "same_suffix_records": matching_records, "info_lookup_http_status": lookup.status_code,
                 "info_lookup_body": lookup_body},
        "wb": {"snapshot_checked_at": wb.get("checked_at"), "snapshot_complete": wb.get("complete"),
               "target_cards_found": sum(x["card_count"] == 1 for x in wb_rows),
               "target_cards_missing": sum(x["card_count"] == 0 for x in wb_rows),
               "targets_with_old_number_rows": sum(bool(x["documents"]) for x in wb_rows),
               "old_number_verdicts": dict(collections.Counter(str(d.get("verdict", {}).get("reason"))
                                                                  for x in wb_rows for d in x["documents"])),
               "rows": wb_rows},
    }
    out_path = BASE / "feron_00909_live_reconciliation.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out_path), "target_count": len(rows),
                      "source_copies_verified": out["local_offer_copies_verified"],
                      "ozon_identity_count": len(live_products), "ozon_identity_mismatches": len(identity_mismatches),
                      "ozon_existing_suffix_records": len(matching_records),
                      "official_info_lookup_http": lookup.status_code,
                      "wb_cards_found": out["wb"]["target_cards_found"], "wb_cards_missing": out["wb"]["target_cards_missing"],
                      "wb_old_doc_rows": out["wb"]["targets_with_old_number_rows"],
                      "wb_old_doc_verdicts": out["wb"]["old_number_verdicts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
