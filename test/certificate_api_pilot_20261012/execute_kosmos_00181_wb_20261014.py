"""Attach Kosmos 00181/25 to exact in-scope WB cards; never touches Ozon."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))

from api_client import Client, now, digest  # noqa: E402
from execute_arlight_05783_20261014 import (  # noqa: E402
    DOC_FIELDS, DOC_READ_ONLY_FIELDS, WB_UPDATE_FIELDS, read_wb_cards, wb_codes,
)
from preflight_kosmos_00181_20261014 import (  # noqa: E402
    ALLOWED_TNVED, EXTRACT, FSA_ID, FSA_URL, NUMBER, OUT as OLD_PREFLIGHT,
    SHA256, offer_model, read_source,
)

PREFLIGHT = BASE / "kosmos_00181_live_preflight_20261014_v2.json"
RUN = BASE / "kosmos_00181_wb_execution_20261014.json"
ISSUE = "2025-06-23"
EXPIRY = "2030-06-22"
EXPECTED_OFFERS = 58
WB_HOST = "https://content-api.wildberries.ru"


def save(value: dict) -> None:
    temporary = RUN.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(RUN)


def doc_items(card: dict) -> list[dict]:
    container = card.get("documents") or card.get("docs") or {}
    return container.get("items") or []


def clean_doc_items(card: dict) -> list[dict]:
    output = []
    for row in doc_items(card):
        unknown = set(row) - set(DOC_FIELDS) - DOC_READ_ONLY_FIELDS
        if unknown:
            raise RuntimeError("WB document row has unknown fields: " + ", ".join(sorted(unknown)))
        output.append({key: copy.deepcopy(row[key]) for key in DOC_FIELDS if key in row})
    return output


def card_payload(card: dict) -> dict:
    required = set(WB_UPDATE_FIELDS[:-1])
    payload = {key: copy.deepcopy(card[key]) for key in WB_UPDATE_FIELDS if key in card}
    missing = required - payload.keys()
    if missing:
        raise RuntimeError("WB card lacks fields required for full update: " + ", ".join(sorted(missing)))
    container = card.get("documents") or card.get("docs") or {}
    if container.get("excludeDocuments") is True:
        raise RuntimeError("WB card excludes documents; stop before update")
    if any(str(row.get("number") or "").casefold() == NUMBER.casefold() for row in doc_items(card)):
        raise RuntimeError("Exact Kosmos 00181/25 row already exists; reconcile instead")
    certificate = {"type": 1, "number": NUMBER, "startDate": ISSUE + "T00:00:00Z",
                   "endDate": EXPIRY + "T00:00:00Z", "isEndless": False}
    payload["documents"] = {"items": clean_doc_items(card) + [certificate],
                            "excludeDocuments": False}
    if any(payload.get(key) != card.get(key) for key in WB_UPDATE_FIELDS if key in card):
        raise RuntimeError("Full-card payload changed an unrelated WB field")
    return payload


def main() -> None:
    if RUN.exists():
        raise RuntimeError("WB operation journal already exists; reconcile before any retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("fsa_record_id") != FSA_ID:
        raise RuntimeError("Fresh source preflight is malformed")
    checked = dt.datetime.fromisoformat(pre["checked_at_utc"])
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 600:
        raise RuntimeError("Live preflight is older than ten minutes")
    if digest(EXTRACT) != SHA256:
        raise RuntimeError("Official FSA extract hash changed")
    offers, source, mappings = read_source()
    if len(offers) != EXPECTED_OFFERS or len(set(offers)) != EXPECTED_OFFERS:
        raise RuntimeError("Source mapping no longer contains exactly 58 unique offers")
    if source["sha256"] != SHA256:
        raise RuntimeError("Source file does not match the official FSA extract hash")
    if set(pre.get("offers") or []) != set(offers):
        raise RuntimeError("Live preflight target set differs from the source manifest")
    if len(pre.get("ozon_products") or []) != EXPECTED_OFFERS:
        raise RuntimeError("Ozon live preflight is incomplete")
    for product in pre["ozon_products"]:
        codes = {str(value).split(" - ", 1)[0].strip()
                 for value in product.get("tnved_values") or [] if str(value).strip()}
        if product.get("brand_values") != ["Космос"] or codes & ALLOWED_TNVED:
            raise RuntimeError("Ozon brand or TN VED changed; revisit whether it is in scope")

    wb_rows = pre.get("wb_cards_by_offer") or []
    if len(wb_rows) != EXPECTED_OFFERS:
        raise RuntimeError("WB live preflight is incomplete")
    prior_cards = {}
    for row in wb_rows:
        offer = row.get("offer_id")
        cards = row.get("cards") or []
        if offer not in mappings or len(cards) != 1:
            raise RuntimeError("WB exact card missing or ambiguous for " + str(offer))
        card = cards[0]
        if str(card.get("vendorCode") or "") != offer or not str(card.get("nmID") or ""):
            raise RuntimeError("WB card identity mismatch for " + str(offer))
        if card.get("brand") != "Космос" or wb_codes(card) != ["8539520009"]:
            raise RuntimeError("WB brand or TN VED is not an exact in-scope match for " + offer)
        if str(card.get("documents", {}).get("excludeDocuments")).lower() == "true":
            raise RuntimeError("WB excludes documents for " + offer)
        prior_cards[offer] = card
    if len(prior_cards) != EXPECTED_OFFERS:
        raise RuntimeError("WB exact-card set is not unique")

    # Re-read every card immediately before preparing the only marketplace write.
    client = Client()
    cards = {}
    for index, offer in enumerate(offers, 1):
        found = read_wb_cards(client, offer)
        old = prior_cards[offer]
        if (len(found) != 1 or str(found[0].get("nmID") or "") != str(old.get("nmID") or "")
                or str(found[0].get("vendorCode") or "") != offer):
            raise RuntimeError("Fresh WB card identity changed for " + offer)
        card = found[0]
        if card.get("brand") != "Космос" or wb_codes(card) != ["8539520009"]:
            raise RuntimeError("Fresh WB brand or TN VED changed for " + offer)
        if str(card.get("documents", {}).get("excludeDocuments")).lower() == "true":
            raise RuntimeError("Fresh WB card excludes documents for " + offer)
        # Seller article is the exact source mapping; a few WB model attributes are blank.
        if not mappings.get(offer, {}).get("Основание сопоставления"):
            raise RuntimeError("Source mapping lacks model-scope rationale for " + offer)
        cards[offer] = card
        if index % 10 == 0 or index == len(offers):
            print(f"WB final prewrite reread {index}/{len(offers)}", flush=True)

    payloads = []
    before = []
    for offer in offers:
        card = cards[offer]
        payload = card_payload(card)
        payloads.append(payload)
        before.append({"offer_id": offer, "nmID": str(card["nmID"]), "card": card,
                       "payload": payload})
    if len(payloads) != EXPECTED_OFFERS:
        raise RuntimeError("Prepared WB write set is incomplete")

    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_sha = hashlib.sha256(encoded).hexdigest()
    if len(encoded) > 10_000_000:
        raise RuntimeError("WB batch exceeds conservative request-size limit")
    state = {
        "started_at_utc": now(), "phase": "prewrite_verified",
        "number": NUMBER, "document_type": "certificate_of_conformity",
        "issue_date": ISSUE, "expire_date": EXPIRY,
        "official_registry_url": FSA_URL, "official_registry_id": FSA_ID,
        "official_registry_status_observed_in_open_fsa_tab": "Действует",
        "official_registry_status_read_at_utc": now(),
        "source_file": {"path": str(EXTRACT), "sha256": SHA256, "bytes": EXTRACT.stat().st_size},
        "target_count": EXPECTED_OFFERS, "wb_cards": len(payloads),
        "ozon_write_skipped": True,
        "ozon_reason": "All 58 current Ozon TN VED values are outside/missing from the two exact FSA codes; no exact Ozon record exists.",
        "wb_tnved_counts": {"8539520009": EXPECTED_OFFERS},
        "wb_missing_or_ambiguous_cards": 0,
        "wb_prewrite_exact_document_rows": 0,
        "preserved_full_card_fields": list(WB_UPDATE_FIELDS),
        "preserved_existing_document_rows": True,
        "payload_bytes": len(encoded), "payload_sha256": payload_sha,
        "wb_payloads": payloads, "wb_before": before,
        "update_attempts": 0, "local_cleanup_allowed": False,
    }
    save(state)
    state.update({"phase": "wb_update_sent", "update_attempts": 1, "sent_at_utc": now()})
    save(state)
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "wb_update_uncertain_reconcile_only",
                      "error_type": type(exc).__name__, "local_cleanup_allowed": False})
        save(state)
        raise RuntimeError("WB update outcome is uncertain; reconcile live state before retry") from None
    state["response"] = {"error": response.get("error"), "errorText": response.get("errorText"),
                         "additionalErrors": response.get("additionalErrors")}
    if response.get("error") is not False:
        state.update({"phase": "wb_update_response_error_reconcile_only",
                      "local_cleanup_allowed": False})
        save(state)
        raise RuntimeError("WB rejected or ambiguously accepted the update; do not resend")
    state.update({"phase": "accepted_waiting_for_readback", "accepted_at_utc": now()})
    save(state)

    readback = []
    for index, old in enumerate(before, 1):
        found = read_wb_cards(client, old["offer_id"])
        if len(found) != 1 or str(found[0].get("nmID") or "") != old["nmID"]:
            readback.append({"offer_id": old["offer_id"], "nmID_expected": old["nmID"],
                             "card_count": len(found), "exact_row_count": 0})
            continue
        card = found[0]
        rows = [row for row in doc_items(card)
                if str(row.get("number") or "").casefold() == NUMBER.casefold()]
        exact = [row for row in rows if int(row.get("type") or 0) == 1
                 and str(row.get("startDate") or "")[:10] == ISSUE
                 and str(row.get("endDate") or "")[:10] == EXPIRY
                 and row.get("isEndless") is False]
        fields_preserved = all(card.get(key) == old["payload"].get(key)
                               for key in WB_UPDATE_FIELDS if key in old["payload"])
        current_clean_docs = clean_doc_items(card)
        expected_existing_docs = [row for row in old["payload"]["documents"]["items"]
                                  if str(row.get("number") or "").casefold() != NUMBER.casefold()]
        observed_existing_docs = [row for row in current_clean_docs
                                  if str(row.get("number") or "").casefold() != NUMBER.casefold()]
        existing_docs_preserved = observed_existing_docs == expected_existing_docs
        readback.append({"offer_id": old["offer_id"], "nmID": str(card.get("nmID") or ""),
                         "exact_row_count": len(exact), "matching_number_row_count": len(rows),
                         "verdict": exact[0].get("verdict") if len(exact) == 1 else None,
                         "excludeDocuments": (card.get("documents") or {}).get("excludeDocuments"),
                         "tnved_codes": wb_codes(card),
                         "all_full_card_fields_preserved": fields_preserved,
                         "all_document_rows_preserved": existing_docs_preserved})
        if index % 10 == 0 or index == len(before):
            print(f"WB post-update readback {index}/{len(before)}", flush=True)
    visible = sum(x.get("exact_row_count") == 1 and x.get("matching_number_row_count") == 1
                  for x in readback)
    fields = sum(x.get("all_full_card_fields_preserved") is True for x in readback)
    docs = sum(x.get("all_document_rows_preserved") is True for x in readback)
    state.update({"phase": "wb_readback_complete" if visible == EXPECTED_OFFERS else "wb_sync_pending",
                  "readback_at_utc": now(), "readback_target_count": len(readback),
                  "exact_rows_visible": visible, "full_card_fields_preserved_count": fields,
                  "document_rows_preserved_count": docs, "wb_readback": readback,
                  "wb_review_left_to_marketplace": True,
                  "local_cleanup_allowed": False})
    save(state)
    print(json.dumps({k: state[k] for k in (
        "phase", "number", "target_count", "exact_rows_visible",
        "full_card_fields_preserved_count", "document_rows_preserved_count",
        "response", "ozon_write_skipped", "wb_review_left_to_marketplace",
        "local_cleanup_allowed")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
