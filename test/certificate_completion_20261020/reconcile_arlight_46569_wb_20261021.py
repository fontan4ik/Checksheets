"""Reconcile the accepted and HTTP-500 WB batches before any retry."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)

PREFLIGHT = HERE / "arlight_46569_preflight_live_20261021.json"
OZON_STATE = HERE / "arlight_46569_ozon_execution_20261021.json"
WB_STATE = HERE / "arlight_46569_wb_execution_20261021.json"
BEFORE = HERE / "arlight_46569_wb_before_cards_20261021.json"
STATE = HERE / "arlight_46569_wb_reconciliation_20261021.json"
JOURNAL = HERE / "arlight_46569_wb_reconciliation_journal_20261021.jsonl"
READBACK = HERE / "arlight_46569_wb_readback_20261021.json"
RECOVERY_BEFORE = HERE / "arlight_46569_wb_recovery_before_20261021.json"
NUMBER = "ЕАЭС N RU Д-CN.РА01.В.46569/26"
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"
ALLOWED = {"8539519009"}


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def card_codes(card: dict) -> list[str]:
    out = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        out.extend(str(v or "").split(" - ", 1)[0].strip() for v in values if v)
    return sorted(set(out))


def scan_catalog(client: Client, wanted: set[str]) -> tuple[dict[str, list[dict]], int, int]:
    found: dict[str, list[dict]] = collections.defaultdict(list)
    cursor = {"limit": 100}
    seen: set[tuple] = set()
    pages = total = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        batch = body.get("cards")
        if body.get("error") or not isinstance(batch, list):
            raise RuntimeError("wb_catalog_page_invalid")
        returned = body.get("cursor") or {}
        if returned.get("total") != len(batch):
            raise RuntimeError("wb_catalog_page_count_mismatch")
        pages += 1
        total += len(batch)
        for card in batch:
            offer = str(card.get("vendorCode") or "")
            if offer in wanted:
                found[offer].append(card)
        if pages % 50 == 0:
            print(json.dumps({"phase": "wb_reconcile_full_catalog", "pages": pages,
                              "cards_read": total,
                              "targets_found": sum(map(len, found.values()))}), flush=True)
        if len(batch) < 100:
            return found, pages, total
        sig = (returned.get("updatedAt"), returned.get("nmID"))
        if None in sig or sig in seen:
            raise RuntimeError("wb_catalog_cursor_missing_or_repeated")
        seen.add(sig)
        cursor = {"limit": 100, "updatedAt": sig[0], "nmID": sig[1]}


def exact_document(card: dict, desired: dict) -> tuple[list[dict], list[dict]]:
    docs = (card.get("documents") or {}).get("items") or []
    same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
    exact = [d for d in same if doc_key(d) == doc_key(desired)
             and str(d.get("startDate", ""))[:10] == ISSUE
             and str(d.get("endDate", ""))[:10] == EXPIRY
             and d.get("isEndless") is False]
    return same, exact


def status_of(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "valid"):
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    for path in (STATE, JOURNAL, READBACK):
        if path.exists():
            raise RuntimeError("reconciliation_artifact_exists_inspect_before_retry")
    failed = json.loads(WB_STATE.read_text())
    if failed.get("phase") != "wb_update_uncertain" or failed.get("current_batch") != 6:
        raise RuntimeError("expected_single_uncertain_batch_6_not_found")
    pre = json.loads(PREFLIGHT.read_text())
    ozon = json.loads(OZON_STATE.read_text())
    before_doc = json.loads(BEFORE.read_text())
    if (ozon.get("phase") != "ozon_verified_complete" or ozon.get("verified_target_pairs") != 905
            or not before_doc.get("complete") or before_doc.get("target_count") != 905):
        raise RuntimeError("required_previously_verified_state_missing")
    before_by_offer = {str(x["vendorCode"]): x for x in before_doc["cards"]}
    pre_wb = {str(x["offer_id"]): x for x in pre["wb_targets"]}
    targets = {str(x["offer_id"]): x for x in pre["ozon_targets"]}
    if len(before_by_offer) != 905 or set(before_by_offer) != set(targets) or set(pre_wb) != set(targets):
        raise RuntimeError("target_set_mismatch_with_prewrite_snapshot")
    wanted = set(targets)
    expected_nmid = {offer: str(pre_wb[offer]["nmID"]) for offer in wanted}
    desired = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
               "endDate": wb_datetime(EXPIRY), "isEndless": False}
    state = {"started_at": now(), "phase": "reconcile_read_only", "number": NUMBER,
             "target_count": 905, "original_uncertain_batch": 6,
             "original_successful_batches": 5, "ozon_verified_target_pairs": 905,
             "writes_sent": 0, "review_left_to_wb": True,
             "reconciled_before_any_retry": True}
    save(STATE, state)
    client = Client()
    found, pages, total = scan_catalog(client, wanted)
    current_cards = {}
    missing = []
    already_exact = []
    conflicts = []
    for offer in sorted(wanted):
        cards = found.get(offer, [])
        if len(cards) != 1:
            conflicts.append({"offer_id": offer, "reason": "card_missing_or_duplicate",
                              "count": len(cards)})
            continue
        card = cards[0]
        if str(card.get("nmID")) != expected_nmid[offer]:
            conflicts.append({"offer_id": offer, "reason": "nmID_changed"})
            continue
        if str(card.get("brand") or "").strip().casefold() != "arlight" or card_codes(card) != sorted(ALLOWED):
            conflicts.append({"offer_id": offer, "reason": "brand_or_tnved_out_of_scope"})
            continue
        current_cards[offer] = card
        same, exact = exact_document(card, desired)
        if len(exact) == 1 and len(same) == 1:
            already_exact.append(offer)
        elif same:
            conflicts.append({"offer_id": offer, "reason": "existing_number_metadata_conflict",
                              "documents": same})
        else:
            missing.append(offer)
    # Persist the complete observation before sending any remaining writes.
    save(RECOVERY_BEFORE, {"checked_at": now(), "complete": True,
                           "catalog_pages": pages, "catalog_cards_read": total,
                           "target_count": len(current_cards),
                           "cards": list(current_cards.values())})
    state.update(phase="reconcile_snapshot_complete", catalog_pages=pages,
                 catalog_cards_read=total, cards_with_exact_document=len(already_exact),
                 cards_missing_document=len(missing), conflicts=conflicts,
                 recovery_before_path=str(RECOVERY_BEFORE))
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "catalog_pages": pages,
                      "cards_read": total, "exact_now": len(already_exact),
                      "missing_now": len(missing), "conflicts": len(conflicts)},
                     ensure_ascii=False), flush=True)
    # Do not let any conflicting card block safe targets; it remains untouched.
    prepared = []
    for offer in missing:
        card = current_cards[offer]
        payload = runner.merge_wb(card, [desired])
        if payload is None:
            conflicts.append({"offer_id": offer, "reason": "merge_returned_no_change"})
            continue
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]),
                         "before": card, "payload": payload})
    batch_size = 100
    batches = [prepared[i:i + batch_size] for i in range(0, len(prepared), batch_size)]
    state.update(phase="recovery_batches_prepared", writes_sent=0,
                 prepared_recovery_cards=len(prepared), recovery_batch_count=len(batches),
                 conflicts=conflicts)
    save(STATE, state)
    last_send = None
    for number, batch in enumerate(batches, start=1):
        if last_send is not None:
            delay = 7.0 - (time.monotonic() - last_send)
            if delay > 0:
                time.sleep(delay)
        payloads = [x["payload"] for x in batch]
        marker = hashlib.sha256(json.dumps(payloads, sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "prepared", "at": now(),
                                     "batch": number, "cards": len(batch),
                                     "sha256": marker}, ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="recovery_batch_sent", current_batch=number,
                     writes_sent=state["writes_sent"] + 1, updated_at=now())
        save(STATE, state)
        last_send = time.monotonic()
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            state.update(phase="recovery_batch_uncertain", error_type=type(exc).__name__,
                         current_batch=number, updated_at=now())
            save(STATE, state)
            raise RuntimeError("recovery_write_uncertain_stop_and_read_live") from None
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "response", "at": now(), "batch": number,
                                     "response": response}, ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="recovery_batches_progress", completed_batches=number,
                     updated_at=now())
        save(STATE, state)
        if response.get("error") is not False:
            state.update(phase="recovery_batch_rejected",
                         error_text=str(response.get("errorText") or "")[:500])
            save(STATE, state)
            raise RuntimeError("recovery_batch_rejected")
        print(json.dumps({"phase": "recovery_batch_complete", "batch": number,
                          "batches": len(batches), "cards": len(batch)}, ensure_ascii=False), flush=True)

    state.update(phase="final_full_readback", updated_at=now())
    save(STATE, state)
    final_found, final_pages, final_total = scan_catalog(client, wanted)
    rows = []
    statuses = collections.Counter()
    for offer in sorted(wanted):
        cards = final_found.get(offer, [])
        if len(cards) != 1:
            rows.append({"offer_id": offer, "verified": False, "reason": "card_missing_or_duplicate"})
            continue
        card = cards[0]
        same, exact = exact_document(card, desired)
        preserved = offer in current_cards and comparable_card(card) == comparable_card(current_cards[offer])
        okay = len(same) == 1 and len(exact) == 1 and preserved
        status = status_of(exact[0]) if len(exact) == 1 else "missing_or_conflicting"
        statuses[status] += 1
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                     "verified": okay, "exact_document_count": len(same),
                     "metadata_exact": len(exact) == 1,
                     "unrelated_fields_preserved": preserved,
                     "document_status": status,
                     "verdict": exact[0].get("verdict") if len(exact) == 1 else None})
    failures = [x for x in rows if not x.get("verified")]
    readback = {"checked_at": now(), "complete": True, "number": NUMBER,
                "pages": final_pages, "cards_read": final_total,
                "target_cards": len(rows), "verified_target_cards": len(rows) - len(failures),
                "status_counts": dict(statuses), "failures": failures,
                "cards": rows, "wb_review_left_pending": True}
    save(READBACK, readback)
    terminal_phase = "verified_complete" if not failures else "partially_verified"
    state.update(phase=terminal_phase, final_catalog_pages=final_pages,
                 final_catalog_cards_read=final_total,
                 verified_target_cards=len(rows) - len(failures),
                 wb_status_counts=dict(statuses), failure_count=len(failures),
                 conflicts=conflicts, readback_path=str(READBACK),
                 wb_review_left_pending=True, updated_at=now())
    save(WB_STATE, {**failed, "phase": "reconciled_verified_complete" if not failures else "reconciled_partially_verified",
                    "reconciled_at": now(), "reconciliation_path": str(STATE),
                    "verified_target_cards": len(rows) - len(failures),
                    "wb_status_counts": dict(statuses)})
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": state["verified_target_cards"],
                      "status_counts": dict(statuses), "failure_count": len(failures),
                      "conflicts": len(conflicts), "wb_review_left_pending": True},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
