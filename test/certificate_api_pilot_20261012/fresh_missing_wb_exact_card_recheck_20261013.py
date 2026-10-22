"""Recheck missing exact WB vendorCodes from a prior full Feron catalog pass."""
from __future__ import annotations

import collections
import importlib.util
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now, save  # noqa: E402

MODULE = BASE / "fresh_exact_ozon_identity_audit_20261013.py"
SPEC = importlib.util.spec_from_file_location("fresh_exact_audit", MODULE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load workbook target parser")
FRESH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FRESH)

CERT_INFO = {
    "04998/22": {"number": "ЕАЭС RU C-CN.HA46.B.04998/22", "type": 1,
                 "start": "2022-11-17", "end": "2027-11-16"},
    "53525/22": {"number": "ЕАЭС N RU Д-CN.РА06.В.53525/22", "type": 2,
                 "start": "2022-09-15", "end": "2027-09-14"},
    "87137/22": {"number": "ЕАЭС N RU Д-CN.PA02.B.87137/22", "type": 2,
                 "start": "2022-04-05", "end": "2027-04-03"},
    "87180/22": {"number": "ЕАЭС N RU Д-CN.PA02.B.87180/22", "type": 2,
                 "start": "2022-04-05", "end": "2027-04-03"},
}


def main() -> None:
    targets_by_case, excluded = FRESH.workbook_targets()
    snapshot = json.loads((BASE / "feron_full_wb_snapshot.json").read_text(encoding="utf-8"))
    if not snapshot.get("complete"):
        raise RuntimeError("Prior complete WB catalog snapshot is required")
    catalog_offers = set((snapshot.get("cards_by_offer") or {}).keys())
    target_groups = {suffix: {str(row["offer_id"]) for row in rows}
                     for suffix, rows in targets_by_case.items()}
    prior_missing = {suffix: sorted(offers - catalog_offers)
                     for suffix, offers in target_groups.items()}
    # The 87137 group already received a complete exact-target search today; retain that
    # fresh result and include all four groups here for a single reproducible ledger.
    previously_checked = json.loads((BASE / "feron_87137_wb_missing_targets_recheck_20261013.json")
                                    .read_text(encoding="utf-8"))
    if previously_checked.get("problems") or previously_checked.get("fresh_exact_cards_found") != 0:
        raise RuntimeError("87137 fresh exact search had a finding or API problem")
    prior_missing["87137/22"] = list(previously_checked["still_missing_exact_cards"])

    offer_to_groups: dict[str, list[str]] = collections.defaultdict(list)
    for suffix, offers in prior_missing.items():
        for offer in offers:
            offer_to_groups[offer].append(suffix)
    client = Client()
    result = {
        "checked_at_utc": now(), "read_only": True,
        "source_catalog_checked_at": snapshot.get("checked_at"),
        "source_catalog_complete": snapshot.get("complete"),
        "target_counts": {suffix: len(offers) for suffix, offers in target_groups.items()},
        "previously_missing_counts": {suffix: len(offers) for suffix, offers in prior_missing.items()},
        "excluded_candidate_rows": excluded,
        "unique_missing_vendor_code_count": len(offer_to_groups),
        "results": [],
    }
    save("fresh_missing_wb_exact_card_recheck_20261013.json", result)
    for index, (offer, groups) in enumerate(sorted(offer_to_groups.items()), start=1):
        cards = client.wb_cards(offer)
        matches = []
        for card in cards:
            docs = card.get("docs") or []
            per_group = {}
            for suffix in groups:
                spec = CERT_INFO[suffix]
                rows = [doc for doc in docs
                        if str(doc.get("number", "")) == spec["number"]
                        and int(doc.get("type", -1)) == spec["type"]]
                per_group[suffix] = [{
                    "number": row.get("number"), "type": row.get("type"),
                    "startDate": row.get("startDate"), "endDate": row.get("endDate"),
                    "verdict": row.get("verdict"),
                    "dates_match": str(row.get("startDate", ""))[:10] == spec["start"]
                        and str(row.get("endDate", ""))[:10] == spec["end"],
                } for row in rows]
            matches.append({"nmID": str(card.get("nmID")), "vendorCode": card.get("vendorCode"),
                            "brand": card.get("brand"), "subjectName": card.get("subjectName"),
                            "document_rows_by_group": per_group,
                            "card_updatedAt": card.get("updatedAt")})
        item = {"offer": offer, "groups": groups, "exact_cards_found": len(matches),
                "exact_cards": matches}
        result["results"].append(item)
        if index % 20 == 0 or index == len(offer_to_groups):
            save("fresh_missing_wb_exact_card_recheck_20261013.json", result)
            print(json.dumps({"checked": index, "total": len(offer_to_groups),
                              "exact_cards_found_so_far": sum(x["exact_cards_found"] for x in result["results"])},
                             ensure_ascii=False), flush=True)

    result["summary"] = {
        "all_exact_queries_completed": len(result["results"]) == len(offer_to_groups),
        "api_problem_count": 0,
        "exact_cards_found": sum(x["exact_cards_found"] for x in result["results"]),
        "offers_still_without_exact_card": sum(x["exact_cards_found"] == 0 for x in result["results"]),
        "offers_with_multiple_exact_cards": [x["offer"] for x in result["results"] if x["exact_cards_found"] > 1],
        "cards_without_expected_doc_by_group": {
            suffix: [x["offer"] for x in result["results"] if suffix in x["groups"]
                     and x["exact_cards_found"] == 1
                     and not x["exact_cards"][0]["document_rows_by_group"][suffix]]
            for suffix in target_groups
        },
    }
    save("fresh_missing_wb_exact_card_recheck_20261013.json", result)
    print("SAVED", json.dumps(result["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
