#!/usr/bin/env python3
"""Add Arlight 52132/25 only to fresh, exact WB cards in declared TNVED scope."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number,
)
from apply_arlight_52132_wb_20261020 import current_catalog, code_values  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
RECORD_ID = 5920271
ISSUE = "2025-10-22"
EXPIRY = "2030-10-20"
ALLOWED_TNVED = {"9405110013", "9405110033", "9405110039", "9405420012", "9405420032", "9405420039"}
PREFLIGHT = HERE / "arlight_52132_uncovered_preflight_20261022.json"
STATE = HERE / "arlight_52132_wb_uncovered_execution_20261022.json"
BEFORE = HERE / "arlight_52132_wb_uncovered_before_20261022.json"
AFTER = HERE / "arlight_52132_wb_uncovered_readback_20261022.json"
JOURNAL = HERE / "arlight_52132_wb_uncovered_journal_20261022.jsonl"


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def target_doc_rows(card: dict) -> list[dict]:
    docs = ((card.get("documents") or {}).get("items") or [])
    return [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]


def is_exact_document(doc: dict) -> bool:
    return (str(doc.get("type")) == "2"
            and str(doc.get("startDate", ""))[:10] == ISSUE
            and str(doc.get("endDate", ""))[:10] == EXPIRY
            and str(doc.get("isEndless", "false")).lower() not in {"true", "1"})


def main() -> None:
    for path in (STATE, BEFORE, AFTER, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_before_retry:" + path.name)
    pre = json.loads(PREFLIGHT.read_text())
    if pre.get("read_only") is not True or pre.get("number") != NUMBER:
        raise RuntimeError("preflight_identity_invalid")
    if pre.get("ozon_document_current_and_approved") is not True:
        raise RuntimeError("existing_ozon_document_not_current_approved")
    if pre.get("ozon_eligible_targets") != 0 or pre.get("wb_safe_targets") != 396:
        raise RuntimeError("preflight_scope_counts_changed")
    desired = {"type": 2, "number": NUMBER, "startDate": f"{ISSUE}T00:00:00Z",
               "endDate": f"{EXPIRY}T00:00:00Z", "isEndless": False}
    targets = {x["offer_id"]: x for x in pre["wb_targets"] if x.get("safe_for_update") is True}
    if len(targets) != 396:
        raise RuntimeError("preflight_wb_targets_not_unique")

    client = Client()
    cards_by_offer, pages, catalog_rows = current_catalog(client, set(targets))
    updates = []
    already_exact = []
    excluded = []
    before = {}
    evidence = collections.Counter()
    for offer, prior in sorted(targets.items()):
        rows = cards_by_offer.get(offer, [])
        if len(rows) != 1:
            excluded.append({"offer_id": offer, "reason": "fresh_card_missing_or_duplicate"})
            continue
        card = rows[0]
        codes = sorted(set(code_values(card)))
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(prior.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "arlight"):
            excluded.append({"offer_id": offer, "reason": "fresh_card_identity_changed"})
            continue
        if len(codes) != 1 or codes[0] not in ALLOWED_TNVED:
            excluded.append({"offer_id": offer, "reason": "fresh_wb_tnved_out_of_declared_scope", "tnved": codes})
            continue
        existing = target_doc_rows(card)
        if existing:
            if len(existing) == 1 and is_exact_document(existing[0]):
                already_exact.append(offer)
                continue
            excluded.append({"offer_id": offer, "reason": "same_number_metadata_conflict"})
            continue
        payload = merge_wb(card, [desired])
        if payload is None:
            already_exact.append(offer)
            continue
        evidence[codes[0]] += 1
        before[offer] = card
        updates.append({"offer_id": offer, "nmID": str(card["nmID"]), "tnved": codes[0], "payload": payload})

    if excluded:
        raise RuntimeError("fresh_prewrite_exclusions_reconcile_before_mutation:" + str(len(excluded)))
    save(BEFORE, {"checked_at_utc": now(), "read_only": True, "pages": pages,
                  "catalog_rows": catalog_rows, "cards": before})
    state = {
        "started_at_utc": now(), "number": NUMBER, "ozon_certificate_id": RECORD_ID,
        "ozon_write_skipped_due_to_tnved_mismatch": True,
        "ozon_live_tnved_code": "9405190039", "declared_tnved_codes": sorted(ALLOWED_TNVED),
        "wb_targets_preflight": 396, "wb_updates_planned": len(updates),
        "wb_already_exact": len(already_exact), "wb_scope_tnved_counts": dict(evidence),
        "fresh_catalog_pages": pages, "fresh_catalog_rows": catalog_rows,
        "fresh_card_revalidation_at_utc": now(), "excluded": excluded,
        "wb_review_left_pending": True, "local_source_deleted": False,
        "phase": "fresh_preflight_passed_before_first_write", "batches": [],
    }
    save(STATE, state)
    print(json.dumps({k: v for k, v in state.items() if k not in {"batches", "excluded"}},
                     ensure_ascii=False), flush=True)

    batches = [updates[i:i + 100] for i in range(0, len(updates), 100)]
    for index, batch in enumerate(batches, 1):
        payload = [x["payload"] for x in batch]
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        if size > 9_500_000:
            raise RuntimeError("wb_request_payload_too_large:" + str(index))
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prepared = {"key": f"wb:52132:uncovered:{marker}", "phase": "prepared", "at": now(),
                    "batch": index, "cards": len(batch), "offers": [x["offer_id"] for x in batch],
                    "request_sha256": marker, "request_bytes": size}
        journal(prepared)
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        if response.get("error") is not False:
            journal({**prepared, "phase": "response_rejected", "response": response, "finished_at": now()})
            state["phase"] = "wb_write_rejected_readback_required"
            state["batches"].append({"batch": index, "cards": len(batch), "response": response})
            save(STATE, state)
            raise RuntimeError("wb_write_batch_rejected:" + str(index))
        journal({**prepared, "phase": "response", "response": response, "finished_at": now()})
        state["batches"].append({"batch": index, "cards": len(batch), "response": response})
        state["phase"] = "wb_batches_accepted_readback_pending"
        state["updated_at_utc"] = now()
        save(STATE, state)
        print(json.dumps({"phase": state["phase"], "batch": index, "batch_count": len(batches),
                          "cards": len(batch), "accepted_total": sum(x["cards"] for x in state["batches"])}), flush=True)

    # Full fresh catalog readback after all writes, followed by exact metadata and non-document reconciliation.
    after_by_offer, rb_pages, rb_rows = current_catalog(client, set(targets))
    verified = []
    failures = []
    verdict_counts = collections.Counter()
    for offer in sorted(targets):
        rows = after_by_offer.get(offer, [])
        if len(rows) != 1:
            failures.append({"offer_id": offer, "reason": "readback_card_missing_or_duplicate"})
            continue
        card = rows[0]
        matches = target_doc_rows(card)
        exact = len(matches) == 1 and is_exact_document(matches[0])
        non_doc_unchanged = offer not in before or comparable_card(before[offer]) == comparable_card(card)
        if exact and non_doc_unchanged:
            raw = matches[0]
            verdict = raw.get("verdict") or raw.get("status") or ""
            verdict_counts[str(verdict or "not_returned")] += 1
            verified.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                             "metadata_exact": True, "non_document_fields_unchanged": True,
                             "verdict": verdict, "document": raw})
        else:
            failures.append({"offer_id": offer, "reason": "metadata_or_non_document_readback_mismatch",
                             "document_count": len(matches), "non_document_unchanged": non_doc_unchanged,
                             "documents": matches})
    final = {
        "checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "ozon_certificate_id": RECORD_ID, "ozon_eligible_targets": 0,
        "ozon_held_reason": "Live Ozon TNVED 9405190039 is outside this declaration's listed codes; no TNVED changes made.",
        "wb_target_cards": len(targets), "wb_verified_exact_metadata_cards": len(verified),
        "wb_verified_counts_by_verdict": dict(verdict_counts), "wb_readback_failures": failures,
        "wb_readback_pages": rb_pages, "wb_readback_catalog_rows": rb_rows,
        "wb_review_left_pending": True, "local_source_deleted": False,
        "verified_targets": verified,
    }
    save(AFTER, final)
    state["phase"] = "wb_readback_complete" if not failures and len(verified) == len(targets) else "wb_readback_incomplete"
    state["finished_at_utc"] = now()
    state["readback_summary"] = {k: final[k] for k in (
        "wb_target_cards", "wb_verified_exact_metadata_cards", "wb_verified_counts_by_verdict",
        "wb_readback_failures", "wb_review_left_pending")}
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "readback": state["readback_summary"],
                      "readback_artifact": str(AFTER)}, ensure_ascii=False), flush=True)
    if failures or len(verified) != len(targets):
        raise RuntimeError("wb_postwrite_readback_incomplete")


if __name__ == "__main__":
    main()
