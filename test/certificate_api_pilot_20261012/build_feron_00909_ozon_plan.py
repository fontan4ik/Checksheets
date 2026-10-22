"""Build a fresh, exact Ozon plan for FSA declaration 00909/23."""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

from api_client import Client, digest, now
from audit_feron_01315_53551 import FERON, norm
import build_feron_54301_ozon_plan as workbook_reader

BASE = Path(__file__).resolve().parent
SOURCE = FERON / "00_Оригиналы_файлов" / "Декларация__00909_Трековые_светильникиТМ_Feron,_серия_AL._Декларация_по_ТР_ТС_037__0f451f610d.jpg"
UPLOAD = BASE / "feron_00909_upload_files" / "decl_00909_23.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА10.В.00909/23"
SUFFIX = "00909/23"
SOURCE_SHA = "0f451f610d71ff6bb93297c831169f3a9c131af58ac04c5fbf77a271ac918430"
UPLOAD_SHA = "0cd405ada114838b6e364cea8786774b48ed3a8e03b4f90b3badfe9fb1ff1261"
REGISTRY_URL = "https://pub.fsa.gov.ru/rds/declaration/view/18390061/product"
ISSUE_DATE = "2023-11-23"
EXPIRY_DATE = "2028-11-22"


def certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    ids: set[str] = set()
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list response")
        batch_ids = [str(x.get("certificate_id")) for x in batch]
        if ids.intersection(batch_ids):
            raise RuntimeError("Duplicate Ozon certificate ID during pagination")
        ids.update(batch_ids)
        out.extend(batch)
        if len(batch) < 100:
            return out
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def live_products(client: Client, rows: list[dict[str, str]]) -> dict[str, dict]:
    offers = [r["offer_id"] for r in rows]
    out: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[start:start + 100]})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid Ozon product info response")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in out:
                raise RuntimeError("Duplicate or empty Ozon offer identity")
            out[offer] = {"product_id": str(item.get("id", "")), "sku": str(item.get("sku", "")),
                          "is_archived": bool(item.get("is_archived"))}
    return out


def main() -> None:
    workbook_reader.WORKBOOK_NUMBER_SUFFIX = SUFFIX
    rows = workbook_reader.read_target_rows()
    offers = [r["offer_id"] for r in rows]
    if len(rows) != 269 or len(set(offers)) != 269:
        raise RuntimeError(f"Expected 269 unique mapped offers, got {len(rows)}/{len(set(offers))}")
    if any(r["manual_flag"].strip().lower() == "да" for r in rows):
        raise RuntimeError("Workbook contains unresolved manual-review flags")
    if any(not re.search(r"\bAL\d+", r["name"], re.I) or
           not any(word in r["name"].lower() for word in ("трек", "шинопровод")) for r in rows):
        raise RuntimeError("At least one mapped title does not identify a Feron AL track luminaire")
    if not SOURCE.is_file() or digest(SOURCE) != SOURCE_SHA:
        raise RuntimeError("Original FSA declaration scan is missing or changed")
    if not UPLOAD.is_file() or digest(UPLOAD) != UPLOAD_SHA or UPLOAD.stat().st_size > 15_000_000:
        raise RuntimeError("Prepared PDF is missing, changed, or exceeds the Ozon upload guard")

    copies = []
    for row in rows:
        path = FERON / row["file_in_offer"]
        if not path.is_file() or digest(path) != SOURCE_SHA:
            raise RuntimeError("Missing or changed per-offer declaration copy: " + str(path))
        copies.append({"offer_id": row["offer_id"], "path": str(path), "sha256": digest(path),
                       "size": path.stat().st_size})

    client = Client()
    live = live_products(client, rows)
    if len(live) != 269:
        raise RuntimeError(f"Ozon returned {len(live)} of 269 mapped offers")
    targets, archived = [], []
    for row in rows:
        actual = live.get(row["offer_id"])
        expected = {"product_id": row["workbook_product_id"], "sku": row["workbook_sku"]}
        if not actual or actual["product_id"] != expected["product_id"] or actual["sku"] != expected["sku"]:
            raise RuntimeError("Workbook/live Ozon identity mismatch for " + row["offer_id"])
        entry = {"offer_id": row["offer_id"], "feron_article": row["feron_article"],
                 "name": row["name"], "product_id": actual["product_id"], "sku": actual["sku"],
                 "is_archived": actual["is_archived"]}
        (archived if actual["is_archived"] else targets).append(entry)
    if len(targets) != 267 or len(archived) != 2:
        raise RuntimeError(f"Unexpected active/archive split: {len(targets)}/{len(archived)}")
    if len({x["sku"] for x in targets}) != len(targets):
        raise RuntimeError("Active target SKUs are not unique")

    records = certificates(client)
    tail = norm(SUFFIX)
    matching = [c for c in records if norm(c.get("certificate_number", "")).endswith(tail)]
    exact = [c for c in records if norm(c.get("certificate_number", "")) == norm(NUMBER)]
    if matching or exact:
        raise RuntimeError("Ozon already has a matching declaration; reconcile instead of creating")
    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    if lookup.status_code != 404:
        raise RuntimeError(f"Ozon exact-number lookup returned {lookup.status_code}; create not authorized by preflight")

    plan = {
        "planned_at": now(), "number": NUMBER, "workbook_number": "ЕАЭС N RU Д-CN.PA010.В.00909/23",
        "number_note": "Live FSA record 18390061 displays PA10 (without the extra zero found in the scan and workbook). Use the exact active registry number.",
        "document_type": "DECLARATION", "ozon_type_code": "declaration", "country": "RU",
        "accordance_type": "EAEU", "issue_date": ISSUE_DATE, "expire_date": EXPIRY_DATE,
        "product_scope": "Feron general-purpose track luminaires, series AL; TR EAEU 037/2016.",
        "registry_evidence": {"url": REGISTRY_URL, "record_id": 18390061, "status": "Действует",
                              "registration_date": ISSUE_DATE, "valid_until": EXPIRY_DATE,
                              "product_scope": "Feron trademark, series AL; general-purpose track luminaires"},
        "source_file": {"path": str(SOURCE), "sha256": digest(SOURCE), "size": SOURCE.stat().st_size},
        "upload_file": {"path": str(UPLOAD.resolve()), "sha256": digest(UPLOAD), "size": UPLOAD.stat().st_size},
        "source_workbook": {"path": str(workbook_reader.WORKBOOK), "sha256": digest(workbook_reader.WORKBOOK)},
        "workbook_target_count": len(rows), "local_offer_copies": copies,
        "ozon_preflight": {"checked_at": now(), "certificate_list_count": len(records),
                           "matching_suffix_records": len(matching), "exact_records": len(exact),
                           "exact_info_http_status": lookup.status_code,
                           "live_identity_count": len(live), "identity_mismatches": 0,
                           "active_target_count": len(targets), "archived_target_count": len(archived)},
        "targets": targets, "archived_excluded_pending": archived,
        "seed_offer": targets[0]["offer_id"], "seed_product_id": targets[0]["product_id"],
        "seed_sku": targets[0]["sku"], "local_cleanup_allowed": False,
    }
    output = BASE / "feron_00909_ozon_plan.json"
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"plan": str(output), "workbook_offers": len(rows), "active_targets": len(targets),
                      "archived_excluded": [{"offer_id": x["offer_id"], "product_id": x["product_id"], "sku": x["sku"]} for x in archived],
                      "registry_number": NUMBER, "ozon_existing_suffix_matches": len(matching),
                      "local_copies_verified": len(copies)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
