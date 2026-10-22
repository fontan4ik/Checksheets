"""Remove only bulk-projected 15150/25 rows from WB cards with out-of-scope TN VED."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    UPDATE_CARD_FIELDS, comparable_card, copy_documents, doc_key, norm_number,
)

BULK_READBACK = HERE / "all_found_wb_readback_9ad97e303805b13c.json"
BULK_DELAYED_READBACK = HERE / "all_found_coverage_delayed_wb_readback_20261021.json"
BULK_BEFORE = HERE / "all_found_wb_cards_snapshot_20261014.json"
PREFLIGHT = HERE / "stekker_15150_crossplatform_preflight_live_20261021.json"
STATE = HERE / "stekker_15150_wb_scope_correction_20261021.json"
BEFORE = HERE / "stekker_15150_wb_scope_correction_before_20261021.json"
READBACK = HERE / "stekker_15150_wb_scope_correction_readback_20261021.json"
JOURNAL = HERE / "stekker_15150_wb_scope_correction_journal_20261021.jsonl"
NUMBER = "ЕАЭС N RU Д-CN.РА07.В.15150/25"
ISSUE = "2025-08-25"
EXPIRY = "2030-08-24"
OUT_OF_SCOPE_CODE = "8536508008"


def tnved(card: dict) -> list[str]:
    result = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        result.extend(str(x or "").split(" - ", 1)[0].strip() for x in values if x)
    return sorted(set(result))


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def save(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def main() -> None:
    if any(path.exists() for path in (STATE, BEFORE, READBACK, JOURNAL)):
        raise RuntimeError("scope_correction_artifact_exists_reconcile_first")
    bulk = json.loads(BULK_READBACK.read_text(encoding="utf-8"))
    delayed = json.loads(BULK_DELAYED_READBACK.read_text(encoding="utf-8"))
    full_before = json.loads(BULK_BEFORE.read_text(encoding="utf-8"))
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    old_by_offer = {str(card.get("vendorCode") or ""): card for card in full_before.get("cards") or []}
    if (bulk.get("wb_review_left_pending") is not True or len(bulk.get("results") or []) != 68
            or delayed.get("complete") is not True):
        raise RuntimeError("unexpected_bulk_readback_state")
    wb_scope = {str(row.get("offer_id")): row for row in pre.get("wb_targets") or []}
    added_by_offer = {}
    for row in bulk["results"]:
        offer = str(row.get("offer_id") or "")
        cards = row.get("cards") or []
        if len(cards) != 1:
            continue
        card = cards[0]
        added = [doc for doc in ((card.get("documents") or {}).get("items") or [])
                 if norm_number(doc.get("number")) == norm_number(NUMBER)]
        if tnved(card) == [OUT_OF_SCOPE_CODE] and added:
            added_by_offer[offer] = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                                     "bulk_number_items": added}
    for row in delayed.get("results") or []:
        if (not row.get("readback_verified") or str(row.get("offer_id") or "") in added_by_offer
                or not row.get("expected_documents")):
            continue
        if any(norm_number(item.get("number")) == norm_number(NUMBER) and item.get("exact") is True
               for item in row["expected_documents"]):
            added_by_offer[str(row["offer_id"])] = {"offer_id": str(row["offer_id"]),
                                                     "nmID": str(row.get("nmID") or ""),
                                                     "bulk_number_items": []}
    candidates = list(added_by_offer.values())
    if len(candidates) != 67:
        raise RuntimeError(f"unexpected_out_of_scope_card_count:{len(candidates)}")
    if any(wb_scope.get(row["offer_id"], {}).get("safe_for_update") is True for row in candidates):
        raise RuntimeError("one_candidate_was_in_original_safe_wb_scope")
    if any(row["offer_id"] not in old_by_offer for row in candidates):
        raise RuntimeError("original_wb_snapshot_missing_candidate")

    client = Client()
    prepared = []
    skipped = []
    for candidate in candidates:
        offer = candidate["offer_id"]
        cards = client.wb_cards(offer)
        old_card = old_by_offer[offer]
        if len(cards) != 1:
            skipped.append({"offer_id": offer, "reason": "live_card_missing_or_ambiguous"})
            continue
        card = cards[0]
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != candidate["nmID"]
                or str(card.get("nmID") or "") != str(old_card.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "stekker"
                or tnved(card) != [OUT_OF_SCOPE_CODE]):
            skipped.append({"offer_id": offer, "reason": "live_identity_brand_or_scope_changed"})
            continue
        docs = copy_documents(card)
        same = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        exact = [doc for doc in same if doc_key(doc) == (2, norm_number(NUMBER))
                 and str(doc.get("startDate", ""))[:10] == ISSUE
                 and str(doc.get("endDate", ""))[:10] == EXPIRY
                 and doc.get("isEndless") is False]
        if len(same) != 1 or len(exact) != 1:
            skipped.append({"offer_id": offer, "reason": "live_added_row_missing_or_conflicting"})
            continue
        old_items = copy_documents(old_card)
        old_same = [doc for doc in old_items if norm_number(doc.get("number")) == norm_number(NUMBER)]
        if old_same:
            skipped.append({"offer_id": offer, "reason": "document_preexisted_before_bulk_write"})
            continue
        kept = [doc for doc in docs if norm_number(doc.get("number")) != norm_number(NUMBER)]
        payload = {key: card[key] for key in UPDATE_CARD_FIELDS if key in card}
        payload["documents"] = {"items": kept, "excludeDocuments": False}
        if payload.get("nmID") != card.get("nmID") or payload.get("vendorCode") != offer:
            raise RuntimeError("correction_payload_identity_mismatch")
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]), "before": card,
                         "payload": payload,
                         "kept_document_signatures": [signature(doc) for doc in docs if doc not in exact]})

    if len(prepared) != 67 or skipped:
        save(STATE, {"started_at": now(), "phase": "prewrite_recheck_incomplete",
                     "candidate_count": len(candidates), "prepared_count": len(prepared),
                     "skipped": skipped, "mutation_sent": False,
                     "source_pdf_deleted": False})
        raise RuntimeError("scope_correction_prewrite_recheck_incomplete")
    save(BEFORE, {"checked_at": now(), "number_removed": NUMBER,
                  "out_of_scope_tnved": OUT_OF_SCOPE_CODE, "complete": True,
                  "candidate_count": len(candidates), "prepared_count": len(prepared),
                  "cards": [row["before"] for row in prepared]})
    state = {"started_at": now(), "phase": "prewrite_verified", "number_removed": NUMBER,
             "reason": "WB TN VED 8536508008 is outside the official FSA code list",
             "candidate_count": len(candidates), "prepared_count": len(prepared),
             "mutation_sent": False, "local_file_deleted": False}
    save(STATE, state)
    payloads = [row["payload"] for row in prepared]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 9_000_000 or len(payloads) > 1000:
        raise RuntimeError("scope_correction_batch_limit_exceeded")
    marker = hashlib.sha256(encoded).hexdigest()
    append({"phase": "prepared", "at": now(), "platform": "wb",
            "endpoint": "/content/v2/cards/update", "cards": len(payloads),
            "payload_bytes": len(encoded), "sha256": marker})
    state.update(phase="wb_correction_sent", mutation_sent=True,
                 payload_sha256=marker, updated_at=now())
    save(STATE, state)
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update(phase="wb_correction_uncertain", error_type=type(exc).__name__, updated_at=now())
        save(STATE, state)
        raise RuntimeError("correction_uncertain_reconcile_live_before_retry") from None
    append({"phase": "response", "at": now(), "response": response,
            "cards": len(payloads), "sha256": marker})
    if response.get("error") is not False or response.get("additionalErrors"):
        state.update(phase="wb_correction_rejected", response=response, updated_at=now())
        save(STATE, state)
        raise RuntimeError("wb_scope_correction_rejected")

    old_by_offer = {row["offer_id"]: row["before"] for row in prepared}
    kept_by_offer = {row["offer_id"]: collections.Counter(row["kept_document_signatures"])
                     for row in prepared}
    results = []
    for row in prepared:
        offer = row["offer_id"]
        live = client.wb_cards(offer)
        if len(live) != 1:
            results.append({"offer_id": offer, "verified": False, "reason": "live_card_missing_or_ambiguous"})
            continue
        card = live[0]
        docs = copy_documents(card)
        remaining = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        actual_sigs = collections.Counter(signature(doc) for doc in docs)
        kept = kept_by_offer[offer]
        preserved_docs = all(actual_sigs[sig] >= count for sig, count in kept.items())
        fields = comparable_card(card) == comparable_card(old_by_offer[offer])
        okay = (str(card.get("vendorCode") or "") == offer
                and str(card.get("nmID") or "") == row["nmID"]
                and tnved(card) == [OUT_OF_SCOPE_CODE]
                and not remaining and preserved_docs and fields)
        results.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "verified": okay, "target_document_removed": not remaining,
                        "prior_documents_preserved": preserved_docs,
                        "unrelated_card_fields_preserved": fields,
                        "remaining_target_document_count": len(remaining)})
    failures = [row for row in results if not row.get("verified")]
    readback = {"checked_at": now(), "complete": not failures and len(results) == len(prepared),
                "number_removed": NUMBER, "out_of_scope_tnved": OUT_OF_SCOPE_CODE,
                "cards_requested": len(prepared), "cards_verified": len(results) - len(failures),
                "failures": failures, "results": results, "source_pdf_deleted": False}
    save(READBACK, readback)
    state.update(phase="verified_complete" if not failures else "readback_incomplete",
                 cards_requested=len(prepared), cards_verified=len(results) - len(failures),
                 failures=failures, readback_path=str(READBACK), updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "cards_requested": len(prepared),
                      "cards_verified": len(results) - len(failures), "failures": failures,
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError("scope_correction_readback_incomplete")


if __name__ == "__main__":
    main()
