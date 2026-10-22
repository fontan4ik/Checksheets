"""Fresh read-only Ozon/WB preflight for the requested residual document groups.

This intentionally uses only marketplace read endpoints. It does not call upload,
bind, update, or delete APIs and does not touch local source PDFs.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client  # noqa: E402

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = BASE / "residual_groups_live_preflight_20261014.json"

GROUPS = {
    "Jazzway 37909/22": {"substring": "37909/22", "brands": {"jazzway"}},
    "Stekker 01452/23": {"substring": "01452/23", "brands": {"stekker"}},
    "Navigator 39095/25": {"substring": "39095/25", "brands": {"navigator"}},
    "Saffit 53562/22": {"substring": "53562/22", "brands": {"saffit"}},
    "Saffit 05931/22": {"substring": "05931/22", "brands": {"saffit"}},
    "Gauss 02212/22": {"substring": "02212/22", "brands": {"gauss"}},
    "Gauss 07695/22": {"substring": "07695/22", "brands": {"gauss"}},
}

CHAR_MAP = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H",
                          "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                          "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D",
                          "П": "P"})


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def post(client: Client, platform: str, path: str, body: dict) -> dict:
    host, headers = (("https://api-seller.ozon.ru", client.ozon_headers) if platform == "ozon"
                     else ("https://content-api.wildberries.ru", client.wb_headers))
    response = client.http.post(host + path, json=body, headers=headers, timeout=(20, 120))
    if response.status_code != 200:
        raise RuntimeError(f"read endpoint {platform}{path} returned HTTP {response.status_code}")
    return response.json()


def read_ozon_bindings(client: Client, certificate_id: int) -> list[dict]:
    items: list[dict] = []
    last_id = 0
    expected = None
    seen: set[str] = set()
    while True:
        body = post(client, "ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "last_id": last_id, "limit": 1000})
        result = body.get("result") or {}
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError(f"malformed bindings for Ozon certificate {certificate_id}")
        if expected is None:
            expected = count
        elif expected != count:
            raise RuntimeError(f"binding count changed during certificate {certificate_id} read")
        for row in batch:
            pid = str(row.get("product_id") or "")
            if not pid or pid in seen:
                raise RuntimeError(f"missing/repeated product_id for Ozon certificate {certificate_id}")
            seen.add(pid)
        items.extend(batch)
        if len(items) == expected:
            return items
        if not batch or len(items) > expected:
            raise RuntimeError(f"incomplete bindings for Ozon certificate {certificate_id}")
        last_id = batch[-1]["product_id"]


def read_wb_cards(client: Client, offer: str) -> list[dict]:
    found: list[dict] = []
    cursor = {"limit": 100}
    seen: set[tuple[object, object]] = set()
    while True:
        body = post(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer}}})
        batch = body.get("cards")
        if body.get("error") or not isinstance(batch, list):
            raise RuntimeError(f"malformed WB exact-card search for {offer}")
        found.extend(card for card in batch if str(card.get("vendorCode") or "") == offer)
        returned = body.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError(f"WB cursor total mismatch for {offer}")
        if len(batch) < 100:
            return found
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError(f"WB cursor missing/repeated for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}


def tnved_values(card_or_attr_rows: list[dict], *, ozon: bool = False) -> list[str]:
    if ozon:
        return [str(v.get("value") or "") for attr in card_or_attr_rows
                if str(attr.get("id")) == "22232" for v in attr.get("values") or []]
    return [str(v) for attr in card_or_attr_rows if int(attr.get("id", -1)) == 15000001
            for v in (attr.get("value") or [])]


def main() -> None:
    rows = list(csv.DictReader(ASSIGNMENTS.open(encoding="utf-8-sig", newline="")))
    expected: dict[str, dict[str, dict]] = {}
    for group, selector in GROUPS.items():
        selected = [r for r in rows if selector["substring"] in r.get("Номер/название документа", "")
                    and str(r.get("Бренд подтвержденный") or "").strip().lower() in selector["brands"]]
        by_offer: dict[str, dict] = {}
        for row in selected:
            offer = str(row.get("Артикул продавца") or "").strip()
            if offer:
                by_offer.setdefault(offer, row)
        if len(by_offer) != len(set(by_offer)):
            raise RuntimeError(f"duplicate offer assignment in {group}")
        expected[group] = by_offer

    offers = sorted({offer for group in expected.values() for offer in group})
    client = Client()
    products: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        body = post(client, "ozon", "/v3/product/info/list", {"offer_id": batch})
        items = body.get("items") or (body.get("result") or {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("malformed Ozon product-info response")
        for item in items:
            offer = str(item.get("offer_id") or "")
            if not offer or offer in products:
                raise RuntimeError("missing/duplicate Ozon offer in product-info response")
            products[offer] = item
    if set(products) != set(offers):
        raise RuntimeError("Ozon product-info did not return the complete requested offer set")

    attr_rows: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        body = post(client, "ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)})
        items = body.get("result") or body.get("items")
        if not isinstance(items, list):
            raise RuntimeError("malformed Ozon attributes response")
        for item in items:
            offer = str(item.get("offer_id") or "")
            if offer in attr_rows:
                raise RuntimeError("duplicate Ozon attribute offer")
            attr_rows[offer] = item
    if set(attr_rows) != set(offers):
        raise RuntimeError("Ozon attributes did not return the complete requested offer set")

    records: list[dict] = []
    for page in range(1, 101):
        body = post(client, "ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        batch = (body.get("result") or {}).get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("malformed Ozon certificate list")
        records.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Ozon certificate pagination exceeded limit")
    if len({str(r.get("certificate_id")) for r in records}) != len(records):
        raise RuntimeError("duplicate Ozon certificate IDs")

    all_numbers = {group: row["Номер/название документа"] for group, offers_by_id in expected.items()
                   for row in offers_by_id.values()}
    doc_matches: dict[str, list[dict]] = {}
    for group, number in all_numbers.items():
        matches = [rec for rec in records if norm(rec.get("certificate_number")) == norm(number)]
        doc_matches[group] = []
        for rec in matches:
            cid = int(rec["certificate_id"])
            bindings = read_ozon_bindings(client, cid)
            clean = {k: v for k, v in rec.items() if k not in {"certificate_file", "file_content"}}
            clean["binding_count_live"] = len(bindings)
            clean["binding_status_counts_live"] = dict(collections.Counter(
                str(b.get("product_status_code") or "") for b in bindings))
            clean["target_bindings_live"] = [{"offer_id": str(b.get("offer_id") or ""),
                                               "product_id": str(b.get("product_id") or ""),
                                               "sku": str(b.get("sku") or ""),
                                               "status": b.get("product_status_code")}
                                              for b in bindings
                                              if str(b.get("offer_id") or "") in offers]
            doc_matches[group].append(clean)

    target_by_group: dict[str, list[dict]] = {}
    live_products = {}
    for group, offer_map in expected.items():
        targets = []
        for offer, assignment in offer_map.items():
            product = products[offer]
            attr_item = attr_rows[offer]
            attrs = attr_item.get("attributes") or []
            brand_values = [str(v.get("value") or "") for a in attrs if str(a.get("id")) == "85"
                            for v in a.get("values") or []]
            tnved_raw = tnved_values(attrs, ozon=True)
            row = {
                "offer_id": offer,
                "assignment_brand": assignment.get("Бренд подтвержденный"),
                "assignment_name": assignment.get("Название товара Ozon"),
                "live_product_id": str(product.get("id") or product.get("product_id") or ""),
                "live_sku": str(product.get("sku") or ""),
                "live_is_archived": product.get("is_archived"),
                "live_product_name": product.get("name"),
                "ozon_brand_values": brand_values,
                "ozon_tnved_values": tnved_raw,
                "ozon_tnved_codes": sorted({re.split(r"\s+-\s+", x, 1)[0].strip()
                                              for x in tnved_raw if x.strip()}),
                "assignment_applicability": assignment.get("Применимость"),
                "assignment_coverage": assignment.get("Статус покрытия артикула"),
                "assignment_local_file": assignment.get("Локальный файл"),
                "assignment_source_url": assignment.get("URL документа"),
            }
            live_products[offer] = row
            targets.append(row)
        target_by_group[group] = targets

    wb_by_offer: dict[str, list[dict]] = {}
    for i, offer in enumerate(offers, 1):
        cards = read_wb_cards(client, offer)
        cleaned = []
        for card in cards:
            docs = card.get("documents") or card.get("docs") or {}
            characteristics = card.get("characteristics") or []
            tcodes = tnved_values(characteristics)
            cleaned.append({
                "vendorCode": str(card.get("vendorCode") or ""),
                "nmID": str(card.get("nmID") or ""),
                "brand": card.get("brand"),
                "title": card.get("title"),
                "tnved_values": tcodes,
                "tnved_codes": sorted({re.split(r"\s+-\s+", x, 1)[0].strip()
                                        for x in tcodes if x.strip()}),
                "documents": [{"type": d.get("type"), "number": d.get("number"),
                               "startDate": d.get("startDate"), "endDate": d.get("endDate"),
                               "verdict": d.get("verdict")}
                              for d in docs.get("items") or []],
                "overallVerdict": docs.get("overallVerdict"),
            })
        wb_by_offer[offer] = cleaned
        # Wildberries' seller content limit is 2 requests per second.
        time.sleep(0.72)
        if i % 50 == 0:
            print(f"WB exact-card reads: {i}/{len(offers)}", flush=True)

    for group, targets in target_by_group.items():
        for target in targets:
            target["wb_exact_cards"] = wb_by_offer[target["offer_id"]]

    group_summaries = {}
    for group, targets in target_by_group.items():
        tnved_counts = collections.Counter(code for t in targets for code in t["ozon_tnved_codes"])
        wb_counts = collections.Counter(len(t["wb_exact_cards"]) for t in targets)
        group_summaries[group] = {
            "assignment_unique_offers": len(expected[group]),
            "ozon_products": len(targets),
            "ozon_archived_count": sum(t["live_is_archived"] is True for t in targets),
            "ozon_identity_missing_count": sum(not t["live_product_id"] or not t["live_sku"] for t in targets),
            "ozon_brand_exact_count": sum([t["assignment_brand"]] == t["ozon_brand_values"] for t in targets),
            "ozon_tnved_counts": dict(tnved_counts),
            "wb_exact_card_count_distribution": dict(wb_counts),
            "wb_unique_exact_cards": sum(len(t["wb_exact_cards"]) for t in targets),
            "matching_ozon_record_count": len(doc_matches[group]),
            "matching_ozon_records": doc_matches[group],
        }

    state = {
        "checked_at_utc": now(),
        "read_only": True,
        "note": "Only read endpoints were called. No marketplace mutation API was called; local PDFs were read only.",
        "assignment_source": str(ASSIGNMENTS),
        "unique_offer_count_across_groups": len(offers),
        "ozon_current_certificate_record_count": len(records),
        "group_summaries": group_summaries,
        "targets_by_group": target_by_group,
        "read_errors": [],
    }
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": state["checked_at_utc"],
                      "unique_offers": len(offers), "groups": {
                          group: {k: v for k, v in summary.items()
                                  if k != "matching_ozon_records"}
                          for group, summary in group_summaries.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
