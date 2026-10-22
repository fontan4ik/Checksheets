#!/usr/bin/env python3
"""Read-only live preflight for Gauss declaration 51581/22."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.PA01.В.51581/22"
NORMALIZED = norm_number(NUMBER)
ISSUE = "2022-02-01"
EXPIRY = "2027-01-31"
TNVED = {"8539519009"}
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/32b2e645b39d5de8fa7f9b9b.pdf"
SOURCE_SHA256 = "5d21a024f7c34c4eb02119e69cb28d72c0ccfc3ebc06214bf93526810d550b21"
LIVE_EDGES = HERE / "all_confirmed_source_assignments_live_20261022.csv"
OUT = HERE / "gauss_51581_live_preflight_20261022.json"


def attr_values(row: dict, ident: str) -> set[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return {str(v.get("value") or "").strip()
            for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()}


def tnved_values(row: dict) -> set[str]:
    return {v.split(" - ", 1)[0].strip() for v in attr_values(row, "22232")}


def wb_tnved_values(card: dict) -> set[str]:
    values: set[str] = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values.update((str(x) if x is not None else "").split(" - ", 1)[0].strip()
                      for x in raw if str(x).strip()) if isinstance(raw, list) else values.add(
                          (str(raw) if raw is not None else "").split(" - ", 1)[0].strip())
    return {x for x in values if x}


def load_targets() -> list[dict]:
    rows = []
    with LIVE_EDGES.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("normalized_number") != NORMALIZED:
                continue
            if row.get("brand", "").casefold() != "gauss" or row.get("type") != "declaration":
                raise RuntimeError("source edge identity conflict")
            rows.append({k: row.get(k) for k in ("offer_id", "ozon_product_id", "ozon_sku", "wb_nmID", "ozon_state", "wb_state", "source_files")})
    by_offer = {x["offer_id"]: x for x in rows}
    if len(rows) != 74 or len(by_offer) != 74:
        raise RuntimeError(f"expected 74 unique confirmed source edges, got {len(rows)}/{len(by_offer)}")
    return sorted(by_offer.values(), key=lambda x: x["offer_id"])


def all_ozon_records(client: Client) -> list[dict]:
    records = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("invalid Ozon certificate list page")
        records.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return records
    raise RuntimeError("Ozon certificate list page limit")


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight output already exists; inspect before retry")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("official Gauss PDF missing or hash changed")
    targets = load_targets()
    offers = [x["offer_id"] for x in targets]
    client = Client()

    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {"filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("live Ozon identity set incomplete")

    ozon_records = all_ozon_records(client)
    matches = [x for x in ozon_records if norm_number(x.get("certificate_number")) == NORMALIZED]
    if len(matches) > 1:
        raise RuntimeError("duplicate Ozon records for declaration")
    record = matches[0] if matches else None
    bindings = client.ozon_bindings(record["certificate_id"]) if record else []
    binding_by_product = {str(x.get("product_id") or ""): x for x in bindings}
    if len(binding_by_product) != len(bindings):
        raise RuntimeError("duplicate Ozon product bindings")
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing Ozon declaration metadata conflict")

    ozon_targets = []
    for t in targets:
        p, a = pmap[t["offer_id"]], amap[t["offer_id"]]
        brands = sorted(attr_values(a, "85"))
        tnved = sorted(tnved_values(a))
        product_id, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        bound = binding_by_product.get(product_id)
        reasons = []
        if p.get("is_archived") is not False:
            reasons.append("archived_or_archive_state_unknown")
        if brands != ["Gauss"]:
            reasons.append("ozon_brand_mismatch")
        if not tnved or not set(tnved) <= TNVED:
            reasons.append("ozon_tnved_out_of_document_scope")
        if t.get("ozon_product_id") and t["ozon_product_id"] != product_id:
            reasons.append("ozon_product_id_changed_since_source_audit")
        if t.get("ozon_sku") and t["ozon_sku"] != sku:
            reasons.append("ozon_sku_changed_since_source_audit")
        if bound and (str(bound.get("product_id") or "") != product_id or str(bound.get("sku") or "") != sku):
            reasons.append("existing_binding_identity_conflict")
        ozon_targets.append({**t, "live_product_id": product_id, "live_sku": sku,
            "product_id": product_id, "sku": sku,
            "live_brand": brands, "live_tnved": tnved, "is_archived": p.get("is_archived"),
            "existing_binding": bound, "safe_for_new_bind": not reasons and not bound,
            "safe_for_ozon": not reasons and not bound,
            "already_exact_binding": bool(bound and not reasons), "problems": reasons})

    wb_targets = []
    for i, t in enumerate(targets, 1):
        cards = client.wb_cards(t["offer_id"])
        if len(cards) != 1:
            wb_targets.append({**t, "unique_card_count": len(cards), "safe_for_update": False,
                               "already_exact": False, "problems": ["no_exact_wb_card" if not cards else "multiple_wb_cards"]})
        else:
            card = cards[0]
            brand = str(card.get("brand") or "")
            codes = sorted(wb_tnved_values(card))
            docs = ((card.get("documents") or {}).get("items") or [])
            number_docs = [d for d in docs if norm_number(d.get("number")) == NORMALIZED]
            exact = [d for d in number_docs if d.get("type") == 2
                     and str(d.get("startDate") or "")[:10] == ISSUE
                     and str(d.get("endDate") or "")[:10] == EXPIRY
                     and d.get("isEndless") is False]
            reasons = []
            if brand.casefold() != "gauss":
                reasons.append("wb_brand_mismatch")
            if not codes or not set(codes) <= TNVED:
                reasons.append("wb_tnved_out_of_document_scope")
            if number_docs and not exact:
                reasons.append("existing_document_metadata_conflict")
            wb_targets.append({**t, "unique_card_count": 1, "nmID": str(card.get("nmID") or ""),
                "brand_live": brand, "tnved_live": codes, "exact_document_count": len(exact),
                "existing_document_verdicts": [d.get("verdict") for d in exact],
                "safe_for_update": not reasons and not exact, "already_exact": bool(exact and not reasons),
                "problems": reasons})
        if i % 20 == 0:
            print(json.dumps({"live_wb_cards_prepared": i, "total": len(targets)}, ensure_ascii=False), flush=True)

    safe_ozon = [x for x in ozon_targets if x["safe_for_new_bind"]]
    existing_ozon = [x for x in ozon_targets if x["already_exact_binding"]]
    safe_wb = [x for x in wb_targets if x["safe_for_update"]]
    already_wb = [x for x in wb_targets if x["already_exact"]]
    out = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "issue_date": ISSUE, "expire_date": EXPIRY,
        "source_pdf": str(SOURCE), "source_sha256": SOURCE_SHA256,
        "source_date_scope": {"issue_date": ISSUE, "expire_date": EXPIRY, "tnved": sorted(TNVED), "regulation": "ТР ЕАЭС 037/2016"},
        "ozon_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")} if record else None),
        "ozon_existing_binding_count": len(bindings), "ozon_targets": ozon_targets,
        "ozon_safe_targets": len(safe_ozon), "ozon_already_exact_targets": len(existing_ozon),
        "ozon_problem_counts": dict(Counter(p for x in ozon_targets for p in x["problems"])),
        "wb_targets": wb_targets, "wb_safe_targets": len(safe_wb), "wb_already_exact_targets": len(already_wb),
        "wb_update_targets": len(safe_wb),
        "wb_problem_counts": dict(Counter(p for x in wb_targets for p in x["problems"])),
        "wb_review_left_pending": True, "local_source_deleted": False}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"saved": str(OUT), "ozon_record": out["ozon_record"],
        "ozon_safe_targets": out["ozon_safe_targets"], "ozon_already_exact": out["ozon_already_exact_targets"],
        "ozon_problems": out["ozon_problem_counts"], "wb_safe_targets": out["wb_safe_targets"],
        "wb_already_exact": out["wb_already_exact_targets"], "wb_problems": out["wb_problem_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
