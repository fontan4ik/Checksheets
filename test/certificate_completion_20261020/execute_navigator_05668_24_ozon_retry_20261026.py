#!/usr/bin/env python3
"""Retry a confirmed non-creating Ozon attempt with its documented enum value."""
from __future__ import annotations
import csv, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import execute_navigator_ozon_groups_20261026 as base

ROOT = HERE.parents[1]
OUT = HERE / "navigator_05668_24_ozon_retry_execution_20261026.json"
PREFLIGHT_OUT = HERE / "navigator_05668_24_ozon_preflight_20261026.json"
JOURNAL = HERE / "navigator_pair_ozon_mutation_journal_20261026.jsonl"
NUMBER = "РОСС RU Д-CN.РА01.В.05668/24"

def main():
    if OUT.exists():
        raise RuntimeError("Retry output already exists; reconcile instead of repeating")
    events = [json.loads(x) for x in JOURNAL.read_text(encoding="utf-8").splitlines() if x.strip()]
    prior = [x for x in events if x.get("phase") == "create_response" and x.get("document_number") == NUMBER]
    if len(prior) != 1 or prior[0].get("certificate_id") != "" or prior[0].get("status") != "INCOMPLETE":
        raise RuntimeError("Prior attempt is not proven non-creating; do not retry")
    client = base.Client()
    doc = dict(base.DOCS[1])
    doc["accordance_type"] = "NATIONAL"
    snapshot = json.loads(base.SNAPSHOT.read_text(encoding="utf-8"))
    if not snapshot.get("ozon_products", {}).get("complete") or not snapshot.get("ozon_certificates", {}).get("complete"):
        raise RuntimeError("Incomplete baseline snapshot")
    assignments = list(csv.DictReader(base.ASSIGNMENTS.open(encoding="utf-8-sig", newline="")))
    source_groups = json.loads(base.REPORT.read_text(encoding="utf-8"))["candidate_source_groups"]
    pf = base.preflight(client, doc, assignments, snapshot, source_groups)
    if pf.get("target_count") != 3 or not pf.get("upload_eligible"):
        raise RuntimeError("Fresh preflight did not validate the exact three products")
    matches = [x for x in base.list_certificates(client) if base.norm(x.get("certificate_number")) == base.norm(NUMBER)]
    if matches:
        raise RuntimeError("A certificate record now exists; reconcile it, do not create another")
    PREFLIGHT_OUT.write_text(json.dumps(pf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = base.process(client, doc, pf)
    if result.get("certificate_id") is None or result.get("exact_binding_count") != 3:
        raise RuntimeError("Upload/readback did not prove all three exact bindings")
    final = {"checked_at_utc": base.now(), "retry_reason": "prior API attempt returned INCOMPLETE with certificate_id=null because lowercase accordance_type was invalid", "accordance_type": "NATIONAL", "read_only_preflight": str(PREFLIGHT_OUT), **result, "local_source_deleted": False, "wb_changed": False}
    OUT.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "certificate_id": final["certificate_id"], "record_status": final["record_status"], "targets": final["target_count"], "exact_bindings": final["exact_binding_count"], "binding_status_counts": final["binding_status_counts"], "accordance_type": final["accordance_type_code"]}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
