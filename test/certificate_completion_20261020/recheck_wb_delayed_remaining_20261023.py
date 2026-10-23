#!/usr/bin/env python3
"""Fresh read-only check of delayed WB document visibility for three groups."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

OUT = HERE / "wb_delayed_recheck_remaining_20261023.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
SPECS = {
    "arlight_33344": {
        "fragment": "33344/26", "number": "ЕАЭС N RU Д-CN.РА03.В.33344/26",
        "issue": "2026-04-13", "expiry": "2031-04-09", "type": "2",
    },
    "gauss_52411": {
        "fragment": "52411/23", "number": "ЕАЭС N RU Д-CN.РА04.В.52411/23",
        "issue": "2023-06-08", "expiry": "2028-06-07", "type": "2",
    },
    "stekker_24659": {
        "fragment": "24659/26", "number": "ЕАЭС N RU Д-CN.РА01.В.24659/26",
        "issue": "2026-01-22", "expiry": "2031-01-21", "type": "2",
    },
}


def targets_for(fragment: str) -> list[str]:
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        offers = {
            str(row.get("Артикул продавца") or "").strip()
            for row in csv.DictReader(stream)
            if fragment in str(row.get("Номер/название документа") or "")
            and str(row.get("Артикул продавца") or "").strip()
        }
    return sorted(offers)


def matches(doc: dict, spec: dict) -> bool:
    return (
        norm_number(doc.get("number")) == norm_number(spec["number"])
        and str(doc.get("type")) == spec["type"]
        and str(doc.get("startDate") or "")[:10] == spec["issue"]
        and str(doc.get("endDate") or "")[:10] == spec["expiry"]
        and doc.get("isEndless") is False
    )


def main() -> None:
    if OUT.exists():
        raise RuntimeError("readback_artifact_exists_inspect_before_rechecking")
    client = Client()
    groups = {}
    for key, spec in SPECS.items():
        offers = targets_for(spec["fragment"])
        rows = []
        for index, offer in enumerate(offers, 1):
            cards = [card for card in client.wb_cards(offer)
                     if str(card.get("vendorCode") or "") == offer]
            if len(cards) != 1:
                rows.append({"offer_id": offer, "exact_card_count": len(cards),
                             "exact_metadata_count": 0, "verdicts": []})
                continue
            card = cards[0]
            docs = ((card.get("documents") or {}).get("items") or [])
            exact = [doc for doc in docs if matches(doc, spec)]
            rows.append({
                "offer_id": offer,
                "nmID": str(card.get("nmID") or ""),
                "exact_card_count": 1,
                "brand": card.get("brand"),
                "exact_metadata_count": len(exact),
                "verdicts": [doc.get("verdict") for doc in exact],
                "prior_document_count": len(docs),
            })
            if index % 20 == 0:
                print(json.dumps({"group": key, "read": index, "total": len(offers)},
                                 ensure_ascii=False), flush=True)
        groups[key] = {
            "number": spec["number"],
            "target_count": len(offers),
            "exact_card_count": sum(row["exact_card_count"] == 1 for row in rows),
            "exact_metadata_count": sum(row["exact_metadata_count"] == 1 for row in rows),
            "verdict_counts": dict(Counter(
                (verdict or {}).get("reason", "no_verdict")
                for row in rows for verdict in row["verdicts"])),
            "rows": rows,
        }
    report = {"checked_at_utc": now(), "read_only": True,
              "wb_review_left_to_marketplace": True, "groups": groups}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {k: value for k, value in group.items() if k != "rows"}
                      for key, group in groups.items()}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
