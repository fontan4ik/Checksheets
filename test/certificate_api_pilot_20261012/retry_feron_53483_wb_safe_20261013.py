"""One guarded retry after an accepted WB update remained unapplied for 30 minutes."""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now
from feron_53483_crossplatform_20261013 import CARD_FIELDS, EXPIRY, ISSUE, WB_NUMBER, clean_wb_doc, norm

ORIGINAL = BASE / "feron_53483_wb_execution_20261013.json"
OUT = BASE / "feron_53483_wb_retry_execution_20261013.json"
TARGET_SIGNATURE = (2, norm(WB_NUMBER), ISSUE, EXPIRY, False)
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def document_signature(doc: dict) -> tuple:
    return (int(doc.get("type") or 0), norm(doc.get("number") or ""),
            str(doc.get("startDate") or "")[:10], str(doc.get("endDate") or "")[:10],
            bool(doc.get("isEndless", False)))


def characteristic_signature(rows: list[dict]) -> collections.Counter:
    result = collections.Counter()
    for row in rows or []:
        signature = (int(row.get("id", -1)), str(row.get("name") or ""),
                     json.dumps(row.get("value"), ensure_ascii=False, sort_keys=True))
        result[signature] += 1
    return result


def clean_document_counter(rows: list[dict]) -> collections.Counter:
    return collections.Counter(json.dumps(clean_wb_doc(row), ensure_ascii=False, sort_keys=True)
                               for row in rows or [])


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Retry journal already exists; reconcile live state before any further write")
    if not ORIGINAL.exists():
        raise RuntimeError("Original WB execution journal is missing")
    original = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    if (original.get("phase") != "accepted_waiting_for_wb_sync"
            or original.get("mutation_attempts") != 1
            or (original.get("response") or {}).get("error") is not False
            or len(original.get("payload") or []) != 5):
        raise RuntimeError("Original accepted single-write journal is not in the expected state")

    client = Client()
    retry_payload = []
    checks = []
    for sent in original["payload"]:
        offer = str(sent["vendorCode"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            checks.append({"offer_id": offer, "safe": False, "reason": "card_missing_or_ambiguous"})
            continue
        card = cards[0]
        if str(card.get("nmID")) != str(sent.get("nmID")) or str(card.get("vendorCode")) != offer:
            checks.append({"offer_id": offer, "safe": False, "reason": "identity_changed"})
            continue
        changed = []
        for key in CARD_FIELDS:
            if key == "characteristics":
                if characteristic_signature(card.get(key) or []) != characteristic_signature(sent.get(key) or []):
                    changed.append(key)
            elif card.get(key) != sent.get(key):
                changed.append(key)
        docs = card.get("documents") or card.get("docs") or {}
        if docs.get("excludeDocuments") is not False:
            changed.append("documents.excludeDocuments")
        current_docs = docs.get("items") or []
        target_rows = [row for row in current_docs if document_signature(row)[0:2] == TARGET_SIGNATURE[0:2]]
        sent_rows = (sent.get("documents") or {}).get("items") or []
        expected_old = [row for row in sent_rows if document_signature(row)[0:2] != TARGET_SIGNATURE[0:2]]
        actual_old = [row for row in current_docs if document_signature(row)[0:2] != TARGET_SIGNATURE[0:2]]
        if clean_document_counter(expected_old) != clean_document_counter(actual_old):
            changed.append("preexisting_documents")
        if target_rows:
            changed.append("target_document_already_present_or_conflicting")
        check = {"offer_id": offer, "nmID": str(card.get("nmID")), "safe": not changed,
                 "changed_fields": changed, "preexisting_documents_preserved": "preexisting_documents" not in changed,
                 "target_document_rows_before_retry": len(target_rows),
                 "updatedAt": card.get("updatedAt"), "excludeDocuments": docs.get("excludeDocuments")}
        checks.append(check)
        if changed:
            continue
        clean_docs = [clean_wb_doc(row) for row in current_docs]
        new_doc = {"type": 2, "number": WB_NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
        payload = {key: card[key] for key in CARD_FIELDS if key in card}
        payload["documents"] = {"items": clean_docs + [new_doc], "excludeDocuments": False}
        retry_payload.append(payload)

    encoded = json.dumps(retry_payload, ensure_ascii=False, separators=(",", ":")).encode()
    safe = len(checks) == 5 and all(x.get("safe") for x in checks) and len(retry_payload) == 5 and len(encoded) <= 10_000_000
    state = {"prepared_at_utc": now(), "source_execution": ORIGINAL.name,
             "prior_write_accepted_at_utc": original.get("sent_at"),
             "prior_write_age_minutes_at_preflight": round((__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                    - __import__("datetime").datetime.fromisoformat(original["sent_at"].replace("Z", "+00:00"))).total_seconds()/60, 2),
             "phase": "preflight_complete" if safe else "preflight_blocked", "target_count": len(retry_payload),
             "preflight": checks, "payload_sha256": hashlib.sha256(encoded).hexdigest(),
             "payload_bytes": len(encoded), "payload": retry_payload, "mutation_attempts": 0}
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if not safe:
        raise RuntimeError("Fresh WB card state differs from the reviewed payload; no retry was sent")

    state.update({"phase": "mutation_started", "mutation_attempts": 1, "sent_at_utc": now()})
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        response = client.call("wb", "/content/v2/cards/update", retry_payload, mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "finished_at_utc": now()})
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Retry outcome uncertain; read back all five cards before any new write") from None
    state.update({"phase": "accepted_waiting_for_wb_sync" if response.get("error") is False else "rejected",
                  "response": response, "finished_at_utc": now()})
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": state["phase"], "target_count": state["target_count"],
                      "mutation_attempts": state["mutation_attempts"], "payload_sha256": state["payload_sha256"],
                      "response": response}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
