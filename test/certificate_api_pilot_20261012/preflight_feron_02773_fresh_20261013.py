"""Fresh read-only Ozon preflight for Feron certificate 02773/24."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "feron_02773_live_verification.json"
OUT = "feron_02773_fresh_preflight_20261013.json"

source = json.loads(SOURCE.read_text(encoding="utf-8"))
cert = source["certificate"]
targets = source["workbook"]["targets"]
if len(targets) != 159 or len({str(x["offer_id"]) for x in targets}) != 159:
    raise RuntimeError("Expected 159 unique source-verified target offers")
expected_by_offer = {
    str(x["offer_id"]): {"product_id": str(x["product_id"]), "sku": str(x["sku"])}
    for x in targets
}
client = Client()

info = client.call("ozon", "/v1/product/certificate/info", {
    "certificate_number": cert["canonical_number"],
}).get("result")
if not isinstance(info, dict):
    raise RuntimeError("Ozon certificate info response omitted result")
if str(info.get("certificate_id")) != str(source["ozon"]["certificate_id"]):
    raise RuntimeError("Ozon certificate ID differs from the previously verified record")

product_info = client.call("ozon", "/v3/product/info/list", {
    "offer_id": sorted(expected_by_offer),
}).get("items")
if not isinstance(product_info, list):
    raise RuntimeError("Ozon product info response omitted items")
live_by_offer: dict[str, dict] = {}
for row in product_info:
    offer = str(row.get("offer_id") or "")
    if not offer or offer in live_by_offer:
        raise RuntimeError("Ozon product info returned a missing or duplicate offer_id")
    live_by_offer[offer] = row
if set(live_by_offer) != set(expected_by_offer):
    raise RuntimeError("Ozon product info did not return the complete target offer set")
pair_errors = []
for offer, expected in expected_by_offer.items():
    row = live_by_offer[offer]
    actual = {"product_id": str(row.get("product_id") or row.get("id") or ""),
              "sku": str(row.get("sku") or "")}
    if actual != expected:
        pair_errors.append({"offer_id": offer, "expected": expected, "actual": actual})
if pair_errors:
    raise RuntimeError(f"Ozon target identities changed: {len(pair_errors)}")

product_ids = sorted({x["product_id"] for x in expected_by_offer.values()})
listing = client.call("ozon", "/v3/product/list", {
    "filter": {"product_id": product_ids, "visibility": "ALL"},
    "limit": 1000,
    "last_id": "",
}).get("result", {})
listed = listing.get("items")
if not isinstance(listed, list):
    raise RuntimeError("Ozon product list response omitted items")
listed_by_id = {str(x.get("product_id") or x.get("id") or ""): x for x in listed}
if len(listed_by_id) != len(listed) or set(listed_by_id) != set(product_ids):
    raise RuntimeError("Ozon product list did not return every unique target product exactly once")

bindings = client.ozon_bindings(int(info["certificate_id"]))
binding_by_sku: dict[str, dict] = {}
for row in bindings:
    sku = str(row.get("sku") or "")
    if not sku or sku in binding_by_sku:
        raise RuntimeError("Ozon binding list returned a missing or duplicate SKU")
    binding_by_sku[sku] = row
expected_by_sku = {value["sku"]: value["product_id"] for value in expected_by_offer.values()}
missing = sorted(set(expected_by_sku) - set(binding_by_sku))
unexpected = sorted(set(binding_by_sku) - set(expected_by_sku))
id_mismatches = [
    {"sku": sku, "expected_product_id": expected_by_sku[sku],
     "actual_product_id": str(binding_by_sku[sku].get("product_id") or "")}
    for sku in sorted(set(expected_by_sku) & set(binding_by_sku))
    if expected_by_sku[sku] != str(binding_by_sku[sku].get("product_id") or "")
]
status_counts = collections.Counter(str(x.get("product_status_code") or "MISSING") for x in bindings)

result = {
    "checked_at_utc": now(),
    "read_only": True,
    "certificate": {
        "number": info.get("certificate_number"),
        "certificate_id": str(info.get("certificate_id")),
        "status": info.get("status_code"),
        "issue_date": info.get("issue_date"),
        "expire_date": info.get("expire_date"),
        "matches_prior_record_id": str(info.get("certificate_id")) == str(source["ozon"]["certificate_id"]),
    },
    "targets": {"count": len(targets), "current_offer_product_sku_pairs_match": True},
    "ozon_listing": {
        "count": len(listed),
        "archived_count": sum(x.get("archived") is True for x in listed),
        "active_count": sum(x.get("archived") is False for x in listed),
        "archived_target_offers": sorted(
            offer for offer, pair in expected_by_offer.items()
            if listed_by_id[pair["product_id"]].get("archived") is True
        ),
        "fbs_stock_target_offers": sorted(
            offer for offer, pair in expected_by_offer.items()
            if listed_by_id[pair["product_id"]].get("has_fbs_stocks") is True
        ),
        "fbo_stock_target_offers": sorted(
            offer for offer, pair in expected_by_offer.items()
            if listed_by_id[pair["product_id"]].get("has_fbo_stocks") is True
        ),
    },
    "bindings": {
        "count": len(bindings),
        "status_counts": dict(status_counts),
        "missing_skus": missing,
        "unexpected_skus": unexpected,
        "product_id_mismatches": id_mismatches,
        "all_current_bindings_approved": bool(bindings) and set(status_counts) == {"approved"},
        "missing_offer_ids": sorted(
            offer for offer, pair in expected_by_offer.items() if pair["sku"] in set(missing)
        ),
    },
}
result["safe_to_bind_missing_only"] = (
    result["certificate"]["status"] == "approved"
    and result["certificate"]["matches_prior_record_id"]
    and result["targets"]["current_offer_product_sku_pairs_match"]
    and len(listed) == len(targets)
    and not unexpected and not id_mismatches
    and result["bindings"]["all_current_bindings_approved"]
    and set(missing_offer_ids := result["bindings"]["missing_offer_ids"]) <= {"41153-1", "41155-1"}
)
save(OUT, result)
print(json.dumps(result, ensure_ascii=False, indent=2))
