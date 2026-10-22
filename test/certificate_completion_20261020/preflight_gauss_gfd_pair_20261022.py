#!/usr/bin/env python3
"""Read-only cross-platform preflight for Gauss GFD 004/020 and 037 documents."""
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

TNVED = {"9405420012"}
OUT = HERE / "gauss_gfd_pair_live_preflight_20261022.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
LIVE_EDGES = HERE / "all_confirmed_source_assignments_live_20261022.csv"
DOCS = [
    {
        "number": "ЕАЭС RU C-CN.НВ12.В.01250/24",
        "type_code": "certificate_of_conformity",
        "ozon_type": "CERTIFICATE_OF_CONFORMITY",
        "wb_type": 1,
        "issue_date": "2024-05-31",
        "expire_date": "2029-05-30",
        "source": ROOT / "output_to_user/certificates/group_1/documents/gauss/b35f33696bdfdfe23a91781d.pdf",
        "sha256": "1b763da18ff83df1b09596fee3b82d92c0cea2997467c0978355c4e818d1ce90",
        "fsa_record_id": 3442084,
        "fsa_url": "https://pub.fsa.gov.ru/rss/certificate/view/3442084/baseInfo",
        "scope": "TR CU 004/2011 and TR CU 020/2011; Gauss GFD LED floodlights",
    },
    {
        "number": "ЕАЭС N RU Д-CN.PA04.В.65150/24",
        "type_code": "declaration",
        "ozon_type": "DECLARATION",
        "wb_type": 2,
        "issue_date": "2024-05-31",
        "expire_date": "2029-05-30",
        "source": ROOT / "output_to_user/certificates/group_1/documents/gauss/84289bfc2e2b173292ad34d9.pdf",
        "sha256": "d8338a77eef5efb26031c200fbe5a4d33cb049522ed811dd77295fc110f17775",
        "fsa_record_id": 18944934,
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/18944934/common",
        "scope": "TR EAEU 037/2016; Gauss GFD LED floodlights",
    },
]


