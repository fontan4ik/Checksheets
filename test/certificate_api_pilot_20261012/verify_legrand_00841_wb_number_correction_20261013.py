"""Read back the one-card Legrand WB number-format pilot."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import BASE, Client, now
from feron_53483_crossplatform_20261013 import CARD_FIELDS, clean_wb_doc, norm
from verify_alphacable_00103_wb_20261013 import char_counter

EXEC = BASE / "legrand_00841_wb_number_correction_20261013.json"
OUT = BASE / "legrand_00841_wb_number_correction_verification_20261013.json"
OFFER = "404025-1"
NMID = "1506951587"
NUMBER = "ЕАЭС KG 417/032.FR.02.00841"
OLD_NUMBER = "EAC KG 417/032.FR.02.00841"
ISSUE = "2025-10-28"
EXPIRY = "2030-10-27"
NUMBER_CHAR_ID = 15001136


def read_errors(client: Client) -> list[dict]:
    out = []
    cursor = {"limit": 100}
    for _ in range(100):
        body = client.call("wb", "/content/v2/cards/error/list",
                           {"cursor": cursor, "order": {"ascending": True}})
        if body.get("error"):
            raise RuntimeError("WB error-list returned an API error")
        data = body.get("data") or {}
        out.extend(data.get("items") or [])
        cur = data.get("cursor") or {}
        if cur.get("next") is not True:
            return out
        if not cur.get("updatedAt") or not cur.get("batchUUID"):
            raise RuntimeError("WB error-list cursor incomplete")
        cursor = {"limit": 100, "updatedAt": cur["updatedAt"], "batchUUID": cur["batchUUID"]}
    raise RuntimeError("WB error-list pagination exceeded limit")


def main() -> None:
    execution = json.loads(EXEC.read_text(encoding="utf-8"))
    if execution.get("phase") not in {"accepted_waiting_for_wb_sync", "mutation_uncertain"}:
        raise RuntimeError("WB correction journal is not in accepted/uncertain state")
    payloads = execution.get("payload") or []
    if len(payloads) != 1:
        raise RuntimeError("WB correction journal does not contain one exact card")
    expected = payloads[0]
    client = Client()
    cards = client.wb_cards(OFFER)
    if len(cards) != 1:
        raise RuntimeError("WB exact card missing or ambiguous after update")
    card = cards[0]
    changed = []
    for field in CARD_FIELDS:
        if field == "characteristics":
            before = [x for x in expected.get(field) or [] if int(x.get("id", -1)) != NUMBER_CHAR_ID]
            after = [x for x in card.get(field) or [] if int(x.get("id", -1)) != NUMBER_CHAR_ID]
            if char_counter(before) != char_counter(after):
                changed.append("unrelated_characteristics")
            old_chars = [x for x in card.get(field) or [] if int(x.get("id", -1)) == NUMBER_CHAR_ID]
            if len(old_chars) != 1 or old_chars[0].get("value") != [NUMBER]:
                changed.append("certificate_number_characteristic")
        elif card.get(field) != expected.get(field):
            changed.append(field)
    docs = card.get("documents") or card.get("docs") or {}
    rows = docs.get("items") or []
    target = [x for x in rows if int(x.get("type") or 0) == 1 and str(x.get("number") or "") == NUMBER]
    old = [x for x in rows if str(x.get("number") or "") == OLD_NUMBER]
    if len(rows) != 1:
        changed.append("document_row_count")
    try:
        errors = read_errors(client)
        matching = []
        for batch in errors:
            err = batch.get("errors") or {}
            if OFFER in err:
                matching.append({"batchUUID": batch.get("batchUUID"), "updatedAt": batch.get("updatedAt"),
                                 "errors": err[OFFER]})
        error_state = {"checked": True, "batch_count": len(errors), "matching_error_batches": matching}
    except Exception as exc:
        error_state = {"checked": False, "error_type": type(exc).__name__}
    state = {"checked_at_utc": now(), "write_accepted": (execution.get("response") or {}).get("error") is False,
             "identity_exact": str(card.get("nmID") or "") == NMID and str(card.get("vendorCode") or "") == OFFER,
             "canonical_number_visible": len(target) == 1 and len(old) == 0,
             "number_characteristic_canonical": not any(x == "certificate_number_characteristic" for x in changed),
             "other_fields_preserved": not any(x not in {"certificate_number_characteristic"} for x in changed),
             "excludeDocuments": docs.get("excludeDocuments"),
             "document_verdict": target[0].get("verdict") if target else None,
             "overallVerdict": docs.get("overallVerdict"), "wb_error_list": error_state,
             "changed_fields": changed, "document_rows": rows}
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "checked_at_utc": state["checked_at_utc"],
                      "canonical_number_visible": state["canonical_number_visible"],
                      "other_fields_preserved": state["other_fields_preserved"],
                      "document_verdict": state["document_verdict"],
                      "error_batches": len(error_state.get("matching_error_batches", []))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
