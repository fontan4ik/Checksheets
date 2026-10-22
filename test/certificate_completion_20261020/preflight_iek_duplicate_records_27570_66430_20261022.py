#!/usr/bin/env python3
"""Fresh, read-only preflight for two already approved IEK declarations."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "iek_duplicate_records_27570_66430_preflight_20261022.json"
EDGES = HERE / "verified_group_edges_current_20261022.csv"
MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBERS = {
    "RU Д-RU.РА04.В.27570/26": {
        "allowed_tnved": {"9403700008"},
        "record_ids": {5530976, 5447907},
        "type_code": "declaration",
        "issue_date": "2026-05-18",
        "expire_date": "2027-08-30",
    },
    "ЕАЭС N RU Д-CN.РА02.В.66430/26": {
        "allowed_tnved": {"8536201007"},
        "record_ids": {5520308, 5448146},
        "type_code": "declaration",
        "issue_date": "2026-03-18",
        "expire_date": "2027-10-17",
    },
}


def codes(values: list[str]) -> list[str]:
    return sorted({str(v).split(" - ", 1)[0].strip() for v in values if str(v).strip()})


def wb_codes(card: dict) -> list[str]:
    result = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in label and "тнвед" not in label:
            continue
        raw = item.get("value")
        result.extend(str(v).split(" - ", 1)[0].strip() for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(result))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_first")
    manifest = json.loads(MANIFEST.read_text())
    source_groups = {g["number"]: g for g in manifest.get("groups") or []}
    targets = []
    with EDGES.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row["number"] in NUMBERS:
                targets.append({k: row[k] for k in (
                    "brand", "number", "type", "offer_id", "product_id", "sku", "ozon_state", "wb_nmID", "wb_state")})
    if len(targets) != 23 or len({x["offer_id"] for x in targets}) != 23:
        raise RuntimeError(f"target_edge_set_changed:{len(targets)}")

    group_source = {}
    for number in NUMBERS:
        source_key = number.removeprefix("ЕАЭС N ")
        g = source_groups.get(source_key)
        if not g or not g.get("source_evidence_verified") or g.get("admission") != "official_exact_assignment_sha_number_date_pdf_confirmed":
            raise RuntimeError(f"official_source_admission_missing:{number}")
        upload = g["upload_file"]
        path = pathlib.Path(upload["path"])
        if not path.is_file():
            raise RuntimeError(f"source_pdf_missing:{number}")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != upload["sha256"]:
            raise RuntimeError(f"source_pdf_sha_mismatch:{number}")
        group_source[number] = {"path": str(path), "sha256": sha, "size": path.stat().st_size,
                                "source_urls": sorted({t.get("source_url", "") for t in g.get("targets") or []})}

    c = Client()
    offers = [x["offer_id"] for x in targets]
    products = c.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items") or []
    attrs = c.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result") or []
    if len(products) != len(offers) or len(attrs) != len(offers):
        raise RuntimeError("ozon_target_snapshot_incomplete")
    pmap = {str(x.get("offer_id")): x for x in products}
    amap = {str(x.get("offer_id")): x for x in attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("ozon_target_offer_set_changed")

    certs = []
    for page in range(1, 101):
        result = c.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        certs.extend(batch)
        if page >= int(result.get("page_count") or 0):
            break
    else:
        raise RuntimeError("ozon_certificate_page_limit")

    records_by_number = {}
    bindings_by_number = {}
    for number, info in NUMBERS.items():
        exact = [x for x in certs if norm_number(x.get("certificate_number")) == norm_number(number)
                 and x.get("type_code") == info["type_code"]]
        if len(exact) != 2 or {int(x.get("certificate_id")) for x in exact} != info["record_ids"]:
            raise RuntimeError(f"duplicate_record_set_changed:{number}:{[x.get('certificate_id') for x in exact]}")
        for record in exact:
            if (record.get("status_code") != "approved"
                    or str(record.get("issue_date", ""))[:10] != info["issue_date"]
                    or str(record.get("expire_date", ""))[:10] != info["expire_date"]):
                raise RuntimeError(f"record_status_or_date_conflict:{number}:{record.get('certificate_id')}")
        records_by_number[number] = [{k: row.get(k) for k in (
            "certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")}
            for row in exact]
        combined = {}
        for record in exact:
            bindings = c.ozon_bindings(int(record["certificate_id"]))
            for binding in bindings:
                pid = str(binding.get("product_id"))
                if pid in combined and str(combined[pid].get("sku")) != str(binding.get("sku")):
                    raise RuntimeError(f"duplicate_record_product_sku_conflict:{number}:{pid}")
                combined[pid] = binding
        bindings_by_number[number] = combined

    rows = []
    for target in targets:
        offer = target["offer_id"]
        number = target["number"]
        info = NUMBERS[number]
        p, a = pmap[offer], amap[offer]
        av = {str(x.get("id")): [str(v.get("value") or "").strip() for v in x.get("values") or []
              if str(v.get("value") or "").strip()] for x in a.get("attributes") or []}
        tnved = codes(av.get("22232", []))
        if (str(p.get("product_id") or p.get("id")) != target["product_id"]
                or str(p.get("sku")) != target["sku"]
                or p.get("is_archived") is not False
                or av.get("85") != [target["brand"]]
                or not tnved or not set(tnved) <= info["allowed_tnved"]):
            raise RuntimeError(f"live_ozon_product_or_scope_conflict:{offer}:{tnved}:{av.get('85')}")
        card_rows = c.wb_cards(offer)
        if len(card_rows) != 1:
            raise RuntimeError(f"wb_exact_card_count:{offer}:{len(card_rows)}")
        card = card_rows[0]
        if (str(card.get("vendorCode")) != offer
                or str(card.get("nmID")) != target["wb_nmID"]
                or str(card.get("brand") or "").strip().casefold() != target["brand"].casefold()
                or wb_codes(card) != sorted(info["allowed_tnved"])):
            raise RuntimeError(f"wb_product_or_scope_conflict:{offer}:{wb_codes(card)}")
        docs = ((card.get("documents") or {}).get("items") or [])
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(number)
                and str(d.get("startDate", ""))[:10] == info["issue_date"]
                and str(d.get("endDate", ""))[:10] == info["expire_date"]]
        valid_docs = [d for d in same if (d.get("verdict") or {}).get("verified") is True
                      and (d.get("verdict") or {}).get("reason") == "valid"]
        if len(same) != 1 or len(valid_docs) != 1:
            raise RuntimeError(f"wb_document_not_exactly_valid:{offer}:{len(same)}")
        binding = bindings_by_number[number].get(target["product_id"])
        if binding and str(binding.get("sku")) != target["sku"]:
            raise RuntimeError(f"existing_binding_sku_mismatch:{offer}")
        rows.append({**target, "product_name": p.get("name"), "ozon_brand_values": av.get("85"),
                     "ozon_model_values": av.get("9048", []), "ozon_tnved_codes": tnved,
                     "ozon_binding_existing": binding is not None,
                     "ozon_binding_status": binding.get("product_status_code") if binding else None,
                     "wb_document_valid": True,
                     "wb_document": {k: valid_docs[0].get(k) for k in (
                         "type", "number", "startDate", "endDate", "verdict")}})

    result = {
        "checked_at_utc": now(), "read_only": True, "source_manifest": str(MANIFEST),
        "records_by_number": records_by_number, "sources_by_number": group_source,
        "target_count": len(rows),
        "already_bound_in_any_duplicate_record": sum(x["ozon_binding_existing"] for x in rows),
        "missing_from_both_duplicate_records": [x["offer_id"] for x in rows if not x["ozon_binding_existing"]],
        "ozon_existing_binding_statuses": dict(collections.Counter(x["ozon_binding_status"] for x in rows if x["ozon_binding_existing"])),
        "wb_exact_valid_count": sum(x["wb_document_valid"] for x in rows),
        "targets": rows,
        "selection_rule": "For each duplicate pair, bind only missing products to the approved record with the larger existing products_count; do not create another duplicate record.",
        "local_source_pdfs_deleted": False,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in (
        "checked_at_utc", "records_by_number", "target_count", "already_bound_in_any_duplicate_record",
        "missing_from_both_duplicate_records", "ozon_existing_binding_statuses", "wb_exact_valid_count")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
