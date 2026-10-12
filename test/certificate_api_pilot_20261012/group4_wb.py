"""Attach only missing, exact Systeme Electric documents to fresh WB cards."""
from __future__ import annotations

import collections
import datetime as dt
import json
import time
from pathlib import Path

from api_client import BASE, Client, now, save

PRODUCTS = {
    "BA10-001B-1": [
        {"type": 1, "number": "ЕАЭС RU C-RU.АТ21.В.00153/25", "startDate": "2025-03-18T00:00:00Z", "endDate": "2030-03-17T00:00:00Z", "isEndless": False},
        {"type": 2, "number": "ЕАЭС N RU Д-RU.РА01.В.69737/25", "startDate": "2025-02-05T00:00:00Z", "endDate": "2030-02-04T00:00:00Z", "isEndless": False},
    ],
    "BA10-001B-2": [
        {"type": 1, "number": "ЕАЭС RU C-RU.АТ21.В.00153/25", "startDate": "2025-03-18T00:00:00Z", "endDate": "2030-03-17T00:00:00Z", "isEndless": False},
        {"type": 2, "number": "ЕАЭС N RU Д-RU.РА01.В.69737/25", "startDate": "2025-02-05T00:00:00Z", "endDate": "2030-02-04T00:00:00Z", "isEndless": False},
    ],
    "BA10-001B-5": [
        {"type": 1, "number": "ЕАЭС RU C-RU.АТ21.В.00153/25", "startDate": "2025-03-18T00:00:00Z", "endDate": "2030-03-17T00:00:00Z", "isEndless": False},
        {"type": 2, "number": "ЕАЭС N RU Д-RU.РА01.В.69737/25", "startDate": "2025-02-05T00:00:00Z", "endDate": "2030-02-04T00:00:00Z", "isEndless": False},
    ],
    "PA16-007B-1": [
        {"type": 1, "number": "ЕАЭС RU C-RU.АТ21.В.00159/25", "startDate": "2025-06-27T00:00:00Z", "endDate": "2030-06-26T00:00:00Z", "isEndless": False},
        {"type": 2, "number": "ЕАЭС N RU Д-RU.РА01.В.70012/25", "startDate": "2025-02-05T00:00:00Z", "endDate": "2030-02-04T00:00:00Z", "isEndless": False},
    ],
    "PA16-007B-2": [
        {"type": 1, "number": "ЕАЭС RU C-RU.АТ21.В.00159/25", "startDate": "2025-06-27T00:00:00Z", "endDate": "2030-06-26T00:00:00Z", "isEndless": False},
        {"type": 2, "number": "ЕАЭС N RU Д-RU.РА01.В.70012/25", "startDate": "2025-02-05T00:00:00Z", "endDate": "2030-02-04T00:00:00Z", "isEndless": False},
    ],
    "PA16-007B-5": [
        {"type": 1, "number": "ЕАЭС RU C-RU.АТ21.В.00159/25", "startDate": "2025-06-27T00:00:00Z", "endDate": "2030-06-26T00:00:00Z", "isEndless": False},
        {"type": 2, "number": "ЕАЭС N RU Д-RU.РА01.В.70012/25", "startDate": "2025-02-05T00:00:00Z", "endDate": "2030-02-04T00:00:00Z", "isEndless": False},
    ],
}
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "gtin", "description", "dimensions",
               "characteristics", "sizes", "kizMarked")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant", "startDate", "endDate", "isEndless")
# Wildberries fills these document characteristics from documents.items when a
# document is attached. They are part of the intended update, even though the
# original card did not contain them.
ALLOWED_ADDED_CHARACTERISTIC_IDS = {15001136, 15001137, 15001138}
BASE_DIR = Path(__file__).resolve().parent


def norm(value: str) -> str:
    import re
    text = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").strip().upper())
    text = re.sub(r"^(?:N|№)\s*", "", text)
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
                           "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
                           "Ё": "E", "Э": "E", "Д": "D", "П": "P"})
    return "".join(x for x in text.translate(table) if x.isalnum())


