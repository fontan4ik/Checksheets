"""Read-only Ozon and source-file preflight for Navigator declaration 08110/24."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from preflight_arlight_06897_exact_20261014 import (  # noqa: E402
    api_post, live_ozon_number_lookup, norm, read_ozon_certificates, read_ozon_offers,
)

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
NUMBER = "ЕАЭС N RU Д-CN.РА11.В.08110/24"
FSA_RECORD_ID = "19670009"
ISSUE = "2024-12-02"
EXPIRY = "2029-12-01"
SAMPLE_DATE = "2024-01-10"
FSA_TNVED = {"8539520001", "8539520003", "8539520009"}
OUT = BASE / "navigator_08110_ozon_live_preflight_20261014_v2.json"


def main() -> None:
    rows = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if "08110/24" in str(row.get("Номер/название документа") or ""):
                rows.append(row)
    by_offer = {str(r.get("Артикул продавца") or "").strip(): r for r in rows}
    if len(rows) != 155 or len(by_offer) != 155 or "" in by_offer:
        raise RuntimeError(f"Expected 155 unique Navigator offers, found rows={len(rows)}, unique={len(by_offer)}")
    file_paths = sorted({str(r.get("Локальный файл") or "") for r in rows})
    source_files = []
    for rel in file_paths:
        path = ROOT / rel
        source_files.append({"path": str(path), "exists": path.is_file(),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                             "size_bytes": path.stat().st_size if path.is_file() else None})

    client = Client()
    offers = sorted(by_offer)
    products, attrs = read_ozon_offers(client, offers)
    certs = read_ozon_certificates(client)
    exact = [x for x in certs if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    lookup_status, lookup_body = api_post(client, "ozon", "/v1/product/certificate/info",
                                          {"certificate_number": NUMBER})
    exact_lookup = {"http_status": lookup_status,
                    "exact_record_absent": lookup_status == 404 and lookup_body.get("code") == 5,
                    "result": lookup_body.get("result") if lookup_status == 200 else None,
                    "error_code": lookup_body.get("code") if lookup_status != 200 else None}
    exact_ids = sorted({str(x.get("certificate_id") or "") for x in exact})

    targets = []
    for offer in offers:
        product, a = products[offer], attrs[offer]
        brand = [str(v.get("value") or "") for v in (a.get("85") or {}).get("values") or []]
        raw_codes = [str(v.get("value") or "") for v in (a.get("22232") or {}).get("values") or []]
        codes = sorted({v.split(" - ", 1)[0].strip() for v in raw_codes if v.strip()})
        source = by_offer[offer]
        targets.append({
            "offer_id": offer, "product_id": str(product.get("id") or product.get("product_id") or ""),
            "sku": str(product.get("sku") or ""), "active": product.get("is_archived") is False,
            "name": product.get("name"), "brand": brand, "tnved_values": raw_codes,
            "tnved_codes": codes, "source_document_number": source.get("Номер/название документа"),
            "source_article_evidence": source.get("Основание сопоставления"),
            "source_product_url": source.get("URL карточки/основания"),
            "source_pdf_url": source.get("URL документа"),
            "source_pdf_hash": source.get("SHA256 фактический"),
        })
    record_id = int(exact_ids[0]) if len(exact_ids) == 1 and exact_ids[0].isdigit() else None
    bindings = []
    if record_id is not None:
        last_id, count = 0, None
        while True:
            status, body = api_post(client, "ozon", "/v1/product/certificate/products/list",
                                    {"certificate_id": record_id, "last_id": last_id, "limit": 500})
            if status != 200:
                raise RuntimeError(f"Ozon declaration binding read failed: HTTP {status}")
            result = body.get("result") or {}
            batch, current_count = result.get("items"), result.get("count")
            if not isinstance(batch, list) or not isinstance(current_count, int):
                raise RuntimeError("Ozon declaration binding response malformed")
            if count is None:
                count = current_count
            elif count != current_count:
                raise RuntimeError("Ozon binding count changed during read")
            bindings.extend(batch)
            if len(bindings) == count:
                break
            if not batch or len(bindings) > count:
                raise RuntimeError("Ozon declaration binding pagination incomplete")
            last_id = max(int(x.get("product_id") or 0) for x in batch)

    out = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "fsa_record_id": FSA_RECORD_ID, "issue_date": ISSUE, "expiry_date": EXPIRY,
        "manufacturer": "XIAMEN NEEX OPTICAL ELECTRONIC TECHNOLOGY CO., LTD.",
        "scope": "Navigator NLL LED lamps; series production from sample date",
        "sample_date_cutoff": SAMPLE_DATE, "fsa_tnved_codes": sorted(FSA_TNVED),
        "assignment_count": len(rows), "source_file_paths": file_paths,
        "source_files": source_files, "ozon_exact_records": exact,
        "ozon_exact_lookup": exact_lookup, "ozon_binding_count": len(bindings),
        "ozon_binding_status_counts": dict(collections.Counter(
            str(x.get("product_status_code") or "UNKNOWN") for x in bindings)),
        "ozon_product_state_counts": dict(collections.Counter(
            ("active" if x["active"] else "archived_or_inactive") for x in targets)),
        "ozon_brand_counts": {" | ".join(k) if k else "<missing>": v
                              for k, v in collections.Counter(tuple(x["brand"]) for x in targets).items()},
        "ozon_tnved_counts": dict(collections.Counter(code for x in targets for code in x["tnved_codes"])),
        "ozon_missing_tnved_count": sum(not x["tnved_codes"] for x in targets),
        "ozon_in_scope_tnved_product_count": sum(bool(set(x["tnved_codes"]) & FSA_TNVED) for x in targets),
        "ozon_out_of_scope_tnved_product_count": sum(bool(x["tnved_codes"])
                                                       and not (set(x["tnved_codes"]) & FSA_TNVED)
                                                       for x in targets),
        "missing_sku_count": sum(not x["sku"] or x["sku"] == "0" for x in targets),
        "unique_sku_count": len({x["sku"] for x in targets if x["sku"]}),
        "targets": targets,
        "existing_bindings": [{"product_id": str(x.get("product_id") or ""),
                               "sku": str(x.get("sku") or ""),
                               "product_status_code": x.get("product_status_code")}
                              for x in bindings],
        "batch_date_limitation_requires_lot_date_evidence": True,
        "marketplace_mutation_sent": False,
    }
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in out.items() if k not in ("targets", "existing_bindings", "ozon_exact_records")},
                     ensure_ascii=False, indent=2))
    print("MISMATCH_SAMPLES", json.dumps([{"offer_id": x["offer_id"], "brand": x["brand"],
                                           "tnved_codes": x["tnved_codes"], "active": x["active"]}
                                          for x in targets if not x["active"] or x["brand"] != ["Navigator"]
                                          or not set(x["tnved_codes"]).issubset(FSA_TNVED)][:15],
                                          ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
