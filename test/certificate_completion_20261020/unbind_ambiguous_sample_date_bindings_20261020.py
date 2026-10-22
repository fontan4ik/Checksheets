"""Remove only five new Ozon product bindings that fail the sample-date rule.

The documents remain on Ozon. This corrects associations made in this run for
historic product listings whose actual production lots are unknown.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner_module  # noqa: E402
from api_client import Client, now  # noqa: E402

MANIFEST = HERE / "iek_missing_new_docs_manifest_20261020.json"
EXECUTION = HERE / "iek_missing_new_docs_execute_state_20261020.json"
JOURNAL = HERE / "reconciliation_journal.jsonl"
OUT = HERE / "iek_sample_date_binding_correction_20261020.json"
SAMPLE_LIMITS = {
    "ЕАЭС RU С-CN.АЯ46.В.47749/26": "2025-03",
    "ЕАЭС RU С-CN.АЯ46.В.48571/26": "2025-01",
}


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    execution = json.loads(EXECUTION.read_text())
    manifest_by_number = {g["number"]: g for g in manifest["groups"]}
    exec_by_number = {g["number"]: g for g in execution["groups"]}
    client = Client()
    helper = runner_module.Runner(client, manifest, execute=False,
                                  journal=HERE / "correction_verification_only.jsonl",
                                  state=HERE / "correction_verification_only_state.json")
    records = helper.list_certificate_metadata()
    cert_by_id = {str(c.get("certificate_id")): c for c in records}
    audit_pairs = []

    for number, sample_month in SAMPLE_LIMITS.items():
        group = manifest_by_number[number]
        state_row = exec_by_number[number]
        certificate_id = str(state_row["certificate_id"])
        cert = cert_by_id.get(certificate_id)
        if not cert or cert.get("certificate_number") != number or cert.get("status_code") != "approved":
            raise RuntimeError(f"Fresh Ozon document identity/status changed for {number}")
        live_bindings = client.ozon_bindings(certificate_id)
        by_product = {str(b.get("product_id")): b for b in live_bindings}
        for target in group["targets"]:
            first_sale = (target.get("source_first_sale") or "")[:10]
            if not first_sale or first_sale[:7] > sample_month:
                continue
            binding = by_product.get(str(target["product_id"]))
            if not binding or str(binding.get("sku")) != str(target["sku"]):
                raise RuntimeError(f"Expected exact new binding missing/changed: {number}/{target['offer_id']}")
            if binding.get("product_status_code") != "approved":
                raise RuntimeError(f"Will not alter non-approved binding: {number}/{target['offer_id']}")
            audit_pairs.append({
                "number": number, "certificate_id": certificate_id,
                "product_id": str(target["product_id"]), "sku": str(target["sku"]),
                "offer_id": target["offer_id"], "first_sale": first_sale,
                "sample_month": sample_month,
            })

    if len(audit_pairs) != 5:
        raise RuntimeError(f"Expected exactly five ambiguous links; found {len(audit_pairs)}")
    used = set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text().splitlines():
            row = json.loads(line)
            if row.get("key"):
                used.add(row["key"])

    by_cert = {}
    for pair in audit_pairs:
        by_cert.setdefault(pair["certificate_id"], []).append(pair)
    mutation_results = []
    for certificate_id, pairs in by_cert.items():
        key = "ozon:unbind:" + certificate_id + ":" + hashlib.sha256(
            ",".join(sorted(pair["product_id"] for pair in pairs)).encode()).hexdigest()
        if key in used or any("ozon:unbind_product:" + certificate_id + ":" + pair["product_id"] in used for pair in pairs):
            raise RuntimeError(f"Previous unbind outcome exists; reconcile before retry: {certificate_id}")
        with JOURNAL.open("a") as stream:
            for pair in pairs:
                stream.write(json.dumps({"key": "ozon:unbind_product:" + certificate_id + ":" + pair["product_id"],
                                         "phase": "prepared", "at": now()}, ensure_ascii=False) + "\n")
            stream.write(json.dumps({"key": key, "phase": "prepared", "at": now(),
                                     "platform": "ozon", "endpoint": "/v1/product/certificate/unbind"},
                                    ensure_ascii=False) + "\n")
            stream.flush()
        response = client.call("ozon", "/v1/product/certificate/unbind", {
            "certificate_id": int(certificate_id),
            "product_id": [pair["product_id"] for pair in pairs],
        }, mutation=True)
        mutation_results.append({"certificate_id": certificate_id, "response": response,
                                 "targets": pairs})
        with JOURNAL.open("a") as stream:
            stream.write(json.dumps({"key": key, "phase": "response", "at": now(),
                                     "response": response}, ensure_ascii=False) + "\n")
            stream.flush()

    verified = []
    for certificate_id, pairs in by_cert.items():
        after = client.ozon_bindings(certificate_id)
        present = {str(b.get("product_id")) for b in after}
        for pair in pairs:
            verified.append({**pair, "binding_absent_after": pair["product_id"] not in present})

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reason": "Product first-sale precedes explicit tested-sample month; manufacture lot cannot be proven from marketplace listing.",
        "documents_deleted": False,
        "unbound_count": len(verified),
        "verified_absent_count": sum(row["binding_absent_after"] for row in verified),
        "mutations": mutation_results,
        "verification": verified,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "mutations"}, ensure_ascii=False))
    if result["verified_absent_count"] != len(verified):
        raise SystemExit("Some ambiguous bindings remain; inspect live state before any retry.")


if __name__ == "__main__":
    main()