def signature(doc: dict) -> tuple[int, str]:
    return int(doc.get("type", 0)), norm(doc.get("number", ""))


def canonical(value):
    result = json.loads(json.dumps(value, ensure_ascii=False))
    if isinstance(result, dict) and isinstance(result.get("characteristics"), list):
        result["characteristics"] = sorted(result["characteristics"], key=lambda x: x.get("id", 0))
    return result


def sleep_between_calls():
    # Content API allows at most 10 requests/minute for this endpoint.
    time.sleep(5.4)  # Client.call itself sleeps 0.65 seconds after each response.


def fetch_exact_cards(client: Client, offer: str) -> list[dict]:
    result = []
    cursor = {"limit": 100}
    seen = set()
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1, "textSearch": offer},
        }})
        if body.get("error") or not isinstance(body.get("cards"), list):
            raise RuntimeError(f"WB card read failed for {offer}")
        batch = body["cards"]
        if body.get("cursor", {}).get("total") != len(batch):
            raise RuntimeError(f"WB page count mismatch for {offer}")
        result.extend(c for c in batch if c.get("vendorCode") == offer)
        if len(batch) < 100:
            return result
        response_cursor = body["cursor"]
        signature = (response_cursor.get("updatedAt"), response_cursor.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError(f"WB cursor repeated/incomplete for {offer}")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
        sleep_between_calls()


def copy_doc_items(documents: dict) -> list[dict]:
    items = []
    for old in documents.get("items") or []:
        items.append({k: old[k] for k in DOC_FIELDS if k in old})
    return items


def prepare_card(card: dict, desired: list[dict]) -> dict:
    documents = card.get("documents") or {}
    if documents.get("excludeDocuments") is True:
        raise RuntimeError(f"WB card {card.get('nmID')} currently excludes documents")
    old_items = copy_doc_items(documents)
    existing = {}
    for item in old_items:
        key = signature(item)
        existing.setdefault(key, []).append(item)
    additions = []
    for doc in desired:
        found = existing.get(signature(doc), [])
        if found:
            if any((x.get("startDate", "")[:10], x.get("endDate", "")[:10]) !=
                   (doc["startDate"][:10], doc["endDate"][:10]) for x in found):
                raise RuntimeError(f"WB dates conflict for {card.get('vendorCode')} / {doc['number']}")
            continue
        additions.append(doc.copy())
    payload = {k: card[k] for k in CARD_FIELDS if k in card}
    payload["documents"] = {"items": old_items + additions, "excludeDocuments": False}
    return {"nmID": card["nmID"], "vendorCode": card["vendorCode"], "additions": additions,
            "before": card, "payload": payload}


def compare_readback(before: dict, after: dict) -> dict:
    old = canonical(before)
    new = canonical(after)
    preserved = {}
    differences = {}
    for key in CARD_FIELDS:
        if key == "characteristics":
            old_chars = {x.get("id"): x for x in old.get(key, []) or []}
            new_chars = {x.get("id"): x for x in new.get(key, []) or []}
            missing_or_changed = {i: (v, new_chars.get(i)) for i, v in old_chars.items() if new_chars.get(i) != v}
            added = {i: v for i, v in new_chars.items() if i not in old_chars}
            unexpected_added = {i: v for i, v in added.items() if i not in ALLOWED_ADDED_CHARACTERISTIC_IDS}
            preserved[key] = not missing_or_changed and not unexpected_added
            if missing_or_changed or added:
                differences[key] = {"missing_or_changed": missing_or_changed, "added": added,
                                    "unexpected_added": unexpected_added}
        else:
            preserved[key] = old.get(key) == new.get(key)
            if not preserved[key]:
                differences[key] = {"before": old.get(key), "after": new.get(key)}
    return {"preserved": all(preserved.values()), "fields": preserved, "differences": differences}


def main():
    wb_snapshot = json.loads((BASE_DIR / "wb_live.json").read_text())
    if not wb_snapshot.get("complete"):
        raise RuntimeError("Complete WB catalog snapshot required")
    snapshot_by_offer = {x.get("vendorCode"): x for x in wb_snapshot["cards"]}
    client = Client()
    before = {}
    for offer in PRODUCTS:
        cards = fetch_exact_cards(client, offer)
        if len(cards) != 1:
            raise RuntimeError(f"Expected one exact WB card for {offer}, got {len(cards)}")
        card = cards[0]
        snap = snapshot_by_offer.get(offer)
        if not snap or str(snap.get("nmID")) != str(card.get("nmID")):
            raise RuntimeError(f"WB catalog identity changed since complete snapshot for {offer}")
        before[offer] = card
        sleep_between_calls()
    save("group4_wb_before.json", before)

    planned = [prepare_card(before[offer], desired) for offer, desired in PRODUCTS.items()]
    updates = [x for x in planned if x["additions"]]
    summary = {"planned_at": now(), "wb_snapshot_checked_at": wb_snapshot.get("checked_at"),
               "live_cards_read": len(before), "missing_documents": sum(len(x["additions"]) for x in updates),
               "cards_to_update": len(updates), "already_complete": [x["vendorCode"] for x in planned if not x["additions"]],
               "updates": [{"nmID": x["nmID"], "vendorCode": x["vendorCode"], "additions": x["additions"], "payload": x["payload"]} for x in updates]}
    save("group4_wb_plan.json", summary)
    payloads = [x["payload"] for x in updates]
    encoded_size = len(json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode())
    if encoded_size > 10_000_000:
        raise RuntimeError(f"WB update payload exceeds 10 MB: {encoded_size}")
    save("group4_wb_update_payload.json", payloads)
    print(json.dumps({"cards_read": len(before), "cards_to_update": len(updates),
                      "documents_to_add": summary["missing_documents"], "payload_bytes": encoded_size,
                      "already_complete": summary["already_complete"]}, ensure_ascii=False), flush=True)

    run = {"started_at": now(), "updates": []}
    save("group4_wb_execution.json", run)
    if payloads:
        sleep_between_calls()
        body = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        run["updates"].append({"response": body, "cards": len(payloads), "documents": summary["missing_documents"]})
        save("group4_wb_execution.json", run)
        if body.get("error") is not False:
            raise RuntimeError("WB update response not accepted; reconcile before retry")
        after = {}
        preservation = {}
        for offer in (x["vendorCode"] for x in updates):
            sleep_between_calls()
            cards = fetch_exact_cards(client, offer)
            if len(cards) != 1:
                raise RuntimeError(f"WB readback did not return one card for {offer}")
            card = cards[0]
            before_card = before[offer]
            actual_docs = card.get("documents") or {}
            wanted = {signature(x): x for x in PRODUCTS[offer]}
            found = {}
            for doc in actual_docs.get("items", []) or []:
                key = signature(doc)
                if key in wanted:
                    found[key] = doc
            card_docs_present = len(found) == len(wanted)
            preservation[offer] = compare_readback(before_card, card)
            after[offer] = {"card": card, "wanted_documents_present": card_docs_present,
                            "documents": list(found.values()), "unrelated_fields_preserved": preservation[offer]}
            if not card_docs_present:
                after[offer]["readback_outcome"] = "documents_not_yet_visible_review_pending"
            elif not preservation[offer]["preserved"]:
                after[offer]["readback_outcome"] = "card_field_difference_requires_review"
            else:
                after[offer]["readback_outcome"] = "documents_visible_other_fields_preserved"
            save("group4_wb_readback.json", after)
            sleep_between_calls()
        run["readback"] = after
        run["finished_at"] = now()
        save("group4_wb_execution.json", run)
    else:
        run["finished_at"] = now()
        save("group4_wb_execution.json", run)
    print(json.dumps({"readback": {k: v.get("readback_outcome") for k, v in run.get("readback", {}).items()},
                      "finished_at": run["finished_at"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
