"""Attach Arlight declaration 46569/26 to exact in-scope WB cards and verify."""
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
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)

PREFLIGHT = HERE / "arlight_46569_preflight_live_20261021.json"
OZON_STATE = HERE / "arlight_46569_ozon_execution_20261021.json"
STATE = HERE / "arlight_46569_wb_execution_20261021.json"
BEFORE = HERE / "arlight_46569_wb_before_cards_20261021.json"
READBACK = HERE / "arlight_46569_wb_readback_20261021.json"
JOURNAL = HERE / "arlight_46569_wb_mutation_journal_20261021.jsonl"
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


def full_catalog(client: Client, wanted: set[str], expected_nmid: dict[str, str]) -> tuple[list[dict], int, int]:
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
            print(json.dumps({"phase": "wb_fresh_full_catalog", "pages": pages,
                              "cards_read": total,
                              "targets_found": sum(map(len, found.values()))}), flush=True)
        if len(batch) < 100:
            break
        sig = (returned.get("updatedAt"), returned.get("nmID"))
        if None in sig or sig in seen:
            raise RuntimeError("wb_catalog_cursor_missing_or_repeated")
        seen.add(sig)
        cursor = {"limit": 100, "updatedAt": sig[0], "nmID": sig[1]}
    cards = []
    for offer in sorted(wanted):
        rows = found.get(offer, [])
        if len(rows) != 1:
            raise RuntimeError(f"wb_target_missing_or_duplicate:{offer}:{len(rows)}")
        card = rows[0]
        if str(card.get("nmID")) != expected_nmid[offer]:
            raise RuntimeError("wb_nm_id_changed:" + offer)
        if str(card.get("brand") or "").strip().casefold() != "arlight":
            raise RuntimeError("wb_brand_changed:" + offer)
        codes = card_codes(card)
        if len(codes) != 1 or set(codes) != ALLOWED:
            raise RuntimeError("wb_tnved_scope_changed:" + offer)
        same = [d for d in copy_documents(card)
                if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same:
            raise RuntimeError("wb_number_appeared_after_preflight:" + offer)
        cards.append(card)
    if len(cards) != len(wanted):
        raise RuntimeError("wb_target_cards_incomplete")
    return cards, pages, total


def wb_status(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "valid"):
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    if STATE.exists() or JOURNAL.exists() or READBACK.exists():
        raise RuntimeError("wb_execution_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    ozon = json.loads(OZON_STATE.read_text())
    if (not pre.get("eligible_for_upload") or ozon.get("phase") != "ozon_verified_complete"
            or ozon.get("verified_target_pairs") != 905
            or pre.get("wb_targets_checked") != 905
            or pre.get("wb_scope_counts") != {"in_scope": 905}
            or pre.get("wb_existing_target_cards_with_same_number") != 0):
        raise RuntimeError("cross_platform_preflight_not_complete")
    wanted = {str(x["offer_id"]) for x in pre["ozon_targets"]}
    pre_rows = {str(x["offer_id"]): x for x in pre["wb_targets"]}
    if len(wanted) != 905 or set(pre_rows) != wanted:
        raise RuntimeError("preflight_offer_set_mismatch")
    expected_nmid = {offer: str(pre_rows[offer]["nmID"]) for offer in wanted}
    state = {"started_at": now(), "phase": "fresh_full_wb_read", "number": NUMBER,
             "ozon_certificate_id": ozon.get("certificate_id"),
             "ozon_verified_target_pairs": ozon.get("verified_target_pairs"),
             "target_cards": 905, "writes_sent": 0, "review_left_to_wb": True,
             "local_file_deleted": False}
    save(STATE, state)
    client = Client()
    cards, pages, total = full_catalog(client, wanted, expected_nmid)
    target_doc = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRY), "isEndless": False}
    prepared = []
    for card in cards:
        payload = runner.merge_wb(card, [target_doc])
        if payload is None:
            raise RuntimeError("wb_target_not_added_despite_absence:" + str(card.get("vendorCode")))
        before = json.loads(json.dumps(card, ensure_ascii=False))
        prepared.append({"offer_id": str(card["vendorCode"]), "nmID": str(card["nmID"]),
                         "before": before, "payload": payload})
    save(BEFORE, {"checked_at": now(), "complete": True, "pages": pages,
                  "cards_read": total, "target_count": len(prepared),
                  "cards": [x["before"] for x in prepared]})
    payload_size = len(json.dumps([x["payload"] for x in prepared], ensure_ascii=False,
                                  separators=(",", ":")).encode())
    batches = [prepared[i:i + 100] for i in range(0, len(prepared), 100)]
    state.update(phase="wb_fresh_snapshot_complete", fresh_catalog_pages=pages,
                 fresh_catalog_cards_read=total, prepared_card_count=len(prepared),
                 payload_bytes=payload_size, batch_count=len(batches), document=target_doc)
    save(STATE, state)
    prior_send = None
    for batch_no, batch in enumerate(batches, start=1):
        if prior_send is not None:
            delay = 7.0 - (time.monotonic() - prior_send)
            if delay > 0:
                time.sleep(delay)
        payloads = [x["payload"] for x in batch]
        marker = hashlib.sha256(json.dumps(payloads, sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "prepared", "at": now(),
                                     "batch": batch_no, "cards": len(batch),
                                     "sha256": marker}, ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="wb_update_sent", current_batch=batch_no,
                     writes_sent=state["writes_sent"] + 1, updated_at=now())
        save(STATE, state)
        prior_send = time.monotonic()
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            state.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_update_uncertain_read_live_before_retry") from None
        with JOURNAL.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": "response", "at": now(),
                                     "batch": batch_no, "response": response},
                                    ensure_ascii=False) + "\n")
            stream.flush()
        state.update(phase="wb_batches_progress", completed_batches=batch_no,
                     wb_response_error=response.get("error"), updated_at=now())
        save(STATE, state)
        if response.get("error") is not False:
            state.update(phase="wb_update_rejected", error_text=str(response.get("errorText") or "")[:500])
            save(STATE, state)
            raise RuntimeError("wb_update_rejected_stop_and_reconcile")
        print(json.dumps({"phase": "wb_batch_complete", "batch": batch_no,
                          "batches": len(batches), "cards": len(batch)}, ensure_ascii=False), flush=True)

    state.update(phase="wb_full_catalog_readback", updated_at=now())
    save(STATE, state)
    read_cards, read_pages, read_total = full_catalog(client, wanted, expected_nmid)
    before_by_offer = {x["offer_id"]: x["before"] for x in prepared}
    rows = []
    statuses = collections.Counter()
    for card in read_cards:
        offer = str(card.get("vendorCode") or "")
        docs = (card.get("documents") or {}).get("items") or []
        exact = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact_meta = [d for d in exact if doc_key(d) == doc_key(target_doc)
                      and str(d.get("startDate", ""))[:10] == ISSUE
                      and str(d.get("endDate", ""))[:10] == EXPIRY
                      and d.get("isEndless") is False]
        preserved = comparable_card(card) == comparable_card(before_by_offer[offer])
        status = wb_status(exact_meta[0]) if len(exact_meta) == 1 else "readback_missing_or_conflicting"
        statuses[status] += 1
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID")),
                     "exact_document_count": len(exact),
                     "metadata_exact": len(exact_meta) == 1,
                     "unrelated_fields_preserved": preserved,
                     "document_status": status,
                     "verdict": exact_meta[0].get("verdict") if len(exact_meta) == 1 else None})
    failures = [x for x in rows if not x["metadata_exact"] or not x["unrelated_fields_preserved"]]
    readback = {"checked_at": now(), "complete": True, "number": NUMBER,
                "pages": read_pages, "cards_read": read_total,
                "target_cards": len(rows), "verified_target_cards": len(rows) - len(failures),
                "status_counts": dict(statuses), "failures": failures,
                "cards": rows, "wb_review_left_pending": True}
    save(READBACK, readback)
    if failures:
        state.update(phase="wb_readback_incomplete", failure_count=len(failures), updated_at=now())
        save(STATE, state)
        raise RuntimeError("wb_readback_incomplete")
    state.update(phase="verified_complete", readback_path=str(READBACK),
                 verified_target_cards=len(rows), wb_status_counts=dict(statuses),
                 wb_review_left_pending=True, updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": len(rows),
                      "status_counts": dict(statuses), "review_left_to_wb": True},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
