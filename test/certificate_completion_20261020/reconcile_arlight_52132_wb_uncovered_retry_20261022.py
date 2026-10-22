#!/usr/bin/env python3
"""Read back the accepted 39-card Arlight retry without sending another mutation."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
ISSUE = "2025-10-22"
EXPIRY = "2030-10-20"
JOURNAL = HERE / "arlight_52132_wb_uncovered_retry_journal_20261022.jsonl"
BEFORE = HERE / "arlight_52132_wb_uncovered_before_20261022.json"
OUT = HERE / "arlight_52132_wb_uncovered_retry_targeted_readback_20261022.json"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("output_exists_inspect_before_retry")
    entries = [json.loads(line) for line in JOURNAL.read_text().splitlines() if line.strip()]
    accepted = [x for x in entries if x.get("phase") == "response"]
    if len(accepted) != 1 or (accepted[0].get("response") or {}).get("error") is not False:
        raise RuntimeError("retry_batch_acceptance_not_proven")
    offers = accepted[0].get("offers") or []
    if len(offers) != 39 or len(set(offers)) != 39:
        raise RuntimeError("retry_offer_list_incomplete")
    before = json.loads(BEFORE.read_text())["cards"]
    client = Client()
    results = []
    for index, offer in enumerate(sorted(offers), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            results.append({"offer_id": offer, "status": "missing_or_duplicate", "card_count": len(cards)})
            continue
        card = cards[0]
        docs = [x for x in ((card.get("documents") or {}).get("items") or [])
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = (len(docs) == 1 and str(docs[0].get("type")) == "2"
                 and str(docs[0].get("startDate", ""))[:10] == ISSUE
                 and str(docs[0].get("endDate", ""))[:10] == EXPIRY)
        unchanged = offer in before and comparable_card(before[offer]) == comparable_card(card)
        identity = (str(card.get("nmID") or "") == str(before.get(offer, {}).get("nmID") or "")
                    and str(card.get("brand") or "").strip().casefold() == "arlight")
        status = "verified_exact" if exact and unchanged and identity else (
            "document_not_visible" if not docs else "readback_conflict")
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "status": status, "exact_metadata": exact,
                        "non_document_fields_unchanged": unchanged, "identity_exact": identity,
                        "tnved_codes": sorted(set(code_values(card))),
                        "verdict": docs[0].get("verdict") if docs else None,
                        "document_rows": docs})
        if index % 10 == 0:
            print(json.dumps({"phase": "retry_targeted_readback", "queried": index,
                              "targets": len(offers),
                              "verified": sum(x["status"] == "verified_exact" for x in results)},
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
    output = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
              "accepted_retry_cards": len(offers), "status_counts": dict(counts),
              "verified_exact_by_wb_verdict": dict(verdicts), "wb_review_left_pending": True,
              "local_source_deleted": False, "results": results}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in output.items() if k != "results"}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
