"""Live exact-offer preflight for the approved-Ozon-to-WB reconciliation batch."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import DOC_FIELDS, UPDATE_CARD_FIELDS, doc_key

BASE_DIR = Path(__file__).resolve().parent
PLAN = BASE_DIR / "all_groups_wb_gap_plan_20261014T0800Z.json"
OUT = BASE_DIR / "wb_all_groups_targeted_preflight_20261014T0800Z.json"


def existing_documents(card: dict) -> list[dict]:
    return [{key: item[key] for key in DOC_FIELDS if key in item}
            for item in ((card.get("documents") or {}).get("items") or [])]


def run() -> dict:
    plan = json.loads(PLAN.read_text())
    rows = plan["updates"]
    client = Client()
    results = []
    for index, row in enumerate(rows, 1):
        offer = row["offer_id"]
        try:
            cards = client.wb_cards(offer)
        except Exception as exc:
            results.append({"offer_id": offer, "state": "read_error", "error": type(exc).__name__})
            continue
        if len(cards) != 1:
            results.append({"offer_id": offer, "state": "missing_or_ambiguous", "matches": len(cards),
                            "nmIDs": [c.get("nmID") for c in cards]})
            continue
        card = cards[0]
        if card.get("vendorCode") != offer or not card.get("nmID"):
            results.append({"offer_id": offer, "state": "identity_mismatch", "nmID": card.get("nmID")})
            continue
        items = existing_documents(card)
        by_key: dict[tuple[int, str], list[dict]] = {}
        by_number: dict[str, list[dict]] = {}
        from reconcile_approved_ozon_docs_to_wb import norm_number
        for item in items:
            key = doc_key(item)
            by_key.setdefault(key, []).append(item)
            number_key = norm_number(item.get("number", ""))
            if number_key:
                by_number.setdefault(number_key, []).append(item)
        additions = []
        conflicts = []
        already_visible = []
        for desired in row["additions"]:
            key = doc_key(desired)
            same_number = by_number.get(key[1], [])
            if same_number:
                same_type = [x for x in same_number if int(x.get("type", 0)) == key[0]]
                if len(same_type) == 1:
                    current = same_type[0]
                    dates_match = (str(current.get("startDate") or "")[:10] == desired["startDate"][:10]
                                   and str(current.get("endDate") or "")[:10] == desired["endDate"][:10])
                    if dates_match:
                        already_visible.append({"number": desired["number"], "verdict": current.get("verdict")})
                        continue
                    conflicts.append({"number": desired["number"], "reason": "date_conflict"})
                    continue
                conflicts.append({"number": desired["number"], "reason": "duplicate_or_type_conflict",
                                  "current_count": len(same_number)})
                continue
            additions.append({key: desired[key] for key in ("type", "number", "startDate", "endDate", "isEndless")})
        if conflicts:
            results.append({"offer_id": offer, "nmID": card.get("nmID"), "state": "conflict",
                            "conflicts": conflicts, "already_visible": already_visible})
            continue
        if not additions:
            results.append({"offer_id": offer, "nmID": card.get("nmID"), "state": "already_visible",
                            "already_visible": already_visible})
            continue
        payload = {key: card[key] for key in UPDATE_CARD_FIELDS if key in card}
        payload["nmID"] = card["nmID"]
        payload["vendorCode"] = offer
        payload["documents"] = {
            "items": items + additions,
            "excludeDocuments": False,
        }
        results.append({
            "offer_id": offer, "nmID": card["nmID"], "state": "ready",
            "additions": additions, "already_visible": already_visible,
            "before": card, "payload": payload,
            "ozon_proof": row["ozon_proof"],
        })
        if index % 10 == 0:
            print(f"read {index}/{len(rows)} exact offers", flush=True)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    out = {
        "checked_at": now(), "plan": PLAN.name,
        "source_snapshot_at": plan.get("snapshot_checked_at"),
        "planned_cards": len(rows), "counts": counts, "results": results,
    }
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    tmp.replace(OUT)
    print(json.dumps({"checked_at": out["checked_at"], "planned_cards": len(rows),
                      "counts": counts, "output": str(OUT)}, ensure_ascii=False), flush=True)
    return out


if __name__ == "__main__":
    run()
