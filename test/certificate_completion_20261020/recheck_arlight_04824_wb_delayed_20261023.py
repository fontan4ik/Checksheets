#!/usr/bin/env python3
"""Read-only delayed reconciliation for Arlight 04824/22 WB card updates."""
from __future__ import annotations

import collections
import datetime as dt
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from execute_arlight_04824_crossplatform_20261023 import (  # noqa: E402
    NUMBER, ISSUE_DATE, EXPIRY_DATE, exact_wb_doc, document_signature,
)
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents,
)

EXECUTION = HERE / "arlight_04824_crossplatform_execution_20261023.json"
OUT = HERE / "arlight_04824_wb_delayed_recheck_20261023.json"
PREFLIGHT = HERE / "arlight_04824_crossplatform_preflight_20261023.json"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("delayed_recheck_output_exists")
    execution = json.loads(EXECUTION.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    targets = preflight["wb_targets"]
    first_by_offer = {row["offer_id"]: row for row in execution["wb"]["readback"]}
    if len(targets) != 120 or len(first_by_offer) != 120:
        raise RuntimeError("unexpected_target_count")

    client = Client()
    rows = []
    for index, target in enumerate(targets, 1):
        offer = target["offer_id"]
        cards = client.wb_cards(offer)
        first = first_by_offer[offer]
        result = {"offer_id": offer, "expected_nmID": str(target["wb_nmID"]),
                  "card_count": len(cards)}
        if len(cards) != 1:
            result.update({"exact_metadata_visible": False,
                           "state": "card_missing_or_ambiguous"})
        else:
            card = cards[0]
            state, matches = exact_wb_doc(card)
            exact = state == "exact" and len(matches) == 1
            expected_verdict = matches[0].get("verdict") or {} if exact else {}
            result.update({
                "nmID": str(card.get("nmID") or ""),
                "identity_matches": str(card.get("nmID") or "") == str(target["wb_nmID"]),
                "exact_metadata_visible": exact,
                "document_state": state,
                "document_id": matches[0].get("id") if exact else None,
                "verdict": expected_verdict,
                "prior_documents_preserved": False,
                "unrelated_fields_preserved": False,
            })
            # The prior card snapshot is not duplicated in the execution result. Preservation
            # was already checked for every card during the initial post-write readback.
            result["prior_documents_preserved"] = first.get("prior_documents_preserved") is True
            result["unrelated_fields_preserved"] = first.get("unrelated_fields_preserved") is True
            if result["identity_matches"] is not True:
                raise RuntimeError("nmID_changed_for_offer:" + offer)
        rows.append(result)
        if index % 25 == 0:
            print(json.dumps({"checked": index, "total": len(targets), "at": now()},
                             ensure_ascii=False), flush=True)

    counts = collections.Counter()
    for row in rows:
        if not row.get("exact_metadata_visible"):
            counts["missing_or_conflict"] += 1
        else:
            verdict = row.get("verdict") or {}
            if (verdict.get("verified") is True and verdict.get("status") == 1
                    and verdict.get("reason") == "valid"):
                counts["valid"] += 1
            elif verdict.get("status") in (None, 0) and verdict.get("reason") in (None, ""):
                counts["pending_or_unverified"] += 1
            else:
                counts["rejected_or_invalid"] += 1
    result = {
        "checked_at_utc": now(), "read_only": True,
        "document_number": NUMBER, "issue_date": ISSUE_DATE, "expiry_date": EXPIRY_DATE,
        "target_count": len(targets), "exact_metadata_count": sum(r["exact_metadata_visible"] for r in rows),
        "fully_preserved_count": sum(r["prior_documents_preserved"] and r["unrelated_fields_preserved"] for r in rows),
        "verdict_counts": dict(counts), "rows": rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
