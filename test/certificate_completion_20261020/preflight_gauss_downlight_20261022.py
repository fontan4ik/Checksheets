#!/usr/bin/env python3
"""Read-only live preflight for the exact GAUSS Elementary Downlight pair."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, digest, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import doc_key, norm_number  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402

PACKAGE = ROOT / "output_to_user/certificates/additional_search/brand_research/gauss/followup_2026_10_02_e_b2b_article_link"
COVERAGE = PACKAGE / "coverage.csv"
CERTIFICATE_PDF = ROOT / "output_to_user/certificates/additional_search/brand_research/gauss/docs/slim_004_020.pdf"
DECLARATION_PDF = PACKAGE / "docs/EAES_D-CN-RA03-B-12843-22_TR037.pdf"
OUT = HERE / "gauss_downlight_live_preflight_20261022.json"

DOCS = [
    {
        "number": "ЕАЭС RU C-CN.АД65.В.00380/22",
        "type_code": "certificate_of_conformity",
        "type_name": "CERTIFICATE_OF_CONFORMITY",
        "issue_date": "2022-04-12",
        "expire_date": "2027-04-11",
        "fsa_record_id": 3074857,
        "fsa_url": "https://pub.fsa.gov.ru/rss/certificate/view/3074857/product",
        "file": CERTIFICATE_PDF,
        "sha256": "964ff5b7049bb55bdef6f7c6a2b69ab1de5eb07d2f12d4b8c6653742a6b2eb59",
        "allowed_tnved": {"9405110013", "9405110033", "9405110039"},
        "wb_type": 1,
    },
    {
        "number": "ЕАЭС N RU Д-CN.РА03.В.12843/22",
        "type_code": "declaration",
        "type_name": "DECLARATION",
        "issue_date": "2022-04-18",
        "expire_date": "2027-04-17",
        "fsa_record_id": 16679032,
        "fsa_url": "https://pub.fsa.gov.ru/rds/declaration/view/16679032/product",
        "file": DECLARATION_PDF,
        "sha256": "e8fbc529567266a4e3db2a137a9ac3c48bc6adc9c063362e2565514abc346078",
        "allowed_tnved": {"9405110013", "9405110033", "9405110039"},
        "wb_type": 2,
    },
]


def load_targets() -> list[dict]:
    wanted = ("9100420205-1", "9100420205-2", "9100420205-5",
              "9100420205T-1", "9100420205T-2", "9100420205T-5")
    with COVERAGE.open(newline="", encoding="utf-8-sig") as stream:
        rows = {row["seller_article"]: row for row in csv.DictReader(stream)}
    if any(offer not in rows for offer in wanted):
        raise RuntimeError("official GAUSS article crosswalk is incomplete")
    targets = []
    for offer in wanted:
        row = rows[offer]
        if row["official_ean"] not in {"4610122563381", "4610122563398"}:
            raise RuntimeError("manufacturer EAN crosswalk changed")
        targets.append({
            "offer_id": offer,
            "brand_expected": "Gauss",
            "product_id": str(row["ozon_product_id"]),
            "sku": str(row["ozon_sku"]),
            "barcode": str(row["ozon_barcode"]),
            "name_expected": row["ozon_listing_title"],
            "official_model_match": row["official_model_match"],
            "official_ean": row["official_ean"],
        })
    if len({x["offer_id"] for x in targets}) != 6 or len({x["product_id"] for x in targets}) != 6 or len({x["sku"] for x in targets}) != 6:
        raise RuntimeError("target identities are not unique")
    return targets


def attr_values(row: dict, ident: str) -> set[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return {str(v.get("value") or "").strip()
            for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()}


def scan_wb(client: Client, offers: set[str]) -> tuple[dict[str, list[dict]], dict]:
    cursor = {"limit": 100}
    seen = set()
    matched = []
    pages = raw_rows = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        data = body.get("data", body)
        batch = data.get("cards") or data.get("items") or []
        returned = data.get("cursor") or body.get("cursor") or {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("WB full catalog page/cursor is invalid")
        pages += 1
        raw_rows += len(batch)
        matched.extend(c for c in batch if str(c.get("vendorCode") or "") in offers)
        if len(batch) < 100:
            break
        sig = (returned.get("updatedAt"), returned.get("nmID"))
        if None in sig or sig in seen:
            raise RuntimeError("WB full catalog cursor is incomplete or repeated")
        seen.add(sig)
        cursor = {"limit": 100, "updatedAt": sig[0], "nmID": sig[1]}
    unique, duplicates = runner.deduplicate_equivalent_wb_rows(matched)
    by_offer: dict[str, list[dict]] = {}
    for card in unique:
        by_offer.setdefault(str(card.get("vendorCode") or ""), []).append(card)
    return by_offer, {"complete": True, "pages": pages, "raw_rows": raw_rows,
                      "matched_rows": len(matched), "equivalent_duplicate_rows_removed": duplicates}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preflight_output_exists_inspect_before_retry")
    targets = load_targets()
    for doc in DOCS:
        if not doc["file"].is_file() or digest(doc["file"]) != doc["sha256"]:
            raise RuntimeError("source PDF missing or hash changed: " + doc["number"])

    client = Client()
    offers = [x["offer_id"] for x in targets]
    ids = [int(x["product_id"]) for x in targets]
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attributes = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers),
    }).get("result")
    if not isinstance(products, list) or len(products) != len(targets):
        raise RuntimeError("Ozon live product set incomplete")
    if not isinstance(attributes, list) or len(attributes) != len(targets):
        raise RuntimeError("Ozon live attribute set incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attributes}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("Ozon live offer identity set changed")
    for t in targets:
        p, a = pmap[t["offer_id"]], amap[t["offer_id"]]
        if (str(p.get("product_id") or p.get("id") or "") != t["product_id"]
                or str(p.get("sku") or "") != t["sku"] or p.get("is_archived") is True):
            raise RuntimeError("Ozon offer/product/SKU identity changed: " + t["offer_id"])
        if str(a.get("id") or a.get("product_id") or "") != t["product_id"]:
            raise RuntimeError("Ozon product attribute identity changed: " + t["offer_id"])
        brands = attr_values(a, "85")
        tnved = {v.split(" - ", 1)[0].strip() for v in attr_values(a, "22232")}
        t["ozon_brand_scope_valid"] = bool(brands) and {b.casefold() for b in brands} == {"gauss"}
        t["ozon_tnved_scope_valid"] = bool(tnved) and all(tnved <= d["allowed_tnved"] for d in DOCS)
        t["ozon_scope_conflict"] = None if t["ozon_brand_scope_valid"] and t["ozon_tnved_scope_valid"] else {
            "brands": sorted(brands), "tnved_codes": sorted(tnved),
        }
        t.update({"ozon_name_live": p.get("name"), "ozon_is_archived": p.get("is_archived"),
                  "ozon_brand_live": sorted(brands), "ozon_tnved_live": sorted(tnved)})

    certs = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list page invalid")
        certs.extend(batch)
        if not batch or page >= int(result.get("page_count") or page):
            break
    else:
        raise RuntimeError("Ozon certificate list page limit")

    ozon_docs = []
    for doc in DOCS:
        matches = [x for x in certs if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        record_rows = []
        for record in matches:
            binds = client.ozon_bindings(record["certificate_id"])
            by_pid = {str(x.get("product_id")): x for x in binds}
            record_rows.append({
                **{k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date", "accordance_type_code", "products_count")},
                "binding_count": len(binds),
                "target_bindings": [{"offer_id": t["offer_id"], "product_id": t["product_id"],
                                     "sku": t["sku"], "binding": by_pid.get(t["product_id"])} for t in targets],
            })
        ozon_docs.append({"number": doc["number"], "matches": record_rows})

    wb_by_offer, wb_catalog = scan_wb(client, set(offers))
    wb_cards = []
    for target in targets:
        cards = wb_by_offer.get(target["offer_id"], [])
        card_rows = []
        for card in cards:
            tnv = []
            for ch in card.get("characteristics") or []:
                name = "".join(str(ch.get("name") or "").casefold().split()).replace("ё", "е")
                if "тнвэд" in name or "тнвед" in name:
                    raw = ch.get("value")
                    tnv.extend([str(x).split(" - ", 1)[0].strip() for x in raw] if isinstance(raw, list) else [str(raw).split(" - ", 1)[0].strip()])
            docs = ((card.get("documents") or {}).get("items") or [])
            card_rows.append({
                "nmID": str(card.get("nmID") or ""), "vendorCode": card.get("vendorCode"),
                "brand": card.get("brand"), "title": card.get("title"),
                "tnved_codes": sorted(set(x for x in tnv if x)),
                "matching_docs": [d for d in docs if any(norm_number(d.get("number")) == norm_number(m["number"]) for m in DOCS)],
            })
        wb_cards.append({"offer_id": target["offer_id"], "unique_exact_card_count": len(cards), "cards": card_rows})

    conflicts = []
    ozon_scope_conflicts = [
        {"offer_id": t["offer_id"], **t["ozon_scope_conflict"]}
        for t in targets if t["ozon_scope_conflict"]
    ]
    for item in ozon_docs:
        if len(item["matches"]) > 1:
            conflicts.append("duplicate_ozon_certificate:" + item["number"])
        for record in item["matches"]:
            r = record
            if r.get("type_code") not in {"certificate_of_conformity", "declaration"}:
                conflicts.append("ozon_type_conflict:" + item["number"])
            if str(r.get("issue_date") or "")[:10] != next(d["issue_date"] for d in DOCS if d["number"] == item["number"]):
                conflicts.append("ozon_issue_date_conflict:" + item["number"])
            if str(r.get("expire_date") or "")[:10] != next(d["expire_date"] for d in DOCS if d["number"] == item["number"]):
                conflicts.append("ozon_expiry_date_conflict:" + item["number"])
            if r.get("accordance_type_code") != "EAEU":
                conflicts.append("ozon_accordance_conflict:" + item["number"])
            if r.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}:
                conflicts.append("ozon_document_declined:" + item["number"])
    for card in wb_cards:
        if card["unique_exact_card_count"] > 1:
            conflicts.append("duplicate_wb_card:" + card["offer_id"])
        if card["unique_exact_card_count"] == 1:
            tnv = set(card["cards"][0]["tnved_codes"])
            if not tnv or not all(tnv <= d["allowed_tnved"] for d in DOCS):
                conflicts.append("wb_tnved_out_of_scope:" + card["offer_id"])
            if str(card["cards"][0].get("brand") or "").casefold() != "gauss":
                conflicts.append("wb_brand_out_of_scope:" + card["offer_id"])

    wb_card_conflicts = [x for x in conflicts if x.startswith("wb_") or x.startswith("duplicate_wb_card:")]
    ozon_record_conflicts = [x for x in conflicts if x not in wb_card_conflicts]

    result = {
        "checked_at_utc": now(), "read_only": True,
        "manufacturer_source": {
            "package": str(PACKAGE),
            "official_card_snapshots": ["source_snapshots/gauss_b2b_9100420205.html", "source_snapshots/gauss_b2b_9100420205T.html"],
            "crosswalk_count": len(targets), "targets": targets,
        },
        "documents": [{k: (str(v) if isinstance(v, Path) else sorted(v) if isinstance(v, set) else v)
                       for k, v in d.items() if k != "file"} | {"file": str(d["file"]), "local_sha256": digest(d["file"])} for d in DOCS],
        "ozon_documents": ozon_docs,
        "wb_catalog": wb_catalog,
        "wb_cards": wb_cards,
        "conflicts": conflicts,
        "ozon_scope_conflicts": ozon_scope_conflicts,
        "safe_to_execute_ozon": not ozon_scope_conflicts and not ozon_record_conflicts,
        "safe_to_execute_wb": not wb_card_conflicts and all(x["unique_exact_card_count"] == 1 for x in wb_cards),
        "safe_to_execute": not conflicts and not ozon_scope_conflicts and all(x["unique_exact_card_count"] == 1 for x in wb_cards),
        "wb_review_left_pending": True,
        "local_files_deleted": False,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT)
    print(json.dumps({
        "preflight_file": str(OUT), "checked_at_utc": result["checked_at_utc"],
        "ozon_products": [{k: x.get(k) for k in ["offer_id", "product_id", "sku", "ozon_brand_live", "ozon_tnved_live", "ozon_is_archived"]} for x in targets],
        "ozon_document_records": [{"number": x["number"], "records": len(x["matches"]), "metadata": [{k: r.get(k) for k in ["certificate_id", "status_code", "issue_date", "expire_date", "products_count"]} for r in x["matches"]]} for x in ozon_docs],
        "wb_catalog": wb_catalog,
        "wb_cards": [{"offer_id": x["offer_id"], "count": x["unique_exact_card_count"], "cards": x["cards"]} for x in wb_cards],
        "conflicts": conflicts, "ozon_scope_conflicts": ozon_scope_conflicts,
        "safe_to_execute_ozon": result["safe_to_execute_ozon"],
        "safe_to_execute_wb": result["safe_to_execute_wb"],
        "safe_to_execute": result["safe_to_execute"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
