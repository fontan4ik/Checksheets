"""Safely add the verified AlphaCable certificate to seven exact WB cards."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from api_client import BASE, Client, now
from feron_53483_crossplatform_20261013 import CARD_FIELDS, clean_wb_doc, norm, wb_tnved_codes

PREFLIGHT = BASE / "alphacable_00103_live_preflight_20261013.json"
OZON_EXECUTION = BASE / "alphacable_00103_ozon_execution_20261013.json"
OUT = BASE / "alphacable_00103_wb_execution_20261013.json"
NUMBER = "ЕАЭС RU С-RU.АД38.В.00103/25"
OLD_NUMBER = "ЕАЭС RU С-RU.НА39.В.01186/22"
ISSUE = "2025-05-21"
EXPIRY = "2030-05-20"
TYPE = 1  # WB certificate of conformity
MAX_REQUEST_BYTES = 10_000_000


def signature(row: dict) -> tuple:
    return (int(row.get("type") or 0), norm(row.get("number") or ""),
            str(row.get("startDate") or "")[:10], str(row.get("endDate") or "")[:10],
            bool(row.get("isEndless", False)))


def main() -> None:
    if OUT.exists():
        raise RuntimeError("WB execution journal exists; reconcile state before any further write")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    pf_wb = preflight.get("wb", {})
    targets = preflight.get("targets") or []
    if (len(targets) != 7 or not pf_wb.get("all_identities_exact")
            or not pf_wb.get("all_tnved_in_scope") or not pf_wb.get("all_old_document_rows_present")
            or pf_wb.get("new_document_rows_already_present") != 0):
        raise RuntimeError("Saved WB preflight does not prove seven exact, in-scope cards")
    ozon_exec = json.loads(OZON_EXECUTION.read_text(encoding="utf-8"))
    if ozon_exec.get("certificate_id") != 5649888:
        raise RuntimeError("Ozon execution journal does not identify the expected live certificate")
    ozon_verify = ozon_exec.get("verification") or {}
    expected_skus = {str(x["sku"]): str(x["product_id"]) for x in targets}
    ozon_bindings = ozon_verify.get("bindings") or []
    if (len(ozon_bindings) != 7
            or {str(x.get("sku")): str(x.get("product_id")) for x in ozon_bindings} != expected_skus
            or ozon_verify.get("outside_skus") or ozon_verify.get("missing_skus")
            or ozon_verify.get("duplicates") or ozon_verify.get("product_id_mismatches")):
        raise RuntimeError("Ozon exact product/SKU pairs are not all present; WB update stopped")

    client = Client()
    payload = []
    before = []
    for target in targets:
        offer = str(target["offer_id"])
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError(f"WB exact card is missing or ambiguous for {offer}")
        card = cards[0]
        if str(card.get("vendorCode") or "") != offer or str(card.get("nmID") or "") != str(target["nmID"]):
            raise RuntimeError(f"WB card identity changed for {offer}")
        if str(card.get("brand") or "").strip().casefold() != "альфакабель":
            raise RuntimeError(f"WB brand changed or conflicts with AlphaCable for {offer}")
        if wb_tnved_codes(card) != {"8544499509"}:
            raise RuntimeError(f"WB TN VED changed or is outside the verified FSA scope for {offer}")
        docs = card.get("documents") or card.get("docs") or {}
        if docs.get("excludeDocuments") is not False:
            raise RuntimeError(f"WB document inclusion flag is not explicitly false for {offer}")
        current_docs = docs.get("items") or []
        unknown = [key for doc in current_docs for key in set(doc) - {
            "id", "type", "number", "productNumber", "tradeName", "applicant", "startDate", "endDate",
            "isEndless", "verdict", "createdAt", "updatedAt"}]
        if unknown:
            raise RuntimeError(f"Unknown WB document fields found for {offer}")
        old_rows = [d for d in current_docs if norm(d.get("number")) == norm(OLD_NUMBER)]
        if not old_rows:
            raise RuntimeError(f"Expected existing invalid certificate row is missing for {offer}")
        if any(signature(d) == (TYPE, norm(NUMBER), ISSUE, EXPIRY, False) for d in current_docs):
            raise RuntimeError(f"New certificate already appeared for {offer}; reconcile instead of update")
        required_fields = [key for key in CARD_FIELDS[:-1] if key not in card]
        if required_fields:
            raise RuntimeError(f"WB card response omitted full-card fields for {offer}: {required_fields}")
        clean_docs = [clean_wb_doc(d) for d in current_docs]
        new_doc = {"type": TYPE, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
        update = {key: card[key] for key in CARD_FIELDS if key in card}
        update["documents"] = {"items": clean_docs + [new_doc], "excludeDocuments": False}
        for key in CARD_FIELDS:
            if key in card and update.get(key) != card.get(key):
                raise RuntimeError(f"Prepared WB update changes a non-document field for {offer}: {key}")
        payload.append(update)
        before.append({"offer_id": offer, "nmID": str(card["nmID"]), "brand": card.get("brand"),
                       "tnved_codes": sorted(wb_tnved_codes(card)), "updatedAt": card.get("updatedAt"),
                       "old_invalid_document_rows": len(old_rows), "document_count_before": len(current_docs),
                       "excludeDocuments": False})

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payload) != 7 or len(encoded) > MAX_REQUEST_BYTES:
        raise RuntimeError("WB full-card batch failed its size/target-count guard")
    state = {"prepared_at_utc": now(), "phase": "prepared", "number": NUMBER,
             "document_type": "certificate_of_conformity", "source_number": NUMBER,
             "issue_date": ISSUE, "expiry_date": EXPIRY, "target_count": len(payload),
             "targets": before, "fields_preserved": list(CARD_FIELDS),
             "preexisting_documents_preserved": True, "excludeDocuments": False,
             "payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded),
             "payload": payload, "mutation_attempts": 0}
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    state.update({"phase": "mutation_started", "mutation_attempts": 1, "sent_at_utc": now()})
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "finished_at_utc": now()})
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("WB update outcome uncertain; read all seven cards before any retry") from None
    state.update({"phase": "accepted_waiting_for_wb_sync" if response.get("error") is False else "rejected",
                  "response": response, "finished_at_utc": now()})
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": state["phase"], "target_count": state["target_count"],
                      "mutation_attempts": state["mutation_attempts"], "payload_sha256": state["payload_sha256"],
                      "response": response, "execution": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
