"""Submit the exact Arlight declaration metadata to WB full cards once."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
PLAN = BASE / "arlight_69060_wb_plan_20261012.json"
RUN = BASE / "arlight_69060_wb_execution_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
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
    if (plan.get("number") != NUMBER or plan.get("document_type") != 2
            or not updates or counts.get("wb_cards_to_update") != len(updates)
            or counts.get("conflicts") != 0 or plan.get("local_cleanup_allowed") is not False):
        raise RuntimeError("WB plan is empty, conflicted, or not the reviewed full-card plan")
    payloads = []
    for row in updates:
        offer = row.get("offer_id")
        before, payload = row.get("before") or {}, row.get("payload") or {}
        if (before.get("vendorCode") != offer or payload.get("vendorCode") != offer
                or str(before.get("nmID")) != str(row.get("nmID"))
                or str(payload.get("nmID")) != str(row.get("nmID"))):
            raise RuntimeError("WB card identity mismatch in plan: " + str(offer))
        if any(payload.get(field) != before.get(field) for field in CARD_FIELDS):
            raise RuntimeError("WB plan changes a non-document card field: " + str(offer))
        if (payload.get("documents", {}).get("excludeDocuments") is not False
                or sum(1 for d in payload.get("documents", {}).get("items", [])
                       if d.get("number") == NUMBER and int(d.get("type", -1)) == 2) != 1):
            raise RuntimeError("WB plan does not append exactly one declaration row: " + str(offer))
        payloads.append(payload)
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    sha = hashlib.sha256(encoded).hexdigest()
    if sha != plan.get("payload_sha256") or len(encoded) > 10_000_000 or len(payloads) > 3000:
        raise RuntimeError("WB payload differs from its reviewed hash or exceeds endpoint limits")
    state = {"started_at": now(), "phase": "prepared", "number": NUMBER,
             "cards": len(payloads), "documents_added": len(payloads),
             "already_present": counts.get("already_present_exact"),
             "excluded_tnved_scope": counts.get("excluded_scope"),
             "preserved_all_full_card_fields": list(CARD_FIELDS),
             "payload_bytes": len(encoded), "payload_sha256": sha,
             "preserved_existing_document_rows": True,
             "wb_before_snapshot": plan.get("evidence", {}).get("wb_fullcard_read")}
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
        "phase", "number", "cards", "documents_added", "already_present",
        "excluded_tnved_scope", "payload_bytes", "payload_sha256", "response")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
