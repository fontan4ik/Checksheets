"""Submit the reviewed full-card WB document update once, without automatic retry."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from api_client import BASE, Client, now, save

PLAN = BASE / "wb_fullcard_reconciliation_plan.json"
RUN = BASE / "wb_fullcard_reconciliation_execution.json"
UPDATE_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
                 "characteristics", "sizes", "kizMarked")


def main() -> None:
    if RUN.exists():
        raise RuntimeError(f"WB update already attempted; inspect live readback before retry: {RUN}")
    plan = json.loads(PLAN.read_text())
    cards = plan.get("updates") or []
    counts = plan.get("counts") or {}
    if not plan.get("source_live_audit", {}).get("checked_at"):
        raise RuntimeError("Full-card live WB export timestamp missing")
    if len(cards) != counts.get("cards_to_update") or not cards:
        raise RuntimeError("WB plan card count mismatch")
    if len(cards) > 3000:
        raise RuntimeError("WB 3000-card update limit exceeded")
    payloads = []
    original_documents = 0
    added_documents = 0
    for item in cards:
        before = item.get("before") or {}
        payload = item.get("payload") or {}
        if (str(before.get("nmID")) != str(item.get("nmID")) or
            str(payload.get("nmID")) != str(item.get("nmID")) or
            before.get("vendorCode") != item.get("offer_id") or payload.get("vendorCode") != item.get("offer_id")):
            raise RuntimeError(f"WB live-card identity mismatch for {item.get('offer_id')}")
        if not payload.get("sizes") or payload.get("sizes") != before.get("sizes"):
            raise RuntimeError(f"WB size rows are absent or changed for {item.get('offer_id')}")
        if not payload.get("documents") or payload["documents"].get("excludeDocuments") is not False:
            raise RuntimeError(f"WB documents are still excluded for {item.get('offer_id')}")
        for field in UPDATE_FIELDS:
            if field in before and payload.get(field) != before.get(field):
                raise RuntimeError(f"WB full-card field changed in plan: {item.get('offer_id')} {field}")
        old_docs = (before.get("documents") or {}).get("items") or []
        new_docs = payload["documents"].get("items") or []
        if any(doc not in new_docs for doc in old_docs):
            raise RuntimeError(f"Existing WB documents were removed from payload: {item.get('offer_id')}")
        wanted = {(int(d["type"]), str(d["number"])) for d in item.get("additions", [])}
        found = {(int(d.get("type", 0)), str(d.get("number", ""))) for d in new_docs}
        if not wanted or not wanted.issubset(found):
            raise RuntimeError(f"Exact planned WB documents absent from payload: {item.get('offer_id')}")
        if not item.get("ozon_proof"):
            raise RuntimeError(f"Exact approved Ozon proof missing for {item.get('offer_id')}")
        payloads.append(payload)
        original_documents += len(old_docs)
        added_documents += len(item["additions"])

    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 10_000_000:
        raise RuntimeError(f"WB 10 MB request limit exceeded: {len(encoded)}")
    if len(payloads) != 967 or added_documents != 999:
        raise RuntimeError(f"Unexpected reviewed batch size: cards={len(payloads)} docs={added_documents}")
    run = {"started_at": now(), "phase": "prepared", "plan_checked_at": plan["created_at"],
           "wb_live_checked_at": plan["source_live_audit"]["checked_at"],
           "cards": len(payloads), "documents_to_add": added_documents,
           "preserved_existing_document_rows": original_documents,
           "request_bytes": len(encoded), "request_sha256": hashlib.sha256(encoded).hexdigest(),
           "limit_bytes": 10_000_000, "limit_cards": 3000}
    save(RUN.name, run)
    client = Client()
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        run.update({"phase": "uncertain_or_rejected", "error_type": type(exc).__name__, "finished_at": now()})
        save(RUN.name, run)
        raise
    run.update({"response": response, "finished_at": now(),
                "phase": "accepted_waiting_for_wb_sync" if response.get("error") is False else "response_error"})
    save(RUN.name, run)
    if response.get("error") is not False:
        raise RuntimeError("WB update response was not accepted; reconcile state before any retry")
    print(json.dumps({"phase": run["phase"], "cards": run["cards"],
                      "documents_to_add": run["documents_to_add"], "request_bytes": run["request_bytes"],
                      "execution_journal": str(RUN)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
