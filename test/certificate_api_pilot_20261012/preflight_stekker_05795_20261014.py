"""Read-only live reconciliation for Stekker certificate 05795/22.

Uses the existing authenticated marketplace session but deliberately bypasses
Client.call(), which logs full API response bodies to api_calls.jsonl.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from api_client import BASE, ROOT, Client, digest

DOC_NUMBER = "ЕАЭС RU C-CN.АБ53.В.05795/22"
SOURCE_REL = Path("output_to_user/certificates/group_1/documents/stekker/960606eb9021386ae1d5e24c.jpg")
MASTER = ROOT / "output_to_user/certificates/document_catalog_master.csv"
OUT = BASE / "stekker_05795_live_preflight_20261014.json"


def post(client: Client, platform: str, path: str, payload: dict) -> dict:
    host, headers = (("https://api-seller.ozon.ru", client.ozon_headers)
                     if platform == "ozon" else
                     ("https://content-api.wildberries.ru", client.wb_headers))
    for attempt in range(5):
        response = client.http.post(host + path, json=payload, headers=headers,
                                    timeout=(15, 120))
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(min(2 ** (attempt + 1), 16))
            continue
        response.raise_for_status()
        time.sleep(0.25 if platform == "ozon" else 0.45)
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"Malformed {platform} response for {path}")
        return body
    raise RuntimeError(f"Read retry limit reached for {platform} {path}")


def read_offers() -> tuple[list[str], dict]:
    rows = []
    with MASTER.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("SHA256", "").lower() == "57a0c318989769d7f98cd66177269ec2d84b71fa7575f682d3b5dc0a62b7c608":
                rows.append(row)
    if len(rows) != 1:
        raise RuntimeError(f"Expected one exact source mapping row, found {len(rows)}")
    row = rows[0]
    offers = sorted(set(x.strip() for x in row["Артикулы"].split(";") if x.strip()))
    if len(offers) != int(row["Связанных артикулов"]) or len(offers) != 55:
        raise RuntimeError("The source mapping does not contain exactly 55 unique offers")
    source = ROOT / SOURCE_REL
    if not source.is_file() or source.is_symlink() or digest(source) != row["SHA256"]:
        raise RuntimeError("Source certificate file is missing or its SHA-256 changed")
    return offers, {"row": row, "source_file": str(source), "source_sha256": digest(source),
                    "source_bytes": source.stat().st_size}


def read_ozon_products(client: Client, offers: list[str]) -> list[dict]:
    body = post(client, "ozon", "/v3/product/info/list", {"offer_id": offers})
    rows = body.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("Ozon product info omitted items")
    by_offer = {str(x.get("offer_id")): x for x in rows}
    if len(by_offer) != len(rows) or set(by_offer) != set(offers):
        raise RuntimeError(f"Ozon product response mismatch ({len(rows)} rows for {len(offers)} offers)")
    result = []
    for offer in offers:
        item = by_offer[offer]
        attrs = []
        for attr in item.get("attributes") or []:
            vals = [str(v.get("value")) for v in attr.get("values") or [] if v.get("value") not in (None, "")]
            if vals:
                attrs.append({"id": attr.get("id"), "values": vals})
        result.append({"offer_id": offer, "product_id": str(item.get("id") or item.get("product_id") or ""),
                       "sku": str(item.get("sku") or ""), "name": item.get("name"),
                       "archived": item.get("is_archived"), "attributes": attrs})
    return result


def read_ozon_attributes(client: Client, offers: list[str], products: list[dict]) -> None:
    body = post(client, "ozon", "/v4/product/info/attributes",
                {"filter": {"offer_id": offers}, "limit": len(offers)})
    rows = body.get("result")
    if not isinstance(rows, list) or len(rows) != len(offers):
        raise RuntimeError("Ozon attribute response did not exactly cover the target offers")
    expected = {x["offer_id"]: x["product_id"] for x in products}
    by_offer = {}
    for row in rows:
        offer = str(row.get("offer_id") or "")
        pid = str(row.get("id") or row.get("product_id") or "")
        if offer not in expected or offer in by_offer or pid != expected[offer]:
            raise RuntimeError("Ozon attribute offer/product identity mismatch")
        attr_values = {}
        for attr in row.get("attributes") or []:
            values = [str(v.get("value")) for v in attr.get("values") or []
                      if v.get("value") not in (None, "")]
            attr_values[str(attr.get("id"))] = values
        by_offer[offer] = attr_values
    if set(by_offer) != set(offers):
        raise RuntimeError("Ozon attribute offer set differs from the target set")
    for product in products:
        attr = by_offer[product["offer_id"]]
        product["brand_values"] = attr.get("85", [])
        product["tnved_values"] = attr.get("22232", [])


def read_ozon_certificates(client: Client) -> list[dict]:
    rows = []
    page = 1
    page_count = None
    while page_count is None or page <= page_count:
        result = post(client, "ozon", "/v1/product/certificate/list",
                      {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list omitted certificates")
        rows.extend(batch)
        page_count = int(result.get("page_count") or page)
        page += 1
    ids = [str(x.get("certificate_id")) for x in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate Ozon certificate IDs in list")
    return rows


def read_wb_cards(client: Client, offer: str) -> list[dict]:
    cards = []
    cursor = {"limit": 100}
    seen = set()
    while True:
        body = post(client, "wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer}}})
        batch = body.get("cards")
        if not isinstance(batch, list):
            raise RuntimeError(f"WB response omitted cards for {offer}")
        cards.extend(x for x in batch if x.get("vendorCode") == offer)
        returned = body.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError(f"WB page count mismatch for {offer}")
        if len(batch) < 100:
            return cards
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError(f"WB cursor incomplete/repeated for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}


def main() -> None:
    offers, source = read_offers()
    client = Client()
    products = read_ozon_products(client, offers)
    read_ozon_attributes(client, offers, products)
    certificates = read_ozon_certificates(client)
    matches = [x for x in certificates if re.sub(r"[^0-9]", "", str(x.get("certificate_number", "")))
               .endswith("0579522")]
    wb = []
    for offer in offers:
        cards = read_wb_cards(client, offer)
        wb.append({"offer_id": offer, "cards": cards})
    output = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "source": source,
        "offers": offers,
        "ozon_products": products,
        "ozon_certificate_number_matches": matches,
        "wb_cards_by_offer": wb,
    }
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    temp.replace(OUT)
    print(json.dumps({
        "checked_at_utc": output["checked_at_utc"],
        "offers": len(offers),
        "ozon_products": len(products),
        "ozon_archived": sum(bool(x["archived"]) for x in products),
        "ozon_without_sku": sum(not x["sku"] or x["sku"] == "0" for x in products),
        "ozon_exact_number_matches": len(matches),
        "wb_offers_with_one_card": sum(len(x["cards"]) == 1 for x in wb),
        "wb_offers_without_card": sum(len(x["cards"]) == 0 for x in wb),
        "wb_offers_with_duplicate_cards": sum(len(x["cards"]) > 1 for x in wb),
        "wb_total_target_cards": sum(len(x["cards"]) for x in wb),
        "output": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