def values(row: dict, ident: str) -> set[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return {str(v.get("value") or "").strip()
            for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()}


def ozon_tnved(row: dict) -> set[str]:
    return {x.split(" - ", 1)[0].strip() for x in values(row, "22232")}


def wb_tnved(card: dict) -> set[str]:
    found: set[str] = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        batch = raw if isinstance(raw, list) else [raw]
        found.update(str(x).split(" - ", 1)[0].strip() for x in batch if str(x or "").strip())
    return found


def all_records(client: Client) -> list[dict]:
    result = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = body.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("invalid Ozon certificate page")
        result.extend(batch)
        if not batch or page >= int(body.get("page_count") or 0):
            return result
    raise RuntimeError("Ozon certificate page limit")


def targets_from_assignments() -> list[dict]:
    by_number: dict[str, dict[str, dict]] = {norm_number(d["number"]): {} for d in DOCS}
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = norm_number(row.get("Номер/название документа"))
            if key not in by_number:
                continue
            offer = row.get("Артикул продавца", "")
            prior = by_number[key].get(offer)
            record = {"offer_id": offer, "scope_evidence": row.get("Основание сопоставления"),
                      "source_product_url": row.get("URL карточки/основания"),
                      "product_name_assignment": row.get("Название товара Ozon"),
                      "tnved": row.get("ТН ВЭД") or row.get("ТНВЭД")}
            if prior and prior != record:
                raise RuntimeError("duplicate assignment row mismatch:" + offer)
            by_number[key][offer] = record
    offer_sets = [set(by_number[norm_number(d["number"])]) for d in DOCS]
    if any(len(x) != 96 for x in offer_sets) or offer_sets[0] != offer_sets[1]:
        raise RuntimeError(f"the two documents must each cover the same 96 offers: {[len(x) for x in offer_sets]}")
    with LIVE_EDGES.open(encoding="utf-8-sig", newline="") as stream:
        edges = [r for r in csv.DictReader(stream)
                 if any(norm_number(r.get("number")) == norm_number(d["number"]) for d in DOCS)]
    for d in DOCS:
        matches = [r for r in edges if norm_number(r.get("number")) == norm_number(d["number"])]
        if len(matches) != 96 or {r.get("offer_id") for r in matches} != offer_sets[0]:
            raise RuntimeError("live source edge set changed for " + d["number"])
    first = by_number[norm_number(DOCS[0]["number"])]
    return [first[offer] for offer in sorted(offer_sets[0])]


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight artifact exists; inspect before retry")
    for d in DOCS:
        if not d["source"].is_file() or hashlib.sha256(d["source"].read_bytes()).hexdigest() != d["sha256"]:
            raise RuntimeError("source file hash mismatch:" + d["number"])
    targets = targets_from_assignments()
    offers = [x["offer_id"] for x in targets]
    client = Client()
    product_rows, attribute_rows = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        product_rows.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attribute_rows.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or [])
    pmap = {str(x.get("offer_id") or ""): x for x in product_rows}
    amap = {str(x.get("offer_id") or ""): x for x in attribute_rows}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("live Ozon target set incomplete")

    ozon_records = all_records(client)
    doc_live = []
    for d in DOCS:
        matches = [x for x in ozon_records if norm_number(x.get("certificate_number")) == norm_number(d["number"])]
        if len(matches) > 1:
            raise RuntimeError("duplicate Ozon records:" + d["number"])
        record = matches[0] if matches else None
        if record and (record.get("type_code") != d["type_code"]
                       or str(record.get("issue_date") or "")[:10] != d["issue_date"]
                       or str(record.get("expire_date") or "")[:10] != d["expire_date"]):
            raise RuntimeError("Ozon record metadata conflict:" + d["number"])
        bindings = client.ozon_bindings(record["certificate_id"]) if record else []
        doc_live.append({**{k: d[k] for k in ("number", "type_code", "issue_date", "expire_date", "sha256", "fsa_record_id", "fsa_url", "scope")},
            "ozon_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "products_count")} if record else None),
            "ozon_existing_binding_count": len(bindings),
            "ozon_existing_binding_product_ids": sorted(str(x.get("product_id") or "") for x in bindings)})

    ozon_targets = []
    for t in targets:
        p, a = pmap[t["offer_id"]], amap[t["offer_id"]]
        brand = sorted(values(a, "85")); codes = sorted(ozon_tnved(a))
        product_id, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        problems = []
        if p.get("is_archived") is not False: problems.append("archived_or_archive_state_unknown")
        if [b.casefold() for b in brand] != ["gauss"]: problems.append("ozon_brand_mismatch")
        if not codes or not set(codes) <= TNVED: problems.append("ozon_tnved_out_of_document_scope")
        ozon_targets.append({**t, "product_id": product_id, "sku": sku, "brand_live": brand,
            "tnved_live": codes, "is_archived": p.get("is_archived"), "safe_for_ozon": not problems, "problems": problems})

    wb_targets = []
    for i, t in enumerate(targets, 1):
        cards = [c for c in client.wb_cards(t["offer_id"]) if str(c.get("vendorCode") or "") == t["offer_id"]]
        if len(cards) != 1:
            wb_targets.append({**t, "unique_card_count": len(cards), "safe_for_wb": False,
                               "problems": ["no_exact_wb_card" if not cards else "multiple_wb_cards"]})
            continue
        card = cards[0]; codes = sorted(wb_tnved(card)); brand = str(card.get("brand") or "")
        problems = []
        if brand.casefold() != "gauss": problems.append("wb_brand_mismatch")
        if not codes or not set(codes) <= TNVED: problems.append("wb_tnved_out_of_document_scope")
        per_doc = []
        docs_now = ((card.get("documents") or {}).get("items") or [])
        for d in DOCS:
            same = [x for x in docs_now if norm_number(x.get("number")) == norm_number(d["number"])]
            exact = [x for x in same if str(x.get("type")) == str(d["wb_type"])
                     and str(x.get("startDate") or "")[:10] == d["issue_date"]
                     and str(x.get("endDate") or "")[:10] == d["expire_date"]
                     and x.get("isEndless") is False]
            if same and not exact: problems.append("wb_existing_document_metadata_conflict:" + d["number"])
            per_doc.append({"number": d["number"], "existing_documents": same,
                            "already_exact": len(exact) == 1, "exact_count": len(exact)})
        wb_targets.append({**t, "unique_card_count": 1, "nmID": str(card.get("nmID") or ""),
            "brand_live": brand, "tnved_live": codes, "existing_documents": per_doc,
            "safe_for_wb": not problems, "problems": problems})
        if i % 20 == 0: print(json.dumps({"live_wb_cards_prepared": i, "total": len(targets)}, ensure_ascii=False), flush=True)

    out = {"checked_at_utc": now(), "read_only": True, "targets_expected": 96,
        "documents": doc_live, "ozon_targets": ozon_targets, "ozon_safe_targets": sum(x["safe_for_ozon"] for x in ozon_targets),
        "ozon_problem_counts": dict(Counter(p for x in ozon_targets for p in x["problems"])),
        "wb_targets": wb_targets, "wb_safe_targets": sum(x["safe_for_wb"] for x in wb_targets),
        "wb_problem_counts": dict(Counter(p for x in wb_targets for p in x["problems"])),
        "wb_review_left_for_marketplace": True, "local_sources_deleted": False}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"saved": str(OUT), "documents": [{"number": x["number"], "ozon_record": x["ozon_record"]} for x in doc_live],
        "targets": len(targets), "ozon_safe": out["ozon_safe_targets"], "ozon_problems": out["ozon_problem_counts"],
        "wb_safe": out["wb_safe_targets"], "wb_problems": out["wb_problem_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
