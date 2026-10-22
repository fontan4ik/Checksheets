"""Read-only status poll for AlphaCable Ozon certificate and exact bindings."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "alphacable_00103_ozon_status_poll_20261013.json"
CERT_ID = 5649888
NUMBER = "ЕАЭС RU С-RU.АД38.В.00103/25"
TARGETS = [
    {"offer_id": "4237264-1", "product_id": "6503121195", "sku": "5938248994"},
    {"offer_id": "7699117-1", "product_id": "6503121209", "sku": "5938247255"},
    {"offer_id": "3137562-1", "product_id": "6503121299", "sku": "5938248851"},
    {"offer_id": "4269981-1", "product_id": "6503121325", "sku": "5938247495"},
    {"offer_id": "7188787-1", "product_id": "6503121326", "sku": "5938249419"},
    {"offer_id": "8966341-1", "product_id": "6503121361", "sku": "5938247259"},
    {"offer_id": "1743162-1", "product_id": "6503121363", "sku": "5938246904"},
]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402


def main() -> None:
    client = Client()
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(CERT_ID):
        raise RuntimeError("Ozon exact record readback mismatch")
    bindings = client.ozon_bindings(CERT_ID)
    target_by_sku = {x["sku"]: x["product_id"] for x in TARGETS}
    by_sku = collections.defaultdict(list)
    for row in bindings:
        by_sku[str(row.get("sku") or "")].append(row)
    outside = sorted(set(by_sku) - set(target_by_sku))
    duplicates = sorted(x for x, values in by_sku.items() if len(values) != 1)
    missing = sorted(set(target_by_sku) - set(by_sku))
    mismatches = sorted(x for x in set(target_by_sku) & set(by_sku)
                        if str(by_sku[x][0].get("product_id")) != target_by_sku[x])
    statuses = collections.Counter(str(x.get("product_status_code") or "") for x in bindings)
    out = {"checked_at_utc": now(), "certificate_id": CERT_ID, "number": NUMBER,
           "record_info": info, "binding_count": len(bindings), "binding_status_counts": dict(statuses),
           "outside_skus": outside, "duplicates": duplicates, "missing_skus": missing,
           "product_id_mismatches": mismatches,
           "all_exact_target_pairs_present": len(bindings) == 7 and not any((outside, duplicates, missing, mismatches)),
           "all_target_bindings_approved": len(bindings) == 7 and statuses == {"approved": 7},
           "bindings": bindings}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checked_at_utc": out["checked_at_utc"], "record_status": info.get("status_code"),
                      "binding_status_counts": dict(statuses),
                      "all_exact_target_pairs_present": out["all_exact_target_pairs_present"],
                      "all_target_bindings_approved": out["all_target_bindings_approved"],
                      "artifact": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
