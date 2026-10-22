"""Attach the newly Ozon-approved IEK/ITK sources to exact WB cards.

Dry-run by default. A write requires a fresh approved Ozon binding, exact WB
vendorCode/product brand/TN VED scope, no existing type/date conflict, and a
unique live WB card. Every update is read back; WB document review stays pending.
No local PDFs are deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner_module  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    OZON_TO_WB_TYPE, comparable_card, copy_documents, doc_key,
    norm_number, wb_datetime,
)
merge_wb = runner_module.merge_wb
wb_scope_error = runner_module.wb_scope_error

MANIFEST = HERE / "iek_remaining_official_docs_manifest_20261020.json"
OZON_READBACK = HERE / "iek_remaining_official_docs_live_readback_20261020.json"
JOURNAL = HERE / "reconciliation_journal.jsonl"
STATE = HERE / "iek_remaining_official_docs_wb_state_20261020.json"


def exact_ozon_proof() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    readback = json.loads(OZON_READBACK.read_text())
    if readback.get("read_only") is not True or readback.get("documents_visible") != len(manifest["groups"]):
        raise RuntimeError("Ozon readback is incomplete")
    if readback.get("verified_binding_edges") != manifest["candidate_count"]:
        raise RuntimeError("Not all Ozon source bindings are visible")
    for group_result in readback.get("results", []):
        if group_result.get("document_status") != "approved" or group_result.get("exact_bindings") != group_result.get("expected_targets"):
            raise RuntimeError(f"Ozon document/binding is not fully approved: {group_result.get('number')}")
        if set(group_result.get("target_status_counts", {})) != {"approved"}:
            raise RuntimeError(f"Ozon target binding is not approved: {group_result.get('number')}")
    return manifest


def journal_keys() -> set[str]:
    keys = set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text().splitlines():
            row = json.loads(line)
            if row.get("key"):
                keys.add(row["key"])
    return keys


def wanted(group: dict) -> dict:
    return {
        "type": OZON_TO_WB_TYPE[group["type_code"]],
        "number": group["number"],
        "startDate": wb_datetime(group["issue_date"]),
        "endDate": wb_datetime(group["expire_date"]),
        "isEndless": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = exact_ozon_proof()
    client = Client()
    helper = runner_module.Runner(client, manifest, execute=args.execute,
                                  journal=JOURNAL, state=STATE)
    errors = helper.error_offers()
    keys = journal_keys()
    counts = Counter()
    planned = []
    checks = []

    for group in manifest["groups"]:
        doc = wanted(group)
        for target in group["targets"]:
            offer = target["offer_id"]
            if offer in errors:
                checks.append({"offer_id": offer, "number": group["number"], "result": "skipped_wb_error_list"})
                counts["skipped_wb_error_list"] += 1
                continue
            cards = client.wb_cards(offer)
            exact = [card for card in cards if card.get("vendorCode") == offer]
            if len(exact) != 1:
                label = "wb_card_missing" if not exact else "wb_card_duplicate"
                checks.append({"offer_id": offer, "number": group["number"], "result": label, "matches": len(exact)})
                counts[label] += 1
                continue
            card = exact[0]
            error = wb_scope_error(card, group, target)
            if error:
                checks.append({"offer_id": offer, "number": group["number"], "result": error, "nmID": card.get("nmID")})
                counts[error] += 1
                continue
            existing = [x for x in copy_documents(card) if norm_number(x.get("number")) == norm_number(doc["number"])]
            if existing:
                same = all(doc_key(x) == doc_key(doc) and
                           str(x.get("startDate", ""))[:10] == doc["startDate"][:10] and
                           str(x.get("endDate", ""))[:10] == doc["endDate"][:10]
                           for x in existing)
                label = "already_exact" if same else "existing_type_or_date_conflict"
                checks.append({"offer_id": offer, "number": group["number"], "result": label, "nmID": card.get("nmID")})
                counts[label] += 1
                continue
            payload = merge_wb(card, [doc])
            if payload is None:
                checks.append({"offer_id": offer, "number": group["number"], "result": "already_exact", "nmID": card.get("nmID")})
                counts["already_exact"] += 1
                continue
            card_key = "wb:" + str(card["nmID"]) + ":" + str(doc_key(doc))
            if card_key in keys:
                # A prior prepared/response entry may represent an uncertain
                # write. Do not replay it; retain it for live reconciliation.
                checks.append({"offer_id": offer, "number": group["number"], "result": "previous_mutation_reconcile_only", "nmID": card.get("nmID")})
                counts["previous_mutation_reconcile_only"] += 1
                continue
            planned.append({"offer_id": offer, "number": group["number"], "nmID": card["nmID"],
                            "brand": target["brand"], "payload": payload, "document": doc,
                            "before": card, "key": card_key})
            counts["planned"] += 1

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "execute": args.execute,
        "ozon_evidence": str(OZON_READBACK),
        "manifest": str(MANIFEST),
        "target_edges": manifest["candidate_count"],
        "preflight_counts": dict(counts),
        "checks": checks,
        "wb_review_left_pending": True,
        "local_files_deleted": False,
    }
    if not args.execute:
        STATE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "checks"}, ensure_ascii=False))
        return

    batches = []
    batch = []
    size = 0
    for row in planned:
        payload_size = len(json.dumps(row["payload"], ensure_ascii=False).encode())
        if payload_size > 9_500_000:
            counts["skipped_wb_payload_too_large"] += 1
            continue
        if batch and (len(batch) >= 100 or size + payload_size > 9_500_000):
            batches.append(batch)
            batch, size = [], 0
        batch.append(row)
        size += payload_size
    if batch:
        batches.append(batch)

    submitted = []
    for batch_no, rows in enumerate(batches, 1):
        # Re-read every card immediately before the write and rebuild its
        # merged payload, so changes since preflight are preserved.
        fresh_rows = []
        for row in rows:
            fresh = client.wb_cards(row["offer_id"])
            if len(fresh) != 1 or fresh[0].get("nmID") != row["nmID"]:
                checks.append({"offer_id": row["offer_id"], "number": row["number"], "result": "identity_changed_before_write"})
                counts["identity_changed_before_write"] += 1
                continue
            payload = merge_wb(fresh[0], [row["document"]])
            if payload is None:
                checks.append({"offer_id": row["offer_id"], "number": row["number"], "result": "already_exact_before_write"})
                counts["already_exact"] += 1
                continue
            error = wb_scope_error(fresh[0], next(g for g in manifest["groups"] if g["number"] == row["number"]),
                                   next(t for g in manifest["groups"] if g["number"] == row["number"] for t in g["targets"] if t["offer_id"] == row["offer_id"]))
            if error:
                checks.append({"offer_id": row["offer_id"], "number": row["number"], "result": error})
                counts[error] += 1
                continue
            fresh_rows.append({**row, "payload": payload, "before": fresh[0]})
        if not fresh_rows:
            continue
        with JOURNAL.open("a") as stream:
            for row in fresh_rows:
                keys.add(row["key"])
                stream.write(json.dumps({"key": row["key"], "phase": "prepared", "at": now(),
                                         "platform": "wb", "endpoint": "/content/v2/cards/update"}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        payload = [row["payload"] for row in fresh_rows]
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        except Exception as exc:
            result.setdefault("mutation_errors", []).append({"batch": batch_no, "error_type": type(exc).__name__, "outcome": "reconcile_before_retry"})
            for row in fresh_rows:
                checks.append({"offer_id": row["offer_id"], "number": row["number"], "result": "mutation_uncertain"})
                counts["mutation_uncertain"] += 1
            continue
        if response.get("error") is not False:
            result.setdefault("mutation_errors", []).append({"batch": batch_no, "response_error": response.get("error"), "result": response})
            for row in fresh_rows:
                checks.append({"offer_id": row["offer_id"], "number": row["number"], "result": "mutation_rejected"})
                counts["mutation_rejected"] += 1
            continue
        submitted.extend(fresh_rows)
        # Exact targeted readback for each accepted card; keep review pending.
        for row in fresh_rows:
            fresh = client.wb_cards(row["offer_id"])
            exact = [card for card in fresh if card.get("vendorCode") == row["offer_id"] and card.get("nmID") == row["nmID"]]
            visible = len(exact) == 1 and merge_wb(exact[0], [row["document"]]) is None
            prior = {(doc_key(d), str(d.get("startDate", ""))[:10], str(d.get("endDate", ""))[:10]) for d in copy_documents(row["before"])}
            after = {(doc_key(d), str(d.get("startDate", ""))[:10], str(d.get("endDate", ""))[:10]) for d in copy_documents(exact[0])} if len(exact) == 1 else set()
            preserved = prior <= after
            unrelated_preserved = len(exact) == 1 and comparable_card(exact[0]) == comparable_card(row["before"])
            verdict = "visible_review_left_pending" if visible and preserved and unrelated_preserved else "readback_needs_reconciliation"
            checks.append({"offer_id": row["offer_id"], "number": row["number"], "nmID": row["nmID"],
                           "result": verdict, "expected_doc_visible": visible,
                           "prior_docs_preserved": preserved, "unrelated_fields_preserved": unrelated_preserved,
                           "documents": copy_documents(exact[0]) if len(exact) == 1 else []})
            counts[verdict] += 1
        result["batches"] = result.get("batches", []) + [{"batch": batch_no, "marker": marker, "cards": len(fresh_rows), "accepted": True}]

    result["submitted_cards"] = len(submitted)
    result["final_counts"] = dict(counts)
    result["checks"] = checks
    result["wb_review_left_pending"] = True
    STATE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
