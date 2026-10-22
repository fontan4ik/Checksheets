#!/usr/bin/env python3
"""Retry only Arlight WB cards where targeted readback confirms no 52132 metadata."""
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
from reconcile_approved_ozon_docs_to_wb import copy_documents, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402
from apply_arlight_52132_wb_uncovered_20261022 import (  # noqa: E402
    EXPIRY, ISSUE, NUMBER,
)

TARGET_READBACK = HERE / "arlight_52132_wb_uncovered_targeted_readback_20261022.json"
BEFORE_FILE = HERE / "arlight_52132_wb_uncovered_before_20261022.json"
OUT = HERE / "arlight_52132_wb_uncovered_retry_reconciliation_20261022.json"
JOURNAL = HERE / "arlight_52132_wb_uncovered_retry_journal_20261022.jsonl"
ALLOWED = {"9405110013", "9405110033", "9405110039", "9405420012", "9405420032", "9405420039"}


def exact_docs(card: dict) -> list[dict]:
    return [x for x in ((card.get("documents") or {}).get("items") or [])
            if norm_number(x.get("number")) == norm_number(NUMBER)]


def journal(row: dict) -> None:
    with JOURNAL.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("retry_artifact_exists_inspect_before_retry")
    targeted = json.loads(TARGET_READBACK.read_text())
    before = json.loads(BEFORE_FILE.read_text())["cards"]
    unresolved = [x for x in targeted["results"] if x.get("status") == "document_not_visible"]
    if len(unresolved) != 39:
        raise RuntimeError(f"unexpected_confirmed_missing_document_count:{len(unresolved)}")
    wanted = {x["offer_id"] for x in unresolved}
    client = Client()
    desired = {"type": 2, "number": NUMBER, "startDate": f"{ISSUE}T00:00:00Z",
                "endDate": f"{EXPIRY}T00:00:00Z", "isEndless": False}
    updates = []
    fresh_before = {}
    skipped = []
    for index, offer in enumerate(sorted(wanted), 1):
        cards = client.wb_cards(offer)
        cards = [x for x in cards if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            skipped.append({"offer_id": offer, "reason": "retry_preflight_missing_or_duplicate_card"})
            continue
        card = cards[0]
        prior = before.get(offer) or {}
        codes = sorted(set(code_values(card)))
        if (str(card.get("nmID") or "") != str(prior.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "arlight"
                or len(codes) != 1 or codes[0] not in ALLOWED):
            skipped.append({"offer_id": offer, "reason": "retry_preflight_identity_or_scope_conflict",
                            "nmID": str(card.get("nmID") or ""), "tnved": codes})
            continue
        same = exact_docs(card)
        if same:
            is_exact = (len(same) == 1 and str(same[0].get("type")) == "2"
                        and str(same[0].get("startDate", ""))[:10] == ISSUE
                        and str(same[0].get("endDate", ""))[:10] == EXPIRY)
            if is_exact:
                skipped.append({"offer_id": offer, "reason": "already_exact_on_retry_preflight"})
            else:
                skipped.append({"offer_id": offer, "reason": "retry_preflight_metadata_conflict"})
            continue
        payload = merge_wb(card, [desired])
        if payload is None:
            skipped.append({"offer_id": offer, "reason": "merge_returned_no_change_without_visible_document"})
            continue
        updates.append({"offer_id": offer, "nmID": str(card.get("nmID")), "payload": payload})
        fresh_before[offer] = card
        if index % 20 == 0:
            print(json.dumps({"phase": "retry_preflight", "checked": index,
                              "targets": len(wanted), "safe_to_retry": len(updates)}, ensure_ascii=False), flush=True)
    if skipped:
        raise RuntimeError("retry_preflight_conflicts_reconcile:" + str(len(skipped)))
    if len(updates) != len(wanted):
        raise RuntimeError("retry_target_count_changed")

    payload = [x["payload"] for x in updates]
    byte_count = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    if byte_count > 9_500_000:
        raise RuntimeError("retry_payload_too_large")
    marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    prepared = {"key": f"wb:52132:uncovered:retry:{marker}", "phase": "prepared", "at": now(),
                "cards": len(updates), "offers": [x["offer_id"] for x in updates],
                "request_sha256": marker, "request_bytes": byte_count}
    journal(prepared)
    response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
    journal({**prepared, "phase": "response", "response": response, "finished_at": now()})
    if response.get("error") is not False:
        raise RuntimeError("retry_update_rejected_reconcile_response")
    print(json.dumps({"phase": "retry_batch_accepted", "cards": len(updates), "response": response},
                     ensure_ascii=False), flush=True)

    results = []
    for index, update in enumerate(updates, 1):
        offer = update["offer_id"]
        cards = client.wb_cards(offer)
        cards = [x for x in cards if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            results.append({"offer_id": offer, "status": "missing_or_duplicate_after_retry",
                            "card_count": len(cards)})
            continue
        card = cards[0]
        docs = exact_docs(card)
        exact = (len(docs) == 1 and str(docs[0].get("type")) == "2"
                 and str(docs[0].get("startDate", ""))[:10] == ISSUE
                 and str(docs[0].get("endDate", ""))[:10] == EXPIRY)
        same_other_fields = comparable_card(fresh_before[offer]) == comparable_card(card)
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "status": "verified_exact" if exact and same_other_fields else "retry_readback_unresolved",
                        "document_count": len(docs), "exact_metadata": exact,
                        "non_document_fields_unchanged": same_other_fields,
                        "verdict": docs[0].get("verdict") if docs else None,
                        "document_rows": docs})
        if index % 20 == 0:
            print(json.dumps({"phase": "retry_readback", "queried": index,
                              "targets": len(updates), "verified": sum(x["status"] == "verified_exact" for x in results)},
                             ensure_ascii=False), flush=True)
    counts = collections.Counter(x["status"] for x in results)
    verdicts = collections.Counter()
    for row in results:
        if row["status"] != "verified_exact":
            continue
        verdict = row.get("verdict")
        if isinstance(verdict, dict):
            verdicts[str(verdict.get("reason") or verdict.get("status") or "pending_or_unknown")] += 1
        else:
            verdicts[str(verdict or "pending_or_unknown")] += 1
    output = {"checked_at_utc": now(), "read_only_after_retry": True, "number": NUMBER,
              "retry_targets": len(updates), "status_counts": dict(counts),
              "verified_exact_by_wb_verdict": dict(verdicts),
              "wb_review_left_pending": True, "local_source_deleted": False,
              "retry_batch_response": response, "results": results}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items() if k != "results"}, ensure_ascii=False, indent=2), flush=True)
    if counts != {"verified_exact": len(updates)}:
        raise RuntimeError("retry_readback_incomplete")


if __name__ == "__main__":
    main()
