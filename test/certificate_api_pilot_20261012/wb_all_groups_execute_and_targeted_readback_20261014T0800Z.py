"""Submit the verified missing WB rows once, then verify exact live cards."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import (
    DOC_FIELDS, comparable_card, doc_key, norm_number,
)

BASE_DIR = Path(__file__).resolve().parent
PREFLIGHT = BASE_DIR / "wb_all_groups_targeted_preflight_20261014T0800Z.json"
RUN = BASE_DIR / "wb_all_groups_execution_20261014T0800Z.json"
READBACK = BASE_DIR / "wb_all_groups_targeted_readback_20261014T0800Z.json"


def read_documents(card: dict) -> list[dict]:
    return [{key: item[key] for key in DOC_FIELDS if key in item}
            for item in ((card.get("documents") or {}).get("items") or [])]


def matches(card: dict, wanted: dict) -> list[dict]:
    return [d for d in read_documents(card)
            if doc_key(d) == doc_key(wanted)
            and str(d.get("startDate") or "")[:10] == str(wanted.get("startDate") or "")[:10]
            and str(d.get("endDate") or "")[:10] == str(wanted.get("endDate") or "")[:10]]


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Unique run marker already exists; reconcile live state before any further write")
    pre = json.loads(PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(pre["checked_at"].replace("Z", "+00:00"))
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 1200:
        raise RuntimeError("Exact-card preflight is over 20 minutes old; refresh before writing")
    results = pre.get("results") or []
    if len(results) != pre.get("planned_cards") or pre.get("planned_cards") != 63:
        raise RuntimeError("Preflight cardinality mismatch; refusing to write")
    if len({row.get("offer_id") for row in results}) != len(results):
        raise RuntimeError("Preflight contains duplicate offers; refusing to write")
    unexpected = [row for row in results if row.get("state") not in {"ready", "already_visible"}]
    if unexpected:
        raise RuntimeError(f"Preflight has {len(unexpected)} conflicts/errors; inspect before writing")
    ready = [row for row in results if row["state"] == "ready"]
    if not ready:
        print(json.dumps({"state": "no_write_needed", "already_visible": len(results)}, ensure_ascii=False))
        return
    for row in ready:
        if row["before"].get("vendorCode") != row["offer_id"]:
            raise RuntimeError("Exact vendorCode proof mismatch")
        if len(row.get("ozon_proof") or []) != 1:
            raise RuntimeError("Expected one exact approved Ozon proof per WB row")
        proof = row["ozon_proof"][0]
        addition = row["additions"][0]
        if (proof.get("ozon_status") != "approved" or proof.get("binding_status") != "approved"
                or proof.get("number") != addition["number"]
                or str(proof.get("issue_date", ""))[:10] != addition["startDate"][:10]
                or str(proof.get("expire_date", ""))[:10] != addition["endDate"][:10]):
            raise RuntimeError("Ozon approval/binding/date proof does not match WB addition")
        if row["payload"].get("nmID") != row["nmID"] or row["payload"].get("vendorCode") != row["offer_id"]:
            raise RuntimeError("WB payload identity differs from exact current card")

    payload = [row["payload"] for row in ready]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 10_000_000 or len(payload) > 1000:
        raise RuntimeError("WB batch exceeds API limits")
    run = {
        "started_at": now(), "state": "prepared", "cards": len(ready),
        "documents": sum(len(row["additions"]) for row in ready),
        "request_sha256": hashlib.sha256(encoded).hexdigest(), "request_bytes": len(encoded),
        "offers": [row["offer_id"] for row in ready],
    }
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    client = Client()
    run["state"] = "submitting_once"
    run["submitted_at"] = now()
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    try:
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
    except Exception as exc:
        run["state"] = "write_outcome_uncertain_reconcile_only"
        run["error_type"] = type(exc).__name__
        run["finished_at"] = now()
        RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
        raise
    run["response"] = response
    run["state"] = "accepted_readback_pending" if response.get("error") is False else "response_error_reconcile_only"
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))

    # Read every submitted offer directly from WB. Never resubmit from this script.
    result_by_offer = {}
    for index, row in enumerate(ready, 1):
        try:
            current = client.wb_cards(row["offer_id"])
        except Exception as exc:
            result_by_offer[row["offer_id"]] = {"state": "read_error", "error": type(exc).__name__}
            continue
        if len(current) != 1:
            result_by_offer[row["offer_id"]] = {"state": "missing_or_ambiguous", "matches": len(current)}
            continue
        after = current[0]
        before = row["before"]
        visible = {d["number"]: matches(after, d) for d in row["additions"]}
        expected_docs = read_documents(before)
        after_docs = read_documents(after)
        def signatures(docs):
            return collections.Counter((doc_key(d), str(d.get("startDate") or "")[:10],
                                        str(d.get("endDate") or "")[:10]) for d in docs)
        old_docs_preserved = not (signatures(expected_docs) - signatures(after_docs))
        result_by_offer[row["offer_id"]] = {
            "state": "visible" if all(len(items) == 1 for items in visible.values()) else "pending_or_missing",
            "nmID_before": before.get("nmID"), "nmID_after": after.get("nmID"),
            "documents_visible": all(len(items) == 1 for items in visible.values()),
            "unrelated_fields_preserved": comparable_card(before) == comparable_card(after),
            "preexisting_documents_preserved": old_docs_preserved,
            "visible_documents": {number: (items[0] if items else None) for number, items in visible.items()},
            "overallVerdict": (after.get("documents") or {}).get("overallVerdict"),
        }
        if index % 10 == 0:
            print(f"read back {index}/{len(ready)} exact cards", flush=True)

    summary = {
        "checked_at": now(), "cards_submitted": len(ready), "documents_submitted": run["documents"],
        "accepted_response": response.get("error") is False,
        "counts": dict(collections.Counter(x.get("state", "unknown") for x in result_by_offer.values())),
        "all_documents_visible": all(x.get("documents_visible") for x in result_by_offer.values()),
        "all_unrelated_fields_preserved": all(x.get("unrelated_fields_preserved") for x in result_by_offer.values()),
        "all_preexisting_documents_preserved": all(x.get("preexisting_documents_preserved") for x in result_by_offer.values()),
        "results": result_by_offer,
    }
    READBACK.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    run["readback"] = {k: v for k, v in summary.items() if k != "results"}
    run["finished_at"] = now()
    run["state"] = ("readback_complete" if summary["accepted_response"]
                    and summary["all_documents_visible"]
                    and summary["all_unrelated_fields_preserved"]
                    and summary["all_preexisting_documents_preserved"] else "readback_needs_review")
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
