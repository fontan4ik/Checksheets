"""Fresh live Ozon readback for Arlight 46569/26 before local cleanup."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.46569/26"
CERT_ID = 5920455
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"
PREFLIGHT = json.loads((HERE / "arlight_46569_preflight_live_20261021.json").read_text())
TARGETS = PREFLIGHT["ozon_targets"]
OUT = HERE / "arlight_46569_ozon_final_readback_20261021.json"
if OUT.exists():
    raise RuntimeError("output_exists")

client = Client()
info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}
bindings = client.ozon_bindings(CERT_ID)
by_product = {str(item.get("product_id")): item for item in bindings}
rows = []
for target in TARGETS:
    binding = by_product.get(str(target["product_id"]))
    rows.append({
        "offer_id": target["offer_id"],
        "product_id": target["product_id"],
        "sku": target["sku"],
        "bound": bool(binding and str(binding.get("sku")) == str(target["sku"])),
        "status": str((binding or {}).get("product_status_code") or ""),
    })
status_counts = collections.Counter(row["status"] for row in rows if row["bound"])
metadata_exact = (
    str(info.get("certificate_id")) == str(CERT_ID)
    and norm_number(info.get("certificate_number")) == norm_number(NUMBER)
    and str(info.get("issue_date", ""))[:10] == ISSUE
    and str(info.get("expire_date", ""))[:10] == EXPIRY
    and info.get("status_code") == "approved"
)
complete = (
    metadata_exact
    and len(TARGETS) == 905
    and len(rows) == 905
    and all(row["bound"] and row["status"] == "approved" for row in rows)
)
result = {
    "checked_at": now(),
    "number": NUMBER,
    "certificate_id": CERT_ID,
    "document_metadata_exact": metadata_exact,
    "certificate_status": info.get("status_code"),
    "issue_date": str(info.get("issue_date", ""))[:10],
    "expiry_date": str(info.get("expire_date", ""))[:10],
    "expected_target_bindings": len(TARGETS),
    "verified_target_bindings": sum(row["bound"] for row in rows),
    "binding_status_counts": dict(status_counts),
    "complete": complete,
    "bindings": rows,
}
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(OUT)
print(json.dumps({key: value for key, value in result.items() if key != "bindings"}, ensure_ascii=False, indent=2))
if not complete:
    raise RuntimeError("ozon_approval_or_bindings_incomplete")
