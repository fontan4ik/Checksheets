"""Fresh read-only status check for pending Ozon documents and exact bindings."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

SOURCE = HERE / "all_found_pending_ozon_recheck_20261021.json"
SUPPLEMENTAL = HERE / "arlight_03451_ozon_execution_20261021.json"
OUT = HERE / "all_found_pending_ozon_recheck_20261021_0853.json"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("fresh_pending_recheck_exists_reconcile_before_retry")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    supplemental = json.loads(SUPPLEMENTAL.read_text(encoding="utf-8"))
    targets = []
    for row in source.get("records") or []:
        targets.append({"certificate_id": int(row["certificate_id"]), "number": row["number"],
                        "expected_bindings": int(row["expected_bindings"]),
                        "expected_bindings_rows": row.get("bindings") or [], "source": "prior_pending_recheck"})
    targets.append({"certificate_id": int(supplemental["certificate_id"]),
                     "number": supplemental["number"], "expected_bindings": 462,
                     "expected_bindings_rows": [], "source": "arlight_03451_followup"})
    if len({x["certificate_id"] for x in targets}) != len(targets):
        raise RuntimeError("duplicate_pending_target_certificate_id")
    client = Client()
    results = []
    for index, target in enumerate(targets, 1):
        info = client.call("ozon", "/v1/product/certificate/info", {
            "certificate_number": target["number"]
        }).get("result") or {}
        bindings = client.ozon_bindings(target["certificate_id"])
        previous_by_id = {str(x.get("product_id")): x for x in target["expected_bindings_rows"]}
        live_by_id = {str(x.get("product_id")): x for x in bindings}
        missing = sorted(set(previous_by_id) - set(live_by_id)) if previous_by_id else []
        extra = sorted(set(live_by_id) - set(previous_by_id)) if previous_by_id else []
        sku_mismatches = sorted(pid for pid, old in previous_by_id.items()
                                if pid in live_by_id and str(old.get("sku")) != str(live_by_id[pid].get("sku")))
        status_counts = collections.Counter(str(x.get("product_status_code") or "unknown") for x in bindings)
        metadata_exact = (str(info.get("certificate_id")) == str(target["certificate_id"])
                          and norm_number(info.get("certificate_number")) == norm_number(target["number"]))
        result = {"certificate_id": target["certificate_id"], "number": target["number"],
                  "source": target["source"], "checked_at": now(),
                  "document_status": info.get("status_code"), "type_code": info.get("type_code"),
                  "accordance_type_code": info.get("accordance_type_code"),
                  "issue_date": info.get("issue_date"), "expire_date": info.get("expire_date"),
                  "metadata_exact": metadata_exact, "expected_bindings": target["expected_bindings"],
                  "read_bindings": len(bindings), "binding_status_counts": dict(status_counts),
                  "identity_reconciliation_available": bool(previous_by_id),
                  "missing_previous_product_ids": missing, "extra_product_ids": extra,
                  "sku_mismatches": sku_mismatches,
                  "exact_previous_binding_set": (not missing and not extra and not sku_mismatches)
                        if previous_by_id else len(bindings) == target["expected_bindings"],
                  "bindings": [{"product_id": str(x.get("product_id") or ""),
                                "sku": str(x.get("sku") or ""),
                                "product_status_code": x.get("product_status_code")}
                               for x in bindings]}
        results.append(result)
        print(json.dumps({"checked": index, "of": len(targets), "number": target["number"],
                          "read_bindings": len(bindings), "binding_status_counts": dict(status_counts)},
                         ensure_ascii=False), flush=True)
    out = {"checked_at": now(), "read_only": True, "previous_targets": len(source.get("records") or []),
           "supplemental_targets": 1, "target_records": len(results), "records": results,
           "mutation_performed": False, "local_files_deleted": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)
    print(json.dumps({"checked_at": out["checked_at"], "target_records": len(results),
                      "binding_edges": sum(x["read_bindings"] for x in results),
                      "all_metadata_exact": all(x["metadata_exact"] for x in results),
                      "all_binding_sets_exact": all(x["exact_previous_binding_set"] for x in results),
                      "mutation_performed": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
