"""Fresh read-only verification for the 8 new IEK Ozon documents."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner_module  # noqa: E402
from api_client import Client  # noqa: E402

STATE = HERE / "iek_missing_new_docs_execute_state_20261020.json"
MANIFEST = HERE / "iek_missing_new_docs_manifest_20261020.json"
OUT = HERE / "iek_missing_new_docs_live_readback_20261020.json"


def main() -> None:
    state = json.loads(STATE.read_text())
    manifest = json.loads(MANIFEST.read_text())
    execution_by_number = {group["number"]: group for group in state["groups"]}
    client = Client()
    helper = runner_module.Runner(client, manifest, execute=False,
                                  journal=HERE / "verification_only.jsonl",
                                  state=HERE / "verification_only_state.json")
    certs = helper.list_certificate_metadata()
    cert_by_id = {str(cert.get("certificate_id")): cert for cert in certs}
    results = []
    binding_status_counts = Counter()
    product_ids_seen: set[str] = set()

    for group in manifest["groups"]:
        row = execution_by_number.get(group["number"])
        if not row:
            raise RuntimeError("Execution state missing a certificate ID")
        cert = cert_by_id.get(str(row["certificate_id"]))
        if not cert:
            results.append({"number": group["number"], "certificate_id": row["certificate_id"],
                            "record_visible": False, "expected_targets": len(group["targets"]),
                            "verified_bindings": []})
            continue
        bindings = client.ozon_bindings(cert["certificate_id"])
        by_pid = {str(binding.get("product_id")): binding for binding in bindings}
        expected = []
        for target in group["targets"]:
            binding = by_pid.get(str(target["product_id"]))
            exact = bool(binding and str(binding.get("sku")) == str(target["sku"]))
            if exact:
                product_ids_seen.add(str(target["product_id"]))
                binding_status_counts[str(binding.get("product_status_code") or "unknown")] += 1
            expected.append({
                "offer_id": target["offer_id"], "product_id": target["product_id"],
                "sku": target["sku"], "exact_binding_visible": exact,
                "product_status_code": binding.get("product_status_code") if exact else None,
            })
        results.append({
            "number": group["number"], "certificate_id": str(cert["certificate_id"]),
            "record_visible": True, "type_code": cert.get("type_code"),
            "accordance_type_code": cert.get("accordance_type_code"),
            "status_code": cert.get("status_code"),
            "issue_date": cert.get("issue_date"), "expire_date": cert.get("expire_date"),
            "binding_count": len(bindings), "expected_targets": len(group["targets"]),
            "verified_binding_count": sum(x["exact_binding_visible"] for x in expected),
            "verified_bindings": expected,
        })

    output = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "certificates_read": len(certs),
        "documents_expected": len(manifest["groups"]),
        "documents_visible": sum(bool(result.get("record_visible")) for result in results),
        "expected_binding_edges": sum(len(group["targets"]) for group in manifest["groups"]),
        "verified_binding_edges": sum(result.get("verified_binding_count", 0) for result in results),
        "unique_product_ids_with_new_binding": len(product_ids_seen),
        "binding_product_status_counts": dict(binding_status_counts),
        "results": results,
        "local_files_deleted": False,
        "wb_review_left_pending": True,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in output.items() if key != "results"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
