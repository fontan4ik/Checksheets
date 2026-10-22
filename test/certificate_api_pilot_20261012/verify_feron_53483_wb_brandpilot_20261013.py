"""Independently read back the controlled Feron WB brand/document pilot."""
from __future__ import annotations

import json
from pathlib import Path

from api_client import BASE, Client, now, save
from feron_53483_crossplatform_20261013 import CARD_FIELDS, EXPIRY, ISSUE, WB_NUMBER, clean_wb_doc, norm
from verify_alphacable_00103_wb_20261013 import char_counter, docs_counter

EXEC = BASE / "feron_53483_wb_brandpilot_20261013.json"
OUT = "feron_53483_wb_brandpilot_verification_20261013.json"
BRAND = "Feron"
OFFER = "21488-1"
NMID = "461059396"


def main() -> None:
    state = json.loads(EXEC.read_text(encoding="utf-8"))
    if state.get("mutation_attempts") != 1 or (state.get("response") or {}).get("error") is not False:
        raise RuntimeError("Pilot write was not accepted exactly once; reconcile its journal")
    payloads = state.get("payload") or []
    if len(payloads) != 1:
        raise RuntimeError("Pilot journal does not have one exact payload")
    sent = payloads[0]
    if not state.get("updatedAt_before"):
        diagnostic = json.loads((BASE / "feron_53483_wb_silent_cards_diagnostic_20261013.json").read_text(encoding="utf-8"))
        baseline = next((x.get("updatedAt") for x in diagnostic.get("cards") or []
                         if x.get("offer_id") == OFFER), None)
        if not baseline:
            raise RuntimeError("Pre-write card timestamp is unavailable for the exact pilot")
        state["updatedAt_before"] = baseline
    sent_docs = ((sent.get("documents") or {}).get("items") or [])
    prior_docs = [x for x in sent_docs if norm(x.get("number")) != norm(WB_NUMBER)]
    cards = Client().wb_cards(OFFER)
    if len(cards) != 1:
        result = {"readback_count": len(cards), "identity_exact": False}
    else:
        card = cards[0]
        container = card.get("documents") or card.get("docs") or {}
        actual_docs = container.get("items") or []
        targets = [x for x in actual_docs if int(x.get("type") or 0) == 2
                   and norm(x.get("number")) == norm(WB_NUMBER)]
        prior_actual = [x for x in actual_docs if not (int(x.get("type") or 0) == 2
                        and norm(x.get("number")) == norm(WB_NUMBER))]
        exact_metadata = len(targets) == 1 and str(targets[0].get("startDate") or "")[:10] == ISSUE \
            and str(targets[0].get("endDate") or "")[:10] == EXPIRY \
            and targets[0].get("isEndless") is False
        non_brand_preserved = all(
            (char_counter(card.get(field) or []) == char_counter(sent.get(field) or [])
             if field == "characteristics" else card.get(field) == sent.get(field))
            for field in CARD_FIELDS if field != "brand")
        result = {
            "identity_exact": str(card.get("vendorCode") or "") == OFFER
                              and str(card.get("nmID") or "") == NMID,
            "brand_visible": card.get("brand") == BRAND,
            "updatedAt": card.get("updatedAt"),
            "updatedAt_before": state.get("updatedAt_before"),
            "updatedAt_changed": card.get("updatedAt") != state.get("updatedAt_before"),
            "target_document_visible": len(targets) == 1,
            "target_document_metadata_exact": exact_metadata,
            "target_document_verdict": targets[0].get("verdict") if targets else None,
            "prior_documents_preserved": docs_counter(prior_actual) == docs_counter(prior_docs),
            "excludeDocuments": container.get("excludeDocuments"),
            "all_non_brand_fields_preserved": non_brand_preserved,
        }
    result["all_pilot_changes_visible"] = bool(
        result.get("identity_exact") and result.get("brand_visible")
        and result.get("target_document_metadata_exact") and result.get("prior_documents_preserved")
        and result.get("excludeDocuments") is False and result.get("all_non_brand_fields_preserved"))
    history_path = BASE / OUT
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {
        "offer_id": OFFER, "nmID": NMID, "number": WB_NUMBER, "attempts": []}
    attempt = {"checked_at_utc": now(), **result}
    history["attempts"].append(attempt)
    history["latest"] = attempt
    history["all_pilot_changes_visible"] = result["all_pilot_changes_visible"]
    save(OUT, history)
    state.setdefault("verification_attempts", []).append(attempt)
    state["latest_verification"] = attempt
    save(EXEC.name, state)
    print(json.dumps({"artifact": str(history_path), **attempt}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
