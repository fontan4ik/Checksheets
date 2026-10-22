#!/usr/bin/env python3
"""Direct per-vendorCode reconciliation for WB cards missed by catalog cursor readback."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from apply_arlight_52132_wb_uncovered_20261022 import (  # noqa: E402
    AFTER as FIRST_READBACK, BEFORE, EXPIRY, ISSUE, NUMBER,
)

OUT = HERE / "arlight_52132_wb_uncovered_targeted_readback_20261022.json"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("targeted_readback_exists_inspect_before_retry")
    first = json.loads(FIRST_READBACK.read_text())
    before_doc = json.loads(BEFORE.read_text())
    before = before_doc["cards"]
    failures = {x["offer_id"] for x in first["wb_readback_failures"]}
    if len(failures) != 199:
        raise RuntimeError(f"unexpected_first_readback_failure_count:{len(failures)}")
    client = Client()
    results = []
    for index, offer in enumerate(sorted(failures), 1):
        cards = client.wb_cards(offer)
        exact_cards = [c for c in cards if str(c.get("vendorCode") or "") == offer]
        if len(exact_cards) != 1:
            results.append({"offer_id": offer, "card_count": len(exact_cards),
                            "status": "missing_or_duplicate", "nmIDs": [str(c.get("nmID") or "") for c in exact_cards]})
            continue
        card = exact_cards[0]
        docs = [d for d in ((card.get("documents") or {}).get("items") or [])
                if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = (len(docs) == 1 and str(docs[0].get("type")) == "2"
                 and str(docs[0].get("startDate", ""))[:10] == ISSUE
                 and str(docs[0].get("endDate", ""))[:10] == EXPIRY)
        prior = before.get(offer)
        unchanged = prior is not None and comparable_card(prior) == comparable_card(card)
        expected_nm = str((prior or {}).get("nmID") or "")
        identity = (str(card.get("nmID") or "") == expected_nm
                    and str(card.get("brand") or "").strip().casefold() == "arlight"
                    and str(card.get("vendorCode") or "") == offer)
        verdict = docs[0].get("verdict") if docs else None
        if exact and unchanged and identity:
            status = "verified_exact"
        elif not docs:
            status = "document_not_visible"
        elif len(docs) > 1:
            status = "duplicate_document_metadata"
        else:
            status = "metadata_or_identity_conflict"
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "brand": card.get("brand"), "tnved_codes": sorted(set(code_values(card))),
                        "status": status, "exact_document_metadata": exact,
                        "non_document_fields_unchanged": unchanged, "identity_exact": identity,
                        "document_count": len(docs), "document_rows": docs,
                        "verdict": verdict})
        if index % 50 == 0:
            print(json.dumps({"phase": "direct_readback", "queried": index,
                              "targets": len(failures), "verified_exact": sum(x["status"] == "verified_exact" for x in results)},
                             ensure_ascii=False), flush=True)
    counts = collections.Counter(x["status"] for x in results)
    verdicts = collections.Counter()
    for row in results:
        verdict = row.get("verdict")
        if row["status"] == "verified_exact":
            if isinstance(verdict, dict):
                verdicts[str(verdict.get("reason") or verdict.get("status") or "pending_or_unknown")] += 1
            else:
                verdicts[str(verdict or "pending_or_unknown")] += 1
    output = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
              "targets_directly_queried": len(results), "status_counts": dict(counts),
              "verified_exact_by_wb_verdict": dict(verdicts), "wb_review_left_pending": True,
              "local_source_deleted": False, "results": results}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items() if k != "results"}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
