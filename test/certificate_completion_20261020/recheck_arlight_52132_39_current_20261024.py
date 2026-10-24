#!/usr/bin/env python3
"""Read-only refresh of the 39 WB cards that failed earlier readback."""
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "test/certificate_api_pilot_20261012"), str(HERE)]
from api_client import Client, now  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА09.В.52132/25"
ISSUE = "2025-10-22"
EXPIRY = "2030-10-20"
OUT = HERE / "arlight_52132_wb_39_current_recheck_20261024.json"


def main() -> None:
    prior = json.loads((HERE / "arlight_52132_wb_uncovered_retry_targeted_readback_20261022.json").read_text())
    unresolved = sorted({r["offer_id"]: r for r in prior["results"] if r.get("status") == "document_not_visible"}.values(), key=lambda r: r["offer_id"])
    client = Client()
    results = []
    for i, target in enumerate(unresolved, 1):
        offer = target["offer_id"]
        cards = [c for c in client.wb_cards(offer) if c.get("vendorCode") == offer]
        if len(cards) != 1:
            results.append({"offer_id": offer, "status": "missing_or_duplicate_card", "card_count": len(cards)})
        else:
            card = cards[0]
            docs = [d for d in ((card.get("documents") or {}).get("items") or []) if norm_number(d.get("number")) == norm_number(NUMBER)]
            codes = sorted(set(code_values(card)))
            exact = len(docs) == 1 and str(docs[0].get("type")) == "2" and str(docs[0].get("startDate", ""))[:10] == ISSUE and str(docs[0].get("endDate", ""))[:10] == EXPIRY
            verdict = docs[0].get("verdict") or {} if docs else {}
            results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"), "tnved_codes": codes, "document_count": len(docs), "metadata_exact": exact, "verdict_status": verdict.get("status"), "verdict_reason": verdict.get("reason"), "updatedAt": card.get("updatedAt"), "status": "exact" if exact else "document_not_visible" if not docs else "metadata_conflict"})
        if i % 10 == 0 or i == len(unresolved):
            print(f"WB recheck {i}/{len(unresolved)}", flush=True)
    counts = collections.Counter(r["status"] for r in results)
    report = {"checked_at_utc": now(), "read_only": True, "number": NUMBER, "previously_unresolved_targets": len(unresolved), "current_status_counts": dict(counts), "exact_metadata_count": sum(r.get("metadata_exact", False) for r in results), "exact_valid_count": sum(r.get("metadata_exact") and r.get("verdict_status") == 1 and r.get("verdict_reason") == "valid" for r in results), "results": results, "wb_review_left_to_marketplace": True, "local_source_deleted": False}
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temp.replace(OUT)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False), flush=True)
    print(f"saved {OUT}", flush=True)


if __name__ == "__main__":
    main()
