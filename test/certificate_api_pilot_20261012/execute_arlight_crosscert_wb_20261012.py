"""Append both verified Arlight document rows to eligible WB cards in one full-card update."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
PLAN = BASE / "arlight_crosscert_wb_plan_prewrite_20261012.json"
RUN = BASE / "arlight_crosscert_wb_execution_20261012.json"
DECLARATION = "ЕАЭС N RU Д-RU.РА08.В.41382/26"
CERTIFICATE = "ЕАЭС RU С-RU.НК50.В.00356/26"
CARD_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
               "characteristics", "sizes", "kizMarked", "gtin")


def save(value: dict) -> None:
    tmp = RUN.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(RUN)


def main() -> None:
    if RUN.exists():
        raise RuntimeError("WB update was already attempted; reconcile live cards before any retry")
    plan = json.loads(PLAN.read_text())
    updates = plan.get("updates") or []
    counts = plan.get("counts") or {}
    if (len(plan.get("documents") or []) != 2 or not updates
            or counts.get("wb_cards_to_update") != len(updates)
            or counts.get("document_rows_to_add") != len(updates) * 2
            or counts.get("conflicts") != 0 or plan.get("local_cleanup_allowed") is not False):
        raise RuntimeError("WB plan is empty, conflicted, or does not preserve the reviewed exact scope")
    payloads = []
    for row in updates:
        offer = row.get("offer_id")
        before, payload = row.get("before") or {}, row.get("payload") or {}
        if (before.get("vendorCode") != offer or payload.get("vendorCode") != offer
                or str(before.get("nmID")) != str(row.get("nmID"))
                or str(payload.get("nmID")) != str(row.get("nmID"))):
            raise RuntimeError("WB card identity mismatch in plan: " + str(offer))
        if any(payload.get(field) != before.get(field) for field in CARD_FIELDS):
            raise RuntimeError("WB plan changes an unrelated card field: " + str(offer))
        doc_container = payload.get("documents") or {}
        if doc_container.get("excludeDocuments") is not False:
            raise RuntimeError("WB plan does not enable document attachment: " + str(offer))
        items = doc_container.get("items") or []
        numbers = [x.get("number") for x in items if x.get("number") in {DECLARATION, CERTIFICATE}]
        if numbers.count(DECLARATION) != 1 or numbers.count(CERTIFICATE) != 1:
            raise RuntimeError("WB plan must append exactly one row for each verified document: " + str(offer))
        old_docs = (before.get("documents") or {}).get("items") or []
        old_numbers = [x.get("number") for x in old_docs]
        if [x for x in items if x.get("number") not in {DECLARATION, CERTIFICATE}] != [
                {key: value for key, value in doc.items() if key not in {"verdict", "createdAt", "updatedAt"}}
                for doc in old_docs]:
            raise RuntimeError("WB plan changed or dropped existing document rows: " + str(offer))
        if row.get("set_exclude_documents_false") != ((before.get("documents") or {}).get("excludeDocuments") is not False):
            raise RuntimeError("WB document-exclusion transition is not recorded accurately: " + str(offer))
        payloads.append(payload)
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    sha = hashlib.sha256(encoded).hexdigest()
    if sha != plan.get("payload_sha256") or len(encoded) > 10_000_000 or len(payloads) > 1000:
        raise RuntimeError("WB payload differs from its reviewed hash or exceeds endpoint limits")
    state = {"started_at": now(), "phase": "prepared",
             "documents": [DECLARATION, CERTIFICATE], "cards": len(payloads),
             "document_rows_added": len(payloads) * 2,
             "documents_enabled_on_cards": counts.get("cards_where_documents_will_be_enabled"),
             "cards_excluded_for_wb_tnved_conflict": counts.get("excluded_wb_tnved_conflict"),
             "preserved_all_full_card_fields": list(CARD_FIELDS),
             "payload_bytes": len(encoded), "payload_sha256": sha,
             "preserved_existing_document_rows": True,
             "wb_before_snapshot": plan.get("evidence", {}).get("wb_fullcard_read"),
             "wb_documents_left_for_review": True}
    save(state)
    state.update({"phase": "update_sent", "sent_at": now()})
    save(state)
    try:
        response = Client().call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(state)
        raise RuntimeError("WB update outcome uncertain; read current cards before any retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state.update({"phase": "response_error", "updated_at": now()})
        save(state)
        raise RuntimeError("WB did not accept the full-card update; reconcile before another write")
    state.update({"phase": "accepted_waiting_for_review", "accepted_at": now(),
                  "after_readback_required": True})
    save(state)
    print(json.dumps({k: state[k] for k in (
        "phase", "documents", "cards", "document_rows_added", "documents_enabled_on_cards",
        "cards_excluded_for_wb_tnved_conflict", "payload_bytes", "payload_sha256", "response",
        "wb_documents_left_for_review")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
