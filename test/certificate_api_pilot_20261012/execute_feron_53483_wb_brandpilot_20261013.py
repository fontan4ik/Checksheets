"""Controlled one-card Feron brand plus document pilot on WB."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now, save
from feron_53483_crossplatform_20261013 import CARD_FIELDS, EXPIRY, ISSUE, WB_NUMBER, clean_wb_doc, norm
from verify_alphacable_00103_wb_20261013 import char_counter

OZON_EXEC = BASE / "feron_53483_ozon_execution_20261013.json"
WB_EXEC = BASE / "feron_53483_wb_execution_20261013.json"
OUT = "feron_53483_wb_brandpilot_20261013.json"
OFFER = "21488-1"
NMID = "461059396"
BRAND = "Feron"
BRAND_ID = 11769
SUBJECT_ID = 3081


def main() -> None:
    if (BASE / OUT).exists():
        raise RuntimeError("Brand pilot journal already exists; reconcile before any retry")
    ozon = json.loads(OZON_EXEC.read_text(encoding="utf-8"))
    ozon_ok = ozon.get("all_target_pairs_visible") and ozon.get("final_record_status") == "approved"
    if not ozon_ok:
        raise RuntimeError("Ozon declaration record and bindings are not confirmed approved")
    prior = json.loads(WB_EXEC.read_text(encoding="utf-8"))
    prior_payloads = {str(x.get("vendorCode") or ""): x for x in prior.get("payload") or []}
    expected_prior = prior_payloads.get(OFFER)
    if not expected_prior or str(expected_prior.get("nmID")) != NMID:
        raise RuntimeError("Earlier accepted WB update lacks the exact pilot card payload")
    client = Client()
    card_list = client.wb_cards(OFFER)
    if len(card_list) != 1:
        raise RuntimeError("Exact WB card is missing or ambiguous")
    card = card_list[0]
    if str(card.get("vendorCode") or "") != OFFER or str(card.get("nmID") or "") != NMID:
        raise RuntimeError("WB card identity changed")
    if int(card.get("subjectID") or -1) != SUBJECT_ID or card.get("subjectName") != "Системы умный дом":
        raise RuntimeError("WB card category changed since preflight")
    if card.get("brand") not in (None, ""):
        raise RuntimeError("WB card brand is no longer blank; reconcile before writing")
    if BRAND.casefold() not in " ".join(str(card.get(k) or "") for k in ("title", "description")).casefold():
        raise RuntimeError("Live WB title/description no longer establish the Feron brand")
    for field in CARD_FIELDS:
        same = (char_counter(card.get(field) or []) == char_counter(expected_prior.get(field) or [])
                if field == "characteristics" else card.get(field) == expected_prior.get(field))
        if not same:
            raise RuntimeError(f"WB card field {field} differs from the last accepted update baseline")
    brands = client.call("wb", f"/api/content/v1/brands?subjectId={SUBJECT_ID}", {}, method="GET")
    brand_matches = [x for x in brands.get("brands") or []
                     if str(x.get("name") or "").casefold() == BRAND.casefold()]
    if len(brand_matches) != 1 or int(brand_matches[0].get("id") or -1) != BRAND_ID:
        raise RuntimeError("WB subject brand directory no longer has the exact Feron brand")
    docs_container = card.get("documents") or card.get("docs") or {}
    if docs_container.get("excludeDocuments") is not False:
        raise RuntimeError("WB card excludes documents or omits the explicit allow flag")
    current_docs = docs_container.get("items") or []
    if any(norm(x.get("number")) == norm(WB_NUMBER) for x in current_docs):
        raise RuntimeError("Target declaration appeared after preflight; stop and reconcile")
    clean_docs = [clean_wb_doc(x) for x in current_docs]
    new_doc = {"type": 2, "number": WB_NUMBER,
               "startDate": ISSUE + "T00:00:00Z", "endDate": EXPIRY + "T00:00:00Z",
               "isEndless": False}
    payload = {field: card[field] for field in CARD_FIELDS if field in card}
    payload["brand"] = BRAND
    payload["documents"] = {"items": clean_docs + [new_doc], "excludeDocuments": False}
    for field in CARD_FIELDS:
        expected = BRAND if field == "brand" else card.get(field)
        same = (char_counter(payload.get(field) or []) == char_counter(expected or [])
                if field == "characteristics" else payload.get(field) == expected)
        if not same:
            raise RuntimeError(f"Unexpected payload modification in {field}")
    encoded = json.dumps([payload], ensure_ascii=False, separators=(",", ":")).encode()
    state = {"prepared_at_utc": now(), "phase": "prepared", "offer_id": OFFER,
             "nmID": NMID, "subjectID": SUBJECT_ID, "brand_before": card.get("brand"),
             "brand_after": BRAND, "brand_id": BRAND_ID, "brand_directory_verified": True,
             "updatedAt_before": card.get("updatedAt"),
             "non_document_fields_changed": ["brand"], "prior_documents_preserved": True,
             "documents_excluded": False, "payload_sha256": hashlib.sha256(encoded).hexdigest(),
             "payload_bytes": len(encoded), "payload": [payload], "mutation_attempts": 0}
    save(OUT, state)
    state.update({"phase": "mutation_started", "mutation_attempts": 1,
                  "sent_at_utc": now()})
    save(OUT, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", [payload], mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__,
                      "updated_at_utc": now()})
        save(OUT, state)
        raise RuntimeError("WB update result uncertain; reconcile live state before retry") from None
    state["response"] = response
    state.update({"phase": "response_received", "updated_at_utc": now()})
    save(OUT, state)
    if response.get("error") is True:
        state.update({"phase": "rejected", "finished_at_utc": now()})
        save(OUT, state)
        raise RuntimeError("WB rejected the update; do not retry before reading back")
    readback = client.wb_cards(OFFER)
    if len(readback) != 1 or str(readback[0].get("nmID") or "") != NMID:
        result = {"identity_exact": False, "readback_count": len(readback)}
    else:
        fresh = readback[0]
        current_container = fresh.get("documents") or fresh.get("docs") or {}
        rows = current_container.get("items") or []
        matching = [x for x in rows if int(x.get("type") or 0) == 2
                    and norm(x.get("number")) == norm(WB_NUMBER)]
        result = {"identity_exact": True, "brand_visible": fresh.get("brand") == BRAND,
                  "updatedAt": fresh.get("updatedAt"),
                  "target_document_visible": len(matching) == 1,
                  "target_document_verdict": matching[0].get("verdict") if matching else None,
                  "prior_documents_preserved": [clean_wb_doc(x) for x in rows if any(
                      x.get(k) != new_doc.get(k) for k in ("type", "number", "startDate", "endDate", "isEndless"))
                      ] == clean_docs,
                  "excludeDocuments": current_container.get("excludeDocuments"),
                  "all_non_brand_fields_preserved": all(
                      (char_counter(fresh.get(k) or []) == char_counter(card.get(k) or [])
                       if k == "characteristics" else
                       fresh.get(k) == card.get(k))
                      for k in CARD_FIELDS if k != "brand")}
    state.update({"immediate_readback_utc": now(), "immediate_readback": result,
                  "phase": "accepted_waiting_for_wb_sync" if response.get("error") is False
                  and (not result.get("target_document_visible") or not result.get("brand_visible"))
                  else "readback_complete", "finished_at_utc": now()})
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "phase": state["phase"],
                      "response": response, "immediate_readback": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
