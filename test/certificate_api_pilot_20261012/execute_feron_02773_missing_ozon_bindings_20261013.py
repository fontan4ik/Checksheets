"""Bind only the two source-verified missing Feron 02773/24 Ozon SKUs, then read back."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "feron_02773_live_verification.json"
OUT = "feron_02773_ozon_bind_execute_20261013.json"
EXPECTED_MISSING_OFFERS = {"41153-1", "41155-1"}

source = json.loads(SOURCE.read_text(encoding="utf-8"))
cert = source["certificate"]
targets = source["workbook"]["targets"]
by_offer = {str(x["offer_id"]): x for x in targets}
if len(by_offer) != 159:
    raise RuntimeError("Expected 159 unique source-verified target offers")
if not EXPECTED_MISSING_OFFERS <= set(by_offer):
    raise RuntimeError("Expected missing offers are absent from the certified source matrix")
for offer in EXPECTED_MISSING_OFFERS:
    row = by_offer[offer]
    if row.get("manual_flag") or row.get("relation_level") != "карточка Feron":
        raise RuntimeError(f"Source-scope proof is insufficient for {offer}")

expected_by_offer = {
    offer: {"product_id": str(row["product_id"]), "sku": str(row["sku"])}
    for offer, row in by_offer.items()
}
expected_by_sku = {v["sku"]: v["product_id"] for v in expected_by_offer.values()}
client = Client()

info = client.call("ozon", "/v1/product/certificate/info", {
    "certificate_number": cert["canonical_number"],
}).get("result")
if (not isinstance(info, dict)
        or str(info.get("certificate_id")) != str(source["ozon"]["certificate_id"])
        or info.get("status_code") != "approved"):
    raise RuntimeError("Current Ozon certificate record is not the expected approved record")

product_info = client.call("ozon", "/v3/product/info/list", {
    "offer_id": sorted(expected_by_offer),
}).get("items")
if not isinstance(product_info, list):
    raise RuntimeError("Ozon product info response omitted items")
live_products = {str(x.get("offer_id") or ""): x for x in product_info}
if len(live_products) != len(product_info) or set(live_products) != set(expected_by_offer):
    raise RuntimeError("Ozon current target offer set is incomplete or duplicated")
for offer, expected in expected_by_offer.items():
    row = live_products[offer]
    if {"product_id": str(row.get("product_id") or row.get("id") or ""),
        "sku": str(row.get("sku") or "")} != expected:
        raise RuntimeError(f"Current Ozon identity mismatch for {offer}")

listed_result = client.call("ozon", "/v3/product/list", {
    "filter": {"product_id": sorted({x["product_id"] for x in expected_by_offer.values()}),
               "visibility": "ALL"},
    "limit": 1000,
    "last_id": "",
}).get("result", {})
listed = listed_result.get("items")
if not isinstance(listed, list) or len(listed) != len(expected_by_offer):
    raise RuntimeError("Current Ozon listing does not contain the full 159-product target set")
listed_by_id = {str(x.get("product_id") or x.get("id") or ""): x for x in listed}
if len(listed_by_id) != len(listed):
    raise RuntimeError("Ozon product listing returned duplicate product IDs")
for offer in EXPECTED_MISSING_OFFERS:
    product_id = expected_by_offer[offer]["product_id"]
    row = listed_by_id.get(product_id)
    if not row or row.get("archived") is not True or row.get("has_fbs_stocks") is not True:
        raise RuntimeError(f"Archived/FBS state changed for {offer}; stop before binding")

before = client.ozon_bindings(int(info["certificate_id"]))
binding_by_sku: dict[str, dict] = {}
for row in before:
    sku = str(row.get("sku") or "")
    if not sku or sku in binding_by_sku:
        raise RuntimeError("Current Ozon bindings contain missing or duplicate SKUs")
    binding_by_sku[sku] = row
missing_skus = sorted(set(expected_by_sku) - set(binding_by_sku))
if set(binding_by_sku) - set(expected_by_sku):
    raise RuntimeError("Current Ozon certificate has unexpected target SKUs")
for sku, row in binding_by_sku.items():
    if expected_by_sku[sku] != str(row.get("product_id") or ""):
        raise RuntimeError(f"Current Ozon binding has a product ID mismatch for SKU {sku}")
if any(row.get("product_status_code") != "approved" for row in before):
    raise RuntimeError("Existing Ozon bindings are not all approved")
missing_offers = sorted(offer for offer, pair in expected_by_offer.items()
                        if pair["sku"] in set(missing_skus))
if set(missing_offers) != EXPECTED_MISSING_OFFERS or len(missing_skus) != 2:
    raise RuntimeError(f"Unexpected missing target set: {missing_offers}")

state = {
    "started_at_utc": now(),
    "certificate_id": str(info["certificate_id"]),
    "certificate_number": info.get("certificate_number"),
    "source_verified_missing_offers": [
        {"offer_id": offer, "product_id": expected_by_offer[offer]["product_id"],
         "sku": expected_by_offer[offer]["sku"], "fsa_scope_relation": by_offer[offer]["relation_level"]}
        for offer in sorted(EXPECTED_MISSING_OFFERS)
    ],
    "bindings_before": len(before),
    "before_status_counts": dict(collections.Counter(
        str(x.get("product_status_code") or "MISSING") for x in before)),
    "mutation": {"endpoint": "/v1/product/certificate/bind", "skus": missing_skus,
                 "attempted": False, "http_or_result": None},
    "bindings_after": None,
    "final_verified": False,
}
save(OUT, state)

try:
    response = client.call("ozon", "/v1/product/certificate/bind", {
        "certificate_id": int(info["certificate_id"]), "skus": missing_skus,
    }, mutation=True)
    state["mutation"] = {"endpoint": "/v1/product/certificate/bind", "skus": missing_skus,
                         "attempted": True, "response": response}
except RuntimeError as exc:
    # No retry: reconcile the live state immediately because the write result may be uncertain.
    state["mutation"] = {"endpoint": "/v1/product/certificate/bind", "skus": missing_skus,
                         "attempted": True, "outcome": "uncertain_or_failed",
                         "error": str(exc)}
save(OUT, state)

after = client.ozon_bindings(int(info["certificate_id"]))
after_by_sku: dict[str, dict] = {}
for row in after:
    sku = str(row.get("sku") or "")
    if not sku or sku in after_by_sku:
        raise RuntimeError("Fresh Ozon readback contains missing or duplicate SKUs")
    after_by_sku[sku] = row
after_status_counts = collections.Counter(
    str(x.get("product_status_code") or "MISSING") for x in after)
missing_after = sorted(set(expected_by_sku) - set(after_by_sku))
unexpected_after = sorted(set(after_by_sku) - set(expected_by_sku))
mismatches_after = [
    {"sku": sku, "expected_product_id": expected_by_sku[sku],
     "actual_product_id": str(after_by_sku[sku].get("product_id") or "")}
    for sku in sorted(set(expected_by_sku) & set(after_by_sku))
    if expected_by_sku[sku] != str(after_by_sku[sku].get("product_id") or "")
]
state["bindings_after"] = {
    "count": len(after),
    "status_counts": dict(after_status_counts),
    "missing_skus": missing_after,
    "unexpected_skus": unexpected_after,
    "product_id_mismatches": mismatches_after,
}
state["finished_at_utc"] = now()
state["final_verified"] = (
    len(after) == len(expected_by_sku) == 159
    and not missing_after and not unexpected_after and not mismatches_after
    and set(after_status_counts) == {"approved"}
)
save(OUT, state)
print(json.dumps(state, ensure_ascii=False, indent=2))
if not state["final_verified"]:
    raise RuntimeError("Fresh Ozon readback did not confirm complete approved coverage")
