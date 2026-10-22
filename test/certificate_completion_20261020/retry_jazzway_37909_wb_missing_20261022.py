#!/usr/bin/env python3
"""Retry only Jazzway WB cards with direct postwrite readback proving no metadata."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
ISSUE = "2022-11-21"
EXPIRY = "2027-11-20"
ALLOWED = {"8539520001", "8539520002", "8539520003", "8539520009"}
PREFLIGHT = HERE / "jazzway_37909_uncovered_preflight_20261022.json"
FIRST_READBACK = HERE / "jazzway_37909_uncovered_wb_readback_20261022.json"
BEFORE = HERE / "jazzway_37909_uncovered_wb_before_20261022.json"
OUT = HERE / "jazzway_37909_uncovered_wb_retry_readback_20261022.json"
JOURNAL = HERE / "jazzway_37909_uncovered_wb_retry_journal_20261022.jsonl"


def same_doc(card: dict) -> list[dict]:
    return [x for x in ((card.get("documents") or {}).get("items") or [])
            if norm_number(x.get("number")) == norm_number(NUMBER)]


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("retry_artifact_exists_inspect_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    first = json.loads(FIRST_READBACK.read_text())
    original = json.loads(BEFORE.read_text())["cards"]
    missing = [x["offer_id"] for x in first["results"] if x.get("status") == "readback_mismatch"]
    if len(missing) != 10 or any(x.get("documents") for x in first["results"] if x.get("offer_id") in missing):
        raise RuntimeError("direct_readback_did_not_confirm_exactly_10_missing_documents")
    wb_pre = {x["offer_id"]: x for x in pre["wb_targets"]}
    client = Client()
    desired = {"type": 2, "number": NUMBER, "startDate": f"{ISSUE}T00:00:00Z",
        "endDate": f"{EXPIRY}T00:00:00Z", "isEndless": False}
    before_retry = {}
    updates = []
    already_exact = []
    for offer in sorted(missing):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("retry_preflight_card_missing_or_duplicate:" + offer)
        card = cards[0]
        prior = original.get(offer) or {}
        expected = wb_pre.get(offer) or {}
        codes = sorted(set(code_values(card)))
        if (str(card.get("nmID") or "") != str(prior.get("nmID") or expected.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() not in {"jazzway", "jazz way"}
                or len(codes) != 1 or codes[0] not in ALLOWED):
            raise RuntimeError("retry_preflight_identity_or_scope_changed:" + offer)
        same = same_doc(card)
        if same:
            exact_existing = (len(same) == 1 and str(same[0].get("type")) == "2"
                and str(same[0].get("startDate", ""))[:10] == ISSUE
                and str(same[0].get("endDate", ""))[:10] == EXPIRY)
            if exact_existing:
                already_exact.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                    "status": "verified_exact", "exact_metadata": True,
                    "non_document_fields_unchanged": True,
                    "verdict": same[0].get("verdict"), "documents": same})
                continue
            raise RuntimeError("retry_preflight_document_metadata_conflict:" + offer)
        payload = merge_wb(card, [desired])
        if payload is None:
            raise RuntimeError("retry_preflight_merge_no_change:" + offer)
        updates.append({"offer_id": offer, "payload": payload})
        before_retry[offer] = card
    if len(updates) + len(already_exact) != 10:
        raise RuntimeError("retry_target_count_changed")
    response = None
    if updates:
        payload = [x["payload"] for x in updates]
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        if size > 9_500_000:
            raise RuntimeError("retry_request_too_large")
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prepared = {"key": "wb:37909:retry:" + marker, "phase": "prepared", "at": now(),
            "request_sha256": marker, "request_bytes": size, "cards": len(updates),
            "offers": [x["offer_id"] for x in updates]}
        with JOURNAL.open("a") as f:
            f.write(json.dumps(prepared, ensure_ascii=False) + "\n")
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        with JOURNAL.open("a") as f:
            f.write(json.dumps({**prepared, "phase": "response", "response": response, "finished_at": now()}, ensure_ascii=False) + "\n")
        if response.get("error") is not False:
            raise RuntimeError("retry_batch_rejected_reconcile_before_any_retry")
        print(json.dumps({"phase": "retry_batch_accepted", "cards": len(updates), "response": response}, ensure_ascii=False), flush=True)

    results = list(already_exact)
    for index, row in enumerate(updates, 1):
        offer = row["offer_id"]
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            results.append({"offer_id": offer, "status": "missing_or_duplicate", "card_count": len(cards)})
            continue
        card = cards[0]
        docs = same_doc(card)
        exact = (len(docs) == 1 and str(docs[0].get("type")) == "2"
            and str(docs[0].get("startDate", ""))[:10] == ISSUE
            and str(docs[0].get("endDate", ""))[:10] == EXPIRY)
        unchanged = comparable_card(before_retry[offer]) == comparable_card(card)
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "status": "verified_exact" if exact and unchanged else "readback_mismatch",
            "exact_metadata": exact, "non_document_fields_unchanged": unchanged,
            "verdict": docs[0].get("verdict") if docs else None, "documents": docs})
        print(json.dumps({"phase": "retry_targeted_readback", "queried": index,
            "targets": len(updates), "verified": sum(x["status"] == "verified_exact" for x in results)}, ensure_ascii=False), flush=True)
    counts = collections.Counter(x["status"] for x in results)
    verdicts = collections.Counter()
    for row in results:
        if row["status"] != "verified_exact": continue
        verdict = row.get("verdict")
        if isinstance(verdict, dict): verdicts[str(verdict.get("reason") or verdict.get("status") or "unknown")] += 1
        else: verdicts[str(verdict or "not_returned")] += 1
    out = {"checked_at_utc": now(), "read_only_after_retry": True, "number": NUMBER,
        "retry_cards": len(updates), "became_exact_before_retry": len(already_exact),
        "status_counts": dict(counts), "verdict_counts": dict(verdicts),
        "wb_review_left_pending": True, "local_source_deleted": False,
        "retry_batch_response": response, "results": results}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in out.items() if k != "results"}, ensure_ascii=False, indent=2), flush=True)
    if counts != {"verified_exact": 10}:
        raise RuntimeError("wb_retry_readback_incomplete")


if __name__ == "__main__":
    main()
