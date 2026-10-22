"""Read-only delayed reconciliation; never resends WB writes."""
from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number,
)

STATE = HERE / "arlight_03451_wb_blank_tnved_execution_20261021.json"
BEFORE = HERE / "arlight_03451_wb_blank_tnved_before_20261021.json"
READBACK = HERE / "arlight_03451_wb_blank_tnved_readback_20261021.json"
OUT = HERE / "arlight_03451_wb_blank_tnved_delayed_recheck_20261021.json"
NUMBER = "ЕАЭС RU С-HK.НА46.В.03451/22"
ISSUE = "2022-04-16"
EXPIRY = "2027-04-15"


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


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


def main() -> None:
    if OUT.exists():
        raise RuntimeError("delayed_readback_exists_reconcile_before_retry")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    readback = json.loads(READBACK.read_text(encoding="utf-8"))
    before_doc = json.loads(BEFORE.read_text(encoding="utf-8"))
    if (state.get("writes_sent") != 3 or readback.get("verified_target_cards") != 244
            or len(readback.get("failures") or []) != 4):
        raise RuntimeError("unexpected_state_for_delayed_readback")
    before = {str(c.get("vendorCode") or ""): c for c in before_doc.get("cards") or []}
    pending = {str(r["offer_id"]): r for r in readback.get("failures") or []}
    attempts = []
    client = Client()
    delays = [0, 15, 30, 45, 60, 60]
    resolved = {}
    for attempt_no, delay in enumerate(delays, 1):
        if delay:
            time.sleep(delay)
        newly_resolved = []
        rows = []
        for offer in list(pending):
            cards = client.wb_cards(offer)
            if len(cards) != 1:
                row = {"offer_id": offer, "verified": False,
                       "reason": "live_card_missing_or_ambiguous", "live_card_count": len(cards)}
                rows.append(row)
                continue
            card = cards[0]
            old = before.get(offer)
            if old is None:
                raise RuntimeError("before_snapshot_missing_offer:" + offer)
            docs = copy_documents(card)
            same = [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]
            exact = [d for d in same if doc_key(d) == (1, norm_number(NUMBER))
                     and str(d.get("startDate", ""))[:10] == ISSUE
                     and str(d.get("endDate", ""))[:10] == EXPIRY
                     and d.get("isEndless") is False]
            old_sigs = collections.Counter((doc_key(d), str(d.get("startDate", ""))[:10],
                                            str(d.get("endDate", ""))[:10], bool(d.get("isEndless")))
                                           for d in copy_documents(old))
            new_sigs = collections.Counter((doc_key(d), str(d.get("startDate", ""))[:10],
                                            str(d.get("endDate", ""))[:10], bool(d.get("isEndless")))
                                           for d in docs)
            preserved = all(new_sigs[key] >= value for key, value in old_sigs.items())
            fields = comparable_card(card) == comparable_card(old)
            identity = (str(card.get("vendorCode") or "") == offer
                        and str(card.get("nmID") or "") == str(pending[offer].get("nmID") or ""))
            brand = str(card.get("brand") or "").strip().casefold() == "arlight"
            okay = len(same) == 1 and len(exact) == 1 and preserved and fields and identity and brand and tnved(card) == []
            row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""), "verified": okay,
                   "exact_document_count": len(exact), "prior_documents_preserved": preserved,
                   "unrelated_fields_preserved": fields, "identity_preserved": identity,
                   "brand_preserved": brand, "tnved_still_blank": tnved(card) == [],
                   "document_status": "pending_review_or_verdict_missing" if len(exact) == 1 else "missing_or_conflicting"}
            rows.append(row)
            if okay:
                newly_resolved.append(offer)
                resolved[offer] = row
        for offer in newly_resolved:
            pending.pop(offer, None)
        attempt = {"attempted_at": now(), "attempt": attempt_no,
                   "delay_before_seconds": delay, "checked": len(rows),
                   "verified_this_attempt": len(newly_resolved), "remaining": len(pending),
                   "rows": rows}
        attempts.append(attempt)
        print(json.dumps({k: attempt[k] for k in ("attempt", "checked", "verified_this_attempt", "remaining")},
                         ensure_ascii=False), flush=True)
        save(OUT, {"started_at": attempts[0]["attempted_at"], "updated_at": now(),
                   "read_only": True, "number": NUMBER, "attempts": attempts,
                   "verified_after_delay": len(resolved), "remaining": sorted(pending)})
        if not pending:
            break

    # Update the aggregate result without hiding any unresolved card.
    for i, row in enumerate(readback["cards"]):
        offer = str(row.get("offer_id") or "")
        if offer in resolved:
            readback["cards"][i] = resolved[offer]
    readback["verified_target_cards"] = sum(1 for r in readback["cards"] if r.get("verified"))
    readback["failures"] = [r for r in readback["cards"] if not r.get("verified")]
    counts = collections.Counter(r.get("document_status") for r in readback["cards"] if r.get("verified"))
    readback["status_counts"] = dict(counts)
    readback["complete"] = not readback["failures"] and len(readback["cards"]) == 248
    readback["delayed_settlement_verified"] = len(resolved)
    readback["checked_at"] = now()
    save(READBACK, readback)
    state["phase"] = "verified_complete_after_delayed_readback" if readback["complete"] else "readback_incomplete_after_delay"
    state["verified_target_cards"] = readback["verified_target_cards"]
    state["delayed_settlement_verified"] = len(resolved)
    state["final_status_counts"] = dict(counts)
    state["failures"] = readback["failures"]
    state["updated_at"] = now()
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "verified_target_cards": state["verified_target_cards"],
                      "delayed_settlement_verified": len(resolved),
                      "remaining": [r.get("offer_id") for r in readback["failures"]],
                      "status_counts": dict(counts), "writes_resent": False,
                      "wb_review_left_pending": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
