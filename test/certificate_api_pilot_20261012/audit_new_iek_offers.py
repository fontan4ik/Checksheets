"""Match new Ozon IEK/Generica offers to the current official IEK XML feed.

This is a read-only source audit. A suffix-stripped article is only a candidate
match; the output records the basis so a later document upload still requires
scope/date/PDF validation.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
URL = "https://www.iek.ru/local/cron/xmlapi/file-certificatesPrice.xml"
OUT = BASE / "iek_live_new_offers_docs.json"
SUFFIXES = ("-1", "-2", "-3", "-5", "-10", "-20", "-50")


def variants(offer: str) -> list[tuple[str, str]]:
    values = [(offer, "exact seller article equals IEK Article")]
    for suffix in SUFFIXES:
        if offer.endswith(suffix) and len(offer) > len(suffix):
            values.append((offer[:-len(suffix)], f"candidate base Article after pack suffix {suffix}"))
            break
    return values


class HashingReader:
    def __init__(self, source):
        self.source = source
        self.sha = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size=-1):
        data = self.source.read(size)
        self.sha.update(data)
        self.bytes_read += len(data)
        return data


def child_text(element: ET.Element, name: str) -> str:
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def main() -> None:
    products = json.loads((BASE / "ozon_new_offers_attributes.json").read_text()).get("products") or []
    selected = [p for p in products if p.get("brand") in {"IEK", "Generica"}]
    targets: dict[str, list[dict]] = defaultdict(list)
    for product in selected:
        for article, basis in variants(str(product.get("offer_id") or "")):
            targets[article].append({"offer_id": product["offer_id"], "sku": product["sku"],
                                     "product_id": product["product_id"], "brand": product.get("brand"),
                                     "name": product.get("name"), "model": product.get("model"),
                                     "candidate_basis": basis})

    request = urllib.request.Request(URL, headers={"User-Agent": "Checksheets-Certificate-Audit/1.0",
                                                   "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=180) as response:
        source = HashingReader(response)
        matched: dict[str, list[dict]] = defaultdict(list)
        seen_articles = set()
        total = 0
        for event, element in ET.iterparse(source, events=("end",)):
            if element.tag != "Product":
                continue
            total += 1
            article = child_text(element, "Article")
            if article in targets:
                files = []
                files_node = element.find("Files")
                if files_node is not None:
                    for file_node in files_node.findall("File"):
                        files.append({
                            "url": child_text(file_node, "Link"), "name": child_text(file_node, "PubName"),
                            "type": child_text(file_node, "Type"), "start_date": child_text(file_node, "DateStart"),
                            "end_date": child_text(file_node, "DateEnd"), "number": child_text(file_node, "Number"),
                            "issuer": child_text(file_node, "Issuer"),
                        })
                record = {
                    "article": article, "official_name": child_text(element, "Name"),
                    "category": child_text(element, "CategoryP"), "group": child_text(element, "GroupP"),
                    "subgroup": child_text(element, "SubgroupP"), "documents": files,
                    "matched_offers": targets[article],
                }
                matched[article].append(record)
                seen_articles.add(article)
            element.clear()
            if total % 20000 == 0:
                print(json.dumps({"records_read": total, "matched_articles": len(seen_articles),
                                  "bytes_read": source.bytes_read}), flush=True)
        result = {
            "complete": True, "checked_at": datetime.now(timezone.utc).isoformat(), "source_url": URL,
            "source_last_modified": response.headers.get("Last-Modified"),
            "source_etag": response.headers.get("ETag"), "source_content_length": response.headers.get("Content-Length"),
            "source_bytes_read": source.bytes_read, "source_sha256": source.sha.hexdigest(),
            "xml_product_records": total, "ozon_iek_generica_offers": len(selected),
            "offers_with_exact_article_match": sum(
                1 for p in selected if str(p.get("offer_id")) in matched),
            "offers_with_exact_or_pack_candidate_match": sum(
                1 for p in selected if any(article in matched for article, _ in variants(str(p.get("offer_id") or "")))),
            "unmatched_offers": [p["offer_id"] for p in selected if not any(
                article in matched for article, _ in variants(str(p.get("offer_id") or "")))],
            "matched_articles": list(matched.values()),
        }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({k: result[k] for k in (
        "complete", "source_last_modified", "source_content_length", "source_bytes_read",
        "source_sha256", "xml_product_records", "ozon_iek_generica_offers",
        "offers_with_exact_article_match", "offers_with_exact_or_pack_candidate_match",
    )}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
