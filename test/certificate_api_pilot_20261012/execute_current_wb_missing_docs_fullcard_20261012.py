"""Submit one reviewed WB full-card update; never retry an uncertain mutation."""
from __future__ import annotations

import hashlib
import argparse
import json
from collections import Counter
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
PLAN = BASE / "wb_ozon_reconciliation_fullcard_plan_20261012.json"
RUN_NAME = "wb_ozon_reconciliation_fullcard_execution_20261012.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', default=PLAN.name)
    parser.add_argument('--run-name', default=RUN_NAME)
    parser.add_argument('--chunk-size', type=int, default=3000)
    args = parser.parse_args()
    plan_path = BASE / args.plan
    run_name = args.run_name
    run_path = BASE / run_name
    if run_path.exists():
        raise RuntimeError("This update already has a run marker; reconcile live state before any retry")
    plan = json.loads(plan_path.read_text())
    updates = plan.get("updates") or []
    payloads = [row["payload"] for row in updates]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    counts = plan.get("counts") or {}
    digest = hashlib.sha256(encoded).hexdigest()
    if not updates or len(updates) != counts.get("cards_to_update"):
        raise RuntimeError("Reviewed WB plan is empty or its card count changed")
    if len(encoded) != counts.get("request_bytes") or digest != counts.get("request_sha256"):
        raise RuntimeError("WB payload changed after review")
    if len(updates) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError("WB payload exceeds card-count or request-size limits")
    if args.chunk_size < 1 or args.chunk_size > 1000:
        raise RuntimeError("WB chunk size must be between 1 and 1000 cards")
    for row in updates:
        before, payload = row.get("before") or {}, row.get("payload") or {}
        if (str(before.get("nmID")) != str(row.get("nmID"))
                or str(payload.get("nmID")) != str(row.get("nmID"))
                or before.get("vendorCode") != row.get("offer_id")
                or payload.get("vendorCode") != row.get("offer_id")
                or payload.get("sizes") != before.get("sizes")
                or payload.get("documents", {}).get("excludeDocuments") is not False):
            raise RuntimeError(f"WB card identity, sizes, or document inclusion changed: {row.get('offer_id')}")
        old_docs = (before.get("documents") or {}).get("items") or []
        payload_docs = payload.get("documents", {}).get("items") or []
        doc_key = lambda x: (int(x.get("type", 0)), str(x.get("number", "")),
                             str(x.get("startDate", ""))[:10], str(x.get("endDate", ""))[:10])
        old_keys = Counter(doc_key(x) for x in old_docs)
        new_keys = Counter(doc_key(x) for x in payload_docs)
        if any(new_keys[key] < amount for key, amount in old_keys.items()):
            raise RuntimeError(f"A pre-existing WB document would be removed: {row.get('offer_id')}")
        if not row.get("ozon_proof"):
            raise RuntimeError(f"Exact Ozon proof missing: {row.get('offer_id')}")

    run = {"started_at": now(), "state": "prepared", "cards": len(updates),
           "documents": sum(len(x.get("additions") or []) for x in updates),
           "request_bytes": len(encoded), "request_sha256": digest,
           "plan_created_at": plan.get("created_at"),
           "ozon_snapshot_checked_at": plan.get("ozon_products_checked_at"),
           "wb_full_cards_checked_at": plan.get("wb_full_cards_checked_at"),
           "chunk_size": args.chunk_size, "chunks": []}
    save(run_name, run)
    client = Client()
    for start in range(0, len(updates), args.chunk_size):
        chunk = updates[start:start + args.chunk_size]
        chunk_payloads = [row["payload"] for row in chunk]
        chunk_bytes = json.dumps(chunk_payloads, ensure_ascii=False, separators=(",", ":")).encode()
        entry = {"index": len(run["chunks"]) + 1, "cards": len(chunk),
                 "documents": sum(len(row.get("additions") or []) for row in chunk),
                 "request_bytes": len(chunk_bytes), "request_sha256": hashlib.sha256(chunk_bytes).hexdigest(),
                 "offers": [row["offer_id"] for row in chunk], "phase": "prepared", "prepared_at": now()}
        run["chunks"].append(entry)
        save(run_name, run)
        try:
            response = client.call("wb", "/content/v2/cards/update", chunk_payloads, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain_or_rejected", "error_type": type(exc).__name__, "finished_at": now()})
            run.update({"state": "uncertain_or_rejected", "finished_at": now()})
            save(run_name, run)
            raise
        entry.update({"response": response,
                      "phase": "accepted" if response.get("error") is False else "response_error",
                      "finished_at": now()})
        save(run_name, run)
        if response.get("error") is not False:
            run.update({"state": "response_error_stop", "finished_at": now()})
            save(run_name, run)
            raise RuntimeError("WB returned an error for this chunk; reconcile its live state before any retry")
    run.update({"finished_at": now(), "state": "accepted_waiting_for_wb_sync"})
    save(run_name, run)
    print(json.dumps({k: run[k] for k in ("state", "cards", "documents", "request_bytes", "request_sha256",
                                          "chunk_size", "chunks", "finished_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
