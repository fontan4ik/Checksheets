"""Standalone first-stage NTC ledger that debits/credits a local F snapshot.

Pure calculation: no Google, Ozon, WMS, or marketplace connection. The caller
persists both returned F and state together. A changed F without a matching
state change is rejected, because an external warehouse refresh could otherwise
overwrite or double-count this ledger's operations.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from ntc_stock_engine import _integer, _quantities


HANDOVER_STATUSES = {"driver_pickup", "delivering", "delivered", "last_mile"}
CANCELLED_STATUSES = {"cancelled", "not_accepted"}
RECEIVED_RETURN_STATUS = "ReceivedBySeller"


def advance(payload: dict, previous_state: dict | None = None) -> dict:
    """Reconcile order/return snapshots and calculate new F and ledger state.

    ``postings`` and ``returns`` may contain only updated records; unseen records
    remain in the ledger. ``manual_k`` must be the complete current K snapshot.
    All quantities are sellable units; F and deltas are physical pieces.
    """
    current_f = {str(k): _integer(v, f"F/{k}") for k, v in payload["stock_by_model"].items()}
    articles = {}
    for item in payload["articles"]:
        offer = str(item.get("offer_id") or "").strip()
        model = str(item.get("model") or "").strip()
        size = _integer(item.get("H"), f"H/{offer}")
        if not offer or not model or not size or offer in articles or model not in current_f:
            raise ValueError(f"invalid article {offer!r}")
        articles[offer] = (model, size)

    state = deepcopy(previous_state) if previous_state else {
        "last_f_by_model": dict(current_f),
        "applied_physical_by_model": {model: 0 for model in current_f},
        "base_physical_by_model": dict(current_f),
        "postings": {}, "returns": {}, "manual_k": {},
    }
    if current_f != state["last_f_by_model"]:
        raise ValueError("F changed outside this ledger; reconcile warehouse source before continuing")
    if set(current_f) != set(state["applied_physical_by_model"]):
        raise ValueError("model set changed since ledger creation")
    if "base_physical_by_model" not in state:
        # Upgrade the pre-shortage journal. Until now negative F was rejected,
        # so the original physical pool is exactly last F + applied debits.
        state["base_physical_by_model"] = {
            model: state["last_f_by_model"][model] + state["applied_physical_by_model"][model]
            for model in current_f
        }

    for posting in payload.get("postings", []):
        number = str(posting.get("posting_number") or "").strip()
        status = str(posting.get("status") or "").strip()
        if not number or not status:
            raise ValueError("posting requires posting_number and status")
        old = state["postings"].get(number, {})
        handoff = posting.get("ever_handed_over")
        if handoff is not None and not isinstance(handoff, bool):
            raise ValueError(f"invalid handoff history for {number}")
        handed_over = bool(old.get("ever_handed_over")) or status in HANDOVER_STATUSES or handoff is True
        if status in CANCELLED_STATUSES and handoff is None:
            handed_over = True  # Unknown cancellation history: fail closed.
        if "items" in posting:
            items = _quantities(posting["items"], number)
        elif old:
            items = old["items"]
        else:
            raise ValueError(f"posting {number} has no items")
        if handed_over and old:
            # Cancellation payloads can omit shipped items; never erase them.
            items = {offer: max(quantity, old["items"].get(offer, 0))
                     for offer, quantity in {**old["items"], **items}.items()}
        for offer in items:
            if offer not in articles:
                raise ValueError(f"unknown article {offer} in {number}")
        state["postings"][number] = {
            "status": status, "items": items, "ever_handed_over": handed_over,
        }

    for entry in payload.get("returns", []):
        return_id = str(entry.get("id") or "").strip()
        if not return_id:
            raise ValueError("return without id")
        if str(entry.get("schema", "")).lower() != "fbs":
            continue
        visual_status = ((entry.get("visual") or {}).get("status") or {}).get("sys_name")
        if visual_status != RECEIVED_RETURN_STATUS:
            continue
        number = str(entry.get("posting_number") or "").strip()
        product = entry.get("product") or {}
        offer = str(product.get("offer_id") or "").strip()
        quantity = _integer(product.get("quantity"), f"return/{return_id}")
        if not number or not offer or offer not in articles:
            raise ValueError(f"invalid accepted return {return_id}")
        accepted = {"posting_number": number, "offer_id": offer, "quantity": quantity}
        if return_id in state["returns"] and state["returns"][return_id] != accepted:
            raise ValueError(f"return {return_id} changed after acceptance")
        state["returns"][return_id] = accepted

    returned = defaultdict(int)
    for entry in state["returns"].values():
        returned[(entry["posting_number"], entry["offer_id"])] += entry["quantity"]
    target_units = defaultdict(int)
    for number, posting in state["postings"].items():
        cancelled_before_handoff = (posting["status"] in CANCELLED_STATUSES
                                    and not posting["ever_handed_over"])
        for offer, ordered in posting["items"].items():
            accepted = returned[(number, offer)]
            if accepted > ordered:
                raise ValueError(f"returns exceed ordered quantity for {number}/{offer}")
            if not cancelled_before_handoff:
                target_units[offer] += ordered - accepted
    manual = payload.get("manual_k", {})
    state["manual_k"] = {offer: _integer(qty, f"K/{offer}") for offer, qty in manual.items()}
    for offer, quantity in state["manual_k"].items():
        if offer not in articles:
            raise ValueError(f"unknown manual article {offer}")
        target_units[offer] += quantity

    target_physical = {model: 0 for model in current_f}
    for offer, quantity in target_units.items():
        model, size = articles[offer]
        target_physical[model] += quantity * size
    delta = {model: target_physical[model] - state["applied_physical_by_model"][model]
             for model in current_f}
    new_f = {model: max(0, state["base_physical_by_model"][model] - target_physical[model])
             for model in current_f}
    shortage = {model: max(0, target_physical[model] - state["base_physical_by_model"][model])
                for model in current_f}

    state["applied_physical_by_model"] = target_physical
    state["last_f_by_model"] = new_f
    return {"F_by_model": new_f, "delta_physical_by_model": delta,
            "shortage_physical_by_model": shortage,
            "applied_units_by_offer": {offer: qty for offer, qty in target_units.items() if qty},
            "state": state}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="local JSON snapshot")
    parser.add_argument("--state", type=Path, help="previous state JSON; omitted on first run")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    old = json.loads(args.state.read_text(encoding="utf-8")) if args.state else None
    print(json.dumps(advance(payload, old), ensure_ascii=False, indent=2, sort_keys=True))
