"""Attach Stekker declaration 15150/25 to freshly verified WB cards."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from execute_stekker_15150_ozon_20261021 import eligible as ozon_eligible, live_check, save, digest  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

PREFLIGHT = HERE / "stekker_15150_crossplatform_preflight_live_20261021.json"
OZON_STATE = HERE / "stekker_15150_ozon_execution_20261021.json"
OZON_RECOVERY = HERE / "stekker_15150_ozon_recovery_20261021.json"
OZON_LIVE_PROOF = HERE / "stekker_15150_ozon_live_eligibility_20261021.json"
STATE = HERE / "stekker_15150_wb_execution_20261021.json"
BEFORE = HERE / "stekker_15150_wb_before_20261021.json"
READBACK = HERE / "stekker_15150_wb_readback_20261021.json"
JOURNAL = HERE / "stekker_15150_wb_mutation_journal_20261021.jsonl"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/stekker/c3e79720d30db2f7da55a3cf.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА07.В.15150/25"
ISSUE = "2025-08-25"
EXPIRY = "2030-08-24"
ALLOWED_TNVED = {"8536500700", "8536691000", "8536699008", "8504405500"}


def card_tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values.extend(str(x or "").split(" - ", 1)[0].strip()
                      for x in (raw if isinstance(raw, list) else [raw]) if x)
    return sorted(set(values))


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def doc_status(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "", "valid"):
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def append_journal(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def main() -> None:
    if any(path.exists() for path in (STATE, BEFORE, READBACK, JOURNAL)):
        raise RuntimeError("wb_execution_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    ozon = json.loads(OZON_STATE.read_text(encoding="utf-8"))
    ozon_recovery = json.loads(OZON_RECOVERY.read_text(encoding="utf-8"))
    ozon_proof = json.loads(OZON_LIVE_PROOF.read_text(encoding="utf-8"))
    targets_by_offer = {str(x["offer_id"]): x for x in pre.get("ozon_targets") or []}
    wanted_rows = [x for x in pre.get("wb_targets") or [] if x.get("safe_for_update") is True]
    wanted = {str(x["offer_id"]): x for x in wanted_rows}
    if (pre.get("number") != NUMBER or digest(SOURCE) != pre.get("source_pdf_sha256")
            or len(wanted) != 303 or len(wanted_rows) != 303
            or ozon.get("certificate_info", {}).get("status_code") != "approved"
            or int(ozon.get("certificate_id") or 0) != int(ozon_recovery.get("certificate_id") or -1)
            or ozon_recovery.get("verified_bound_count") != 370
            or ozon_recovery.get("phase") != "verified_complete_except_missing_sku"
            or ozon_proof.get("complete") is not True):
        raise RuntimeError("ozon_verification_or_wb_target_precondition_failed")
    for offer in wanted:
        if offer not in targets_by_offer or not ozon_eligible(targets_by_offer[offer]):
            raise RuntimeError("wb_target_not_in_verified_ozon_scope:" + offer)

    client = Client()
    fresh_scope = live_check(client, [targets_by_offer[offer] for offer in sorted(wanted)])
    fresh_by_offer = {row["offer_id"]: row for row in fresh_scope}
    if (len(fresh_by_offer) != len(wanted)
            or set(fresh_by_offer) != set(wanted)
            or any(not row.get("eligible_now") for row in fresh_scope)):
        raise RuntimeError("fresh_ozon_scope_check_failed_for_wb")

    desired = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
               "endDate": wb_datetime(EXPIRY), "isEndless": False}
    before_cards = []
    prepared = []
    skipped = []
    already_exact = []
    for index, (offer, expected) in enumerate(sorted(wanted.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            skipped.append({"offer_id": offer, "reason": "missing_or_duplicate_exact_card",
                            "card_count": len(cards)})
            continue
        card = cards[0]
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or str(expected.get("nmID") or "") != str(expected.get("expected_nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "stekker"):
            skipped.append({"offer_id": offer, "reason": "live_identity_brand_or_nmID_changed"})
            continue
        codes = card_tnved(card)
        if codes and not set(codes) <= ALLOWED_TNVED:
            skipped.append({"offer_id": offer, "reason": "live_tnved_conflict", "tnved_codes": codes})
            continue
        if not codes and not fresh_by_offer[offer]["eligible_now"]:
            skipped.append({"offer_id": offer, "reason": "blank_wb_tnved_without_live_ozon_scope"})
            continue
        docs = copy_documents(card)
        same = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        if same:
            exact = [doc for doc in same if doc_key(doc) == doc_key(desired)
                     and str(doc.get("startDate", ""))[:10] == ISSUE
                     and str(doc.get("endDate", ""))[:10] == EXPIRY
                     and doc.get("isEndless") is False]
            if len(same) == 1 and len(exact) == 1:
                already_exact.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                      "status": doc_status(exact[0]), "verdict": exact[0].get("verdict")})
            else:
                skipped.append({"offer_id": offer, "reason": "existing_document_metadata_conflict"})
            continue
        payload = runner.merge_wb(card, [desired])
        if not payload:
            skipped.append({"offer_id": offer, "reason": "no_missing_document_to_add"})
            continue
        before_cards.append(card)
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]), "before": card,
                         "payload": payload, "prior_document_signatures": [signature(doc) for doc in docs],
                         "tnved_basis": "exact_WB_TNVED" if codes else "same_offer_live_Ozon_TNVED_and_brand"})
        if index % 50 == 0:
            print(json.dumps({"phase": "fresh_wb_card_preflight", "checked": index,
                              "of": len(wanted), "safe_to_write": len(prepared),
                              "skipped": len(skipped)}, ensure_ascii=False), flush=True)

    save(BEFORE, {"checked_at": now(), "complete": True, "number": NUMBER,
                  "catalog_preflight_cards": len(wanted), "update_count": len(prepared),
                  "already_exact_count": len(already_exact), "skipped": skipped,
                  "cards": before_cards})
    state = {"started_at": now(), "phase": "wb_fresh_snapshot_complete", "number": NUMBER,
             "ozon_certificate_id": ozon.get("certificate_id"),
             "ozon_verified_target_pairs": ozon_recovery.get("verified_bound_count"),
             "wb_preflight_safe_target_count": len(wanted), "wb_update_count": len(prepared),
             "wb_already_exact_count": len(already_exact), "wb_skipped_count": len(skipped),
             "wb_skipped": skipped, "wb_review_left_to_wb": True,
             "local_file_deleted": False, "document": desired, "writes_sent": 0}
    save(STATE, state)

    if prepared:
        payloads = [row["payload"] for row in prepared]
        encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > 9_000_000 or len(payloads) > 1000:
            state.update(phase="wb_payload_limits_exceeded", payload_bytes=len(encoded), updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_update_payload_exceeds_safe_limit")
        marker = hashlib.sha256(encoded).hexdigest()
        append_journal({"phase": "prepared", "at": now(), "platform": "wb",
                        "endpoint": "/content/v2/cards/update", "cards": len(payloads),
                        "payload_bytes": len(encoded), "sha256": marker})
        state.update(phase="wb_update_sent", writes_sent=1, payload_sha256=marker, updated_at=now())
        save(STATE, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            state.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_update_uncertain_read_live_before_retry") from None
        append_journal({"phase": "response", "at": now(), "response": response,
                        "cards": len(payloads), "sha256": marker})
        state.update(phase="wb_update_response", wb_error=response.get("error"),
                     wb_error_text=str(response.get("errorText") or "")[:500], updated_at=now())
        save(STATE, state)
        if response.get("error") is not False or response.get("additionalErrors"):
            state.update(phase="wb_update_rejected_reconcile_before_retry")
            save(STATE, state)
            raise RuntimeError("wb_update_rejected")

    before_by_offer = {row["offer_id"]: row["before"] for row in prepared}
    prior_by_offer = {row["offer_id"]: row["prior_document_signatures"] for row in prepared}
    rows = []
    failures = []
    status_counts = collections.Counter()
    readback_offers = sorted(set(before_by_offer) | {row["offer_id"] for row in already_exact})
    for index, offer in enumerate(readback_offers, 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "reason": "readback_missing_or_duplicate_card",
                             "card_count": len(cards)})
            continue
        card = cards[0]
        docs = copy_documents(card)
        same = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        exact = [doc for doc in same if doc_key(doc) == doc_key(desired)
                 and str(doc.get("startDate", ""))[:10] == ISSUE
                 and str(doc.get("endDate", ""))[:10] == EXPIRY
                 and doc.get("isEndless") is False]
        raw_docs = ((card.get("documents") or {}).get("items") or [])
        raw_same = [doc for doc in raw_docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
        raw_exact = [doc for doc in raw_same if doc_key(doc) == doc_key(desired)
                     and str(doc.get("startDate", ""))[:10] == ISSUE
                     and str(doc.get("endDate", ""))[:10] == EXPIRY
                     and doc.get("isEndless") is False]
        preserved = True
        if offer in before_by_offer:
            preserved = comparable_card(card) == comparable_card(before_by_offer[offer])
            actual_signatures = collections.Counter(signature(doc) for doc in docs)
            prior_signatures = collections.Counter(prior_by_offer[offer])
            preserved = preserved and all(actual_signatures[sig] >= count
                                           for sig, count in prior_signatures.items())
        status = doc_status(raw_exact[0]) if len(raw_exact) == 1 and len(raw_same) == 1 else "missing_or_conflicting"
        status_counts[status] += 1
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "document_exact": len(exact) == 1 and len(same) == 1,
               "prior_docs_and_unrelated_fields_preserved": preserved,
               "document_status": status,
               "verdict": raw_exact[0].get("verdict") if len(raw_exact) == 1 else None}
        rows.append(row)
        if not row["document_exact"] or not preserved:
            failures.append(row)
        if index % 50 == 0:
            print(json.dumps({"phase": "wb_live_readback", "checked": index,
                              "of": len(readback_offers), "verified": len(rows) - len(failures),
                              "failures": len(failures)}, ensure_ascii=False), flush=True)

    readback = {"checked_at": now(), "complete": len(rows) == len(readback_offers), "number": NUMBER,
                "target_cards": len(readback_offers), "source_safe_target_cards": len(wanted),
                "updated_cards": len(prepared),
                "already_exact_count": len(already_exact), "skipped_before_write": skipped,
                "verified_target_cards": len(rows) - len(failures), "failures": failures,
                "status_counts": dict(status_counts), "cards": rows,
                "wb_review_left_pending": True}
    save(READBACK, readback)
    if failures or len(rows) != len(readback_offers):
        state.update(phase="wb_readback_incomplete", failure_count=len(failures), updated_at=now())
        save(STATE, state)
        raise RuntimeError("wb_readback_incomplete")
    state.update(phase="verified_complete", readback_path=str(READBACK),
                 verified_target_cards=len(rows), updated_cards=len(prepared),
                 wb_status_counts=dict(status_counts), wb_review_left_pending=True,
                 local_file_deleted=False, updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "updated_cards": len(prepared),
                      "verified_target_cards": len(rows), "status_counts": dict(status_counts),
                      "skipped_before_write": len(skipped), "review_left_to_wb": True,
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
