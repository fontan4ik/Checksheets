"""Poll current Ozon review status for Feron 02773/24 without mutations."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
SOURCE = json.loads((BASE / "feron_02773_live_verification.json").read_text(encoding="utf-8"))
EXECUTION = json.loads((BASE / "feron_02773_ozon_bind_execute_20261013.json").read_text(encoding="utf-8"))
targets = SOURCE["workbook"]["targets"]
expected = {str(x["sku"]): str(x["product_id"]) for x in targets}
client = Client()
info = client.call("ozon", "/v1/product/certificate/info", {
    "certificate_number": SOURCE["certificate"]["canonical_number"],
}).get("result")
if not isinstance(info, dict) or str(info.get("certificate_id")) != str(EXECUTION["certificate_id"]):
    raise RuntimeError("Current Ozon certificate identity differs from the binding execution")
rows = client.ozon_bindings(int(info["certificate_id"]))
by_sku = {}
for row in rows:
    sku = str(row.get("sku") or "")
    if not sku or sku in by_sku:
        raise RuntimeError("Ozon returned missing or duplicate bound SKUs")
    by_sku[sku] = row
status_counts = collections.Counter(str(x.get("product_status_code") or "MISSING") for x in rows)
missing = sorted(set(expected) - set(by_sku))
unexpected = sorted(set(by_sku) - set(expected))
mismatches = [
    {"sku": sku, "expected_product_id": expected[sku],
     "actual_product_id": str(by_sku[sku].get("product_id") or "")}
    for sku in sorted(set(expected) & set(by_sku))
    if expected[sku] != str(by_sku[sku].get("product_id") or "")
]
result = {
    "checked_at_utc": now(),
    "read_only": True,
    "certificate": {"certificate_id": str(info.get("certificate_id")),
                    "number": info.get("certificate_number"),
                    "status": info.get("status_code"),
                    "issue_date": info.get("issue_date"),
                    "expire_date": info.get("expire_date")},
    "target_count": len(expected),
    "binding_count": len(rows),
    "binding_status_counts": dict(status_counts),
    "missing_skus": missing,
    "unexpected_skus": unexpected,
    "product_id_mismatches": mismatches,
    "full_exact_set_bound": len(rows) == len(expected) and not missing and not unexpected and not mismatches,
    "all_bindings_approved": bool(rows) and set(status_counts) == {"approved"},
    "all_bindings_final": bool(rows) and set(status_counts) == {"approved"},
}
save("feron_02773_ozon_status_latest_20261013.json", result)
print(json.dumps(result, ensure_ascii=False, indent=2))
