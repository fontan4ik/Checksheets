"""Read all live WB cards, retaining full records for the FERON 01381/22 targets."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent


def main() -> None:
    plan_path = BASE / "feron_01381_plan.json"
    if not plan_path.is_file():
        raise RuntimeError("Ozon preflight plan is required to define exact WB targets")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    targets = plan["target_offer_to_sku"]
    found: dict[str, list[dict]] = {offer: [] for offer in targets}
    seen_nmids = set()
    seen_cursors = set()
    page = 0
    cursor = {"limit": 100}
    client = Client()
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        cards = body.get("cards")
        if body.get("error") or not isinstance(cards, list):
            raise RuntimeError(f"WB card page {page + 1} is invalid")
        page += 1
        for card in cards:
            nmid = str(card.get("nmID", ""))
            if not nmid or nmid in seen_nmids:
                raise RuntimeError(f"WB page {page} has missing/duplicate nmID")
            seen_nmids.add(nmid)
            offer = str(card.get("vendorCode", ""))
            if offer in found:
                found[offer].append(card)
        returned = body.get("cursor") or {}
        if returned.get("total") != len(cards):
            raise RuntimeError(f"WB cursor total/card count mismatch on page {page}")
        if len(cards) < 100:
            break
        next_cursor = {key: returned[key] for key in ("updatedAt", "nmID") if key in returned}
        if len(next_cursor) != 2:
            raise RuntimeError(f"WB page {page} has an incomplete pagination cursor")
        signature = (next_cursor["updatedAt"], next_cursor["nmID"])
        if signature in seen_cursors:
            raise RuntimeError(f"WB pagination repeated at page {page}")
        seen_cursors.add(signature)
        cursor = {"limit": 100, **next_cursor}
        if page % 40 == 0:
            print(json.dumps({"pages": page, "catalog_cards_read": len(seen_nmids),
                              "target_cards_found": sum(map(len, found.values()))}, ensure_ascii=False), flush=True)
    missing = sorted(offer for offer, cards in found.items() if not cards)
    multiple = {offer: [str(card["nmID"]) for card in cards]
                for offer, cards in found.items() if len(cards) > 1}
    snapshot = {
        "checked_at": now(),
        "complete_catalog_read": True,
        "pages": page,
        "catalog_cards_read": len(seen_nmids),
        "target_offer_count": len(targets),
        "matched_card_count": sum(map(len, found.values())),
        "offers_without_wb_card": missing,
        "offers_with_multiple_wb_cards": multiple,
        "cards": [card for offer in sorted(found) for card in found[offer]],
    }
    save("feron_01381_wb_cards_live.json", snapshot)
    print(json.dumps({"complete_catalog_read": True, "pages": page,
                      "catalog_cards_read": len(seen_nmids), "target_offers": len(targets),
                      "matched_cards": snapshot["matched_card_count"],
                      "offers_without_wb_card": len(missing),
                      "offers_with_multiple_wb_cards": len(multiple)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
