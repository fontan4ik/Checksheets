"""Attach Arlight certificate 03451/22 only to exact in-scope WB cards."""
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
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

PREFLIGHT = HERE / "arlight_03451_preflight_live_20261021.json"
OZON_STATE = HERE / "arlight_03451_ozon_execution_20261021.json"
STATE = HERE / "arlight_03451_wb_execution_20261021.json"
BEFORE = HERE / "arlight_03451_wb_before_20261021.json"
READBACK = HERE / "arlight_03451_wb_readback_20261021.json"
JOURNAL = HERE / "arlight_03451_wb_mutation_journal_20261021.jsonl"
NUMBER = "ЕАЭС RU С-HK.НА46.В.03451/22"
ISSUE = "2022-04-16"
EXPIRY = "2027-04-15"
TNVED = "8504408300"
EXPECTED = 206


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def append(event: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()


def tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        name = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = char.get("value")
        values.extend(str(v or "").split(" - ", 1)[0].strip()
                      for v in (raw if isinstance(raw, list) else [raw]) if v)
    return sorted(set(values))


def signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate", ""))[:10],
            str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless")))


def status(doc: dict) -> str:
    verdict = doc.get("verdict") or {}
    if verdict.get("verified") is True and verdict.get("reason") == "valid":
        return "valid"
    if verdict.get("verified") is True and verdict.get("reason") not in (None, "valid"):
        return "rejected_or_invalid"
    return "pending_review_or_verdict_missing"


def main() -> None:
    if any(p.exists() for p in (STATE, BEFORE, READBACK, JOURNAL)):
        raise RuntimeError("wb_execution_artifact_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    ozon = json.loads(OZON_STATE.read_text(encoding="utf-8"))
    if (ozon.get("phase") != "ozon_verified_complete"
            or ozon.get("verified_target_pairs") != 462
            or pre.get("eligible_wb_cards_for_add") != EXPECTED):
        raise RuntimeError("cross_platform_preflight_or_ozon_binding_incomplete")
    candidates = {str(r.get("offer_id") or ""): r for r in pre.get("wb_targets") or []
                  if r.get("reason") == "eligible_for_add"}
    if len(candidates) != EXPECTED:
        raise RuntimeError(f"unexpected_safe_wb_offer_count:{len(candidates)}")
    target_doc = {"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRY), "isEndless": False}
    state = {"started_at": now(), "phase": "fresh_wb_card_recheck", "number": NUMBER,
             "ozon_certificate_id": ozon.get("certificate_id"),
             "ozon_verified_target_pairs": ozon.get("verified_target_pairs"),
             "target_cards": EXPECTED, "writes_sent": 0,
             "wb_review_left_pending": True, "local_file_deleted": False,
             "scope_basis": {"brand": "Arlight", "tnved": TNVED}}
    save(STATE, state)
    client = Client()
    prepared = []
    skipped = []
    for index, (offer, planned) in enumerate(sorted(candidates.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            skipped.append({"offer_id": offer, "reason": "live_card_missing_or_ambiguous"})
            continue
        card = cards[0]
        if (str(card.get("vendorCode") or "") != offer
                or str(card.get("nmID") or "") != str(planned.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "arlight"
                or tnved(card) != [TNVED]):
            skipped.append({"offer_id": offer, "reason": "live_identity_brand_or_tnved_changed"})
            continue
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same:
            skipped.append({"offer_id": offer, "reason": "number_appeared_or_conflicted_before_write"})
            continue
        payload = runner.merge_wb(card, [target_doc])
        if payload is None or str(payload.get("nmID")) != str(card.get("nmID")):
            skipped.append({"offer_id": offer, "reason": "merge_refused_or_payload_identity_mismatch"})
            continue
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]),
                         "before": card, "payload": payload,
                         "prior_document_signatures": [signature(d) for d in docs]})
        if index % 50 == 0:
            print(json.dumps({"phase": "fresh_wb_card_recheck", "checked": index,
                              "prepared": len(prepared), "skipped": len(skipped)},
                             ensure_ascii=False), flush=True)
    if len(prepared) != EXPECTED or skipped:
        state.update(phase="prewrite_recheck_incomplete", prepared_cards=len(prepared),
                     skipped=skipped, mutation_sent=False, updated_at=now())
        save(STATE, state)
        raise RuntimeError("wb_prewrite_recheck_incomplete")

    save(BEFORE, {"checked_at": now(), "complete": True, "target_count": len(prepared),
                  "scope": {"brand": "Arlight", "tnved": TNVED},
                  "cards": [x["before"] for x in prepared]})
    batch_size = 100
    batches = [prepared[i:i + batch_size] for i in range(0, len(prepared), batch_size)]
    encoded = json.dumps([x["payload"] for x in prepared], ensure_ascii=False,
                         separators=(",", ":")).encode()
    if len(encoded) > 9_000_000 or any(len(b) > 100 for b in batches):
        raise RuntimeError("wb_payload_exceeds_safe_batch_guard")
    state.update(phase="wb_prewrite_verified", prepared_cards=len(prepared),
                 payload_bytes=len(encoded), batch_count=len(batches), document=target_doc,
                 updated_at=now())
    save(STATE, state)

    previous_send = None
    for batch_no, batch in enumerate(batches, 1):
        if previous_send is not None:
            delay = 7.0 - (time.monotonic() - previous_send)
            if delay > 0:
                time.sleep(delay)
        payloads = [x["payload"] for x in batch]
        marker = hashlib.sha256(json.dumps(payloads, ensure_ascii=False,
                                           sort_keys=True).encode()).hexdigest()
        append({"phase": "prepared", "at": now(), "batch": batch_no,
                "cards": len(batch), "sha256": marker})
        state.update(phase="wb_update_sent", current_batch=batch_no,
                     writes_sent=state["writes_sent"] + 1, updated_at=now())
        save(STATE, state)
        previous_send = time.monotonic()
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            state.update(phase="wb_update_uncertain", error_type=type(exc).__name__, updated_at=now())
            save(STATE, state)
            raise RuntimeError("wb_update_uncertain_read_live_before_retry") from None
        append({"phase": "response", "at": now(), "batch": batch_no,
                "response": response, "sha256": marker})
        state.update(phase="wb_batches_progress", completed_batches=batch_no,
                     wb_response_error=response.get("error"), updated_at=now())
        save(STATE, state)
        if response.get("error") is not False or response.get("additionalErrors"):
            state.update(phase="wb_update_rejected", error_text=str(response.get("errorText") or "")[:500])
            save(STATE, state)
            raise RuntimeError("wb_update_rejected_stop_and_reconcile")
        print(json.dumps({"phase": "wb_batch_complete", "batch": batch_no,
                          "batches": len(batches), "cards": len(batch)},
                         ensure_ascii=False), flush=True)

    old_by_offer = {x["offer_id"]: x["before"] for x in prepared}
    old_doc_sigs = {x["offer_id"]: collections.Counter(x["prior_document_signatures"])
                    for x in prepared}
    rows = []
    for index, entry in enumerate(prepared, 1):
        offer = entry["offer_id"]
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            rows.append({"offer_id": offer, "nmID": entry["nmID"], "verified": False,
                         "reason": "live_card_missing_or_ambiguous"})
            continue
        card = cards[0]
        docs = copy_documents(card)
        same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
        exact = [d for d in same if doc_key(d) == doc_key(target_doc)
                 and str(d.get("startDate", ""))[:10] == ISSUE
                 and str(d.get("endDate", ""))[:10] == EXPIRY
                 and d.get("isEndless") is False]
        actual = collections.Counter(signature(d) for d in docs)
        preserved = all(actual[key] >= count for key, count in old_doc_sigs[offer].items())
        fields = comparable_card(card) == comparable_card(old_by_offer[offer])
        identity = (str(card.get("vendorCode") or "") == offer
                    and str(card.get("nmID") or "") == entry["nmID"])
        scope = str(card.get("brand") or "").strip().casefold() == "arlight" and tnved(card) == [TNVED]
        okay = len(same) == 1 and len(exact) == 1 and preserved and fields and identity and scope
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "verified": okay, "exact_document_count": len(exact),
                     "metadata_exact": len(exact) == 1, "document_status": status(exact[0]) if len(exact) == 1 else "missing_or_conflicting",
                     "prior_documents_preserved": preserved, "unrelated_fields_preserved": fields,
                     "identity_preserved": identity, "scope_preserved": scope,
                     "verdict": exact[0].get("verdict") if len(exact) == 1 else None})
        if index % 50 == 0:
            print(json.dumps({"phase": "wb_targeted_readback", "checked": index,
                              "target_cards": len(prepared)}, ensure_ascii=False), flush=True)
    failures = [r for r in rows if not r.get("verified")]
    statuses = collections.Counter(r.get("document_status") for r in rows if r.get("verified"))
    readback = {"checked_at": now(), "complete": not failures and len(rows) == len(prepared),
                "number": NUMBER, "target_cards": len(rows),
                "verified_target_cards": len(rows) - len(failures),
                "status_counts": dict(statuses), "failures": failures,
                "cards": rows, "wb_review_left_pending": True,
                "local_file_deleted": False}
    save(READBACK, readback)
    state.update(phase="verified_complete" if not failures else "readback_incomplete",
                 readback_path=str(READBACK), verified_target_cards=len(rows) - len(failures),
                 status_counts=dict(statuses), failures=failures,
                 wb_review_left_pending=True, updated_at=now(), local_file_deleted=False)
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": len(rows) - len(failures),
                      "status_counts": dict(statuses), "failures": failures,
                      "review_left_to_wb": True, "local_file_deleted": False},
                     ensure_ascii=False, indent=2))
    if failures:
        raise RuntimeError("wb_readback_incomplete")


if __name__ == "__main__":
    main()
