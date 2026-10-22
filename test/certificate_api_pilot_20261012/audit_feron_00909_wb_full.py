"""Read fresh complete WB card objects for Feron declaration 00909/23 targets."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import Client, now
import build_feron_54301_ozon_plan as workbook_reader

BASE = Path(__file__).resolve().parent
OUT = BASE / "feron_00909_wb_full_preflight.json"
OLD = BASE / "feron_full_wb_snapshot.json"


def save(state: dict) -> None:
    state["checked_at"] = now()
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)


def main() -> None:
    workbook_reader.WORKBOOK_NUMBER_SUFFIX = "00909/23"
    rows = workbook_reader.read_target_rows()
    offers = sorted({r["offer_id"] for r in rows})
    if len(rows) != 269 or len(offers) != 269:
        raise RuntimeError("Unexpected 00909/23 workbook target set")
    old = json.loads(OLD.read_text(encoding="utf-8"))
    if not old.get("complete"):
        raise RuntimeError("Prior complete WB snapshot unavailable for nmID comparison")
    old_cards = old.get("cards_by_offer") or {}
    client = Client()
    state = {"started_at": now(), "complete": False, "target_count": len(offers),
             "read_count": 0, "cards_by_offer": {}, "missing": [], "duplicate_offers": [],
             "nmID_changes": [], "failures": []}
    save(state)
    for index, offer in enumerate(offers, 1):
        try:
            cards = client.wb_cards(offer)
        except Exception as exc:
            state["failures"].append({"offer_id": offer, "error_type": type(exc).__name__})
            save(state)
            raise
        if len(cards) > 1:
            state["duplicate_offers"].append(offer)
        elif not cards:
            state["missing"].append(offer)
        else:
            card = cards[0]
            state["cards_by_offer"][offer] = card
            prior = old_cards.get(offer)
            if prior and str(prior.get("nmID")) != str(card.get("nmID")):
                state["nmID_changes"].append({"offer_id": offer, "old": str(prior.get("nmID")),
                                               "live": str(card.get("nmID"))})
        state["read_count"] = index
        if index % 20 == 0 or index == len(offers):
            save(state)
            print(json.dumps({"read": index, "target_count": len(offers),
                              "found": len(state["cards_by_offer"]), "missing": len(state["missing"]),
                              "duplicate_offers": len(state["duplicate_offers"])}, ensure_ascii=False), flush=True)
    if state["read_count"] != len(offers) or state["failures"] or state["duplicate_offers"] or state["nmID_changes"]:
        raise RuntimeError("WB target full-card read is incomplete or changed identity")
    state["complete"] = True
    state["old_catalog_checked_at"] = old.get("checked_at")
    save(state)
    print(json.dumps({"complete": state["complete"], "checked_at": state["checked_at"],
                      "targets": len(offers), "found": len(state["cards_by_offer"]),
                      "missing": state["missing"], "path": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
