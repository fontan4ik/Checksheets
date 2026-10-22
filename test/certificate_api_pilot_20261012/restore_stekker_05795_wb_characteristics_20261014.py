"""Restore two non-document WB characteristics removed after document upload."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

from api_client import BASE, Client
from execute_stekker_05795_20261014 import (
    EXPIRY, ISSUE, NUMBER, WB_CARD_FIELDS, WB_DOC_CHAR_IDS, clean_wb_doc,
    direct_post, doc_sig,
)
from preflight_stekker_05795_20261014 import read_wb_cards

OFFERS = ("49142-1", "49791-1")
CHAR_ID = 156753
PREFLIGHT = BASE / "stekker_05795_live_preflight_20261014.json"
RUN = BASE / "stekker_05795_wb_characteristic_restore_20261014.json"


def save(value: dict) -> None:
    temp = RUN.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(RUN)


def signature(doc: dict) -> tuple:
    import re
    return (int(doc.get("type") or 0), re.sub(r"[^0-9]", "", str(doc.get("number") or "")),
            str(doc.get("startDate") or "")[:10], str(doc.get("endDate") or "")[:10],
            bool(doc.get("isEndless", False)))


def card_read(client: Client, offer: str) -> dict:
    cards = [x for x in read_wb_cards(client, offer) if x.get("vendorCode") == offer]
    if len(cards) != 1:
        raise RuntimeError(f"Expected exactly one live WB card for {offer}")
    return cards[0]


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Restore evidence already exists; reconcile live WB cards before retry")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    old_cards = {x["offer_id"]: x["cards"][0] for x in preflight["wb_cards_by_offer"]}
    client = Client()
    before, payloads = {}, []
    for offer in OFFERS:
        old = old_cards[offer]
        card = card_read(client, offer)
        if str(card.get("nmID")) != str(old.get("nmID")) or card.get("brand") != old.get("brand"):
            raise RuntimeError(f"WB identity changed for {offer}")
        for field in WB_CARD_FIELDS:
            if field != "characteristics" and old.get(field) != card.get(field):
                raise RuntimeError(f"WB non-characteristic field changed for {offer}: {field}")
        docs = (card.get("documents") or {})
        items = docs.get("items") or []
        old_items = ((old.get("documents") or {}).get("items") or [])
        old_signatures = collections.Counter(signature(x) for x in old_items)
        live_signatures = collections.Counter(signature(x) for x in items)
        if any(live_signatures[sig] < count for sig, count in old_signatures.items()):
            raise RuntimeError(f"A prior WB document row is missing from {offer}")
        target = [x for x in items if signature(x)[1].endswith("0579522")]
        if (docs.get("excludeDocuments") is not False or len(target) != 1
                or signature(target[0]) != (1, "530579522", ISSUE, EXPIRY, False)):
            raise RuntimeError(f"05795/22 is not correctly present on {offer}; restore stopped")
        old_chars = {int(x.get("id", -1)): x for x in old.get("characteristics") or []}
        cur_chars = {int(x.get("id", -1)): x for x in card.get("characteristics") or []}
        wanted = old_chars.get(CHAR_ID)
        if not wanted or wanted.get("name") != "Количество контактов" or wanted.get("value") != ["3"]:
            raise RuntimeError(f"Saved preflight does not prove the expected characteristic for {offer}")
        if CHAR_ID in cur_chars:
            if cur_chars[CHAR_ID] != wanted:
                raise RuntimeError(f"Live characteristic conflicts with the saved value for {offer}")
            continue
        if any(old_chars.get(k) != cur_chars.get(k) for k in set(old_chars) | set(cur_chars)
               if k not in {CHAR_ID} | WB_DOC_CHAR_IDS and (k in old_chars or k in cur_chars)):
            raise RuntimeError(f"Other characteristics changed on {offer}; refusing a blind full-card update")
        before[offer] = card
        characteristics = list(card.get("characteristics") or []) + [wanted]
        characteristics.sort(key=lambda row: int(row.get("id", -1)))
        payload = {key: card[key] for key in WB_CARD_FIELDS if key in card}
        payload["characteristics"] = characteristics
        payload["documents"] = {"items": [clean_wb_doc(x) for x in items],
                                 "excludeDocuments": False}
        payloads.append(payload)
    if not payloads:
        print(json.dumps({"restored_cards": 0, "already_present": list(OFFERS)}, ensure_ascii=False))
        return
    body = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    state = {"started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
             "phase": "prepared", "offers": [x["vendorCode"] for x in payloads],
             "nmids": {offer: str(card["nmID"]) for offer, card in before.items()},
             "characteristic": {"id": CHAR_ID, "name": "Количество контактов", "value": ["3"]},
             "preserved_current_documents": True,
             "request_bytes": len(body), "request_sha256": hashlib.sha256(body).hexdigest(),
             "local_cleanup_allowed": False}
    save(state)
    time.sleep(5.4)
    try:
        status, response = direct_post(client, "wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain_reconcile_before_retry", "error_type": type(exc).__name__})
        save(state)
        status, response = 0, {}
    state["http_status"] = status
    state["response"] = response
    state["phase"] = "accepted_poll_readback" if status == 200 and response.get("error") is False else "inconclusive_poll_readback"
    save(state)
    final = {}
    for attempt in range(5):
        final = {offer: card_read(client, offer) for offer in OFFERS}
        if all(any(int(x.get("id", -1)) == CHAR_ID and x.get("value") == ["3"]
                   for x in card.get("characteristics") or []) for card in final.values()):
            break
        if attempt < 4:
            time.sleep(3)
    result = {}
    for offer, card in final.items():
        characteristic = [x for x in card.get("characteristics") or [] if int(x.get("id", -1)) == CHAR_ID]
        target = [x for x in ((card.get("documents") or {}).get("items") or [])
                  if signature(x)[1].endswith("0579522")]
        result[offer] = {"nmID": str(card.get("nmID")),
                         "characteristic_present": len(characteristic) == 1 and characteristic[0].get("value") == ["3"],
                         "document_present": len(target) == 1 and signature(target[0]) == (1, "530579522", ISSUE, EXPIRY, False),
                         "document_verdict": (target[0].get("verdict") if target else None)}
    state.update({"phase": "readback_complete", "readback": result,
                  "all_restored_and_document_preserved": all(
                      x["characteristic_present"] and x["document_present"] for x in result.values()),
                  "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
    save(state)
    print(json.dumps({"phase": state["phase"], "readback": result,
                      "all_restored_and_document_preserved": state["all_restored_and_document_preserved"],
                      "journal": str(RUN)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
