"""Standalone, pure NTC stock calculation. No API, sheet, or marketplace access.

Input is a JSON-compatible mapping; ``calculate(payload)`` returns a mapping.
``python ntc_stock_engine.py --input test/ntc_example.json`` prints the result.

F is the physical stock currently reported by the warehouse. A posting or a
manual deduction reduces saleable stock only while its movement is NOT yet
reflected in F. An Ozon return status never adds stock by itself.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


RECEIVED_RETURN_STATUS = "ReceivedBySeller"
CANCELLED_STATUSES = {"cancelled", "not_accepted"}


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _quantities(items: list[dict], label: str) -> dict[str, int]:
    quantities: dict[str, int] = defaultdict(int)
    for item in items:
        offer = str(item.get("offer_id") or "").strip()
        if not offer:
            raise ValueError(f"{label}: missing offer_id")
        quantities[offer] += _integer(item.get("quantity"), f"{label}/{offer}")
    return dict(quantities)


def _base_allocation(stock: int, offers: list[str], sizes: dict[str, int]) -> dict[str, int]:
    """Match the sheet's balanced full-cycle allocation for unique H values."""
    ordered = sorted(offers, key=lambda offer: sizes[offer])
    if len({sizes[offer] for offer in ordered}) != len(ordered):
        raise ValueError("one model contains repeated multiplicity H")
    prefixes = []
    total = 0
    for offer in ordered:
        total += sizes[offer]
        prefixes.append(total)
    result = {}
    remainder = stock
    cumulative = 0
    for offer, divisor in zip(reversed(ordered), reversed(prefixes)):
        rounds, remainder = divmod(remainder, divisor)
        cumulative += rounds
        result[offer] = cumulative
    return result


def calculate(payload: dict) -> dict:
    """Return L by offer, unreflected holds, accepted returns, and diagnostics.

    ``outbound_booked`` maps posting_number -> offer_id -> units already removed
    from F. ``return_reconciled`` maps posting_number -> offer_id -> units of an
    accepted return explicitly confirmed as available in F; it is needed only
    for order units whose outbound movement was never booked in F.
    ``manual_booked`` maps offer_id -> units of K already removed from F.
    """
    models = {str(k): _integer(v, f"F/{k}") for k, v in payload["stock_by_model"].items()}
    articles: dict[str, tuple[str, int]] = {}
    groups: dict[str, list[str]] = defaultdict(list)
    for item in payload["articles"]:
        offer = str(item.get("offer_id") or "").strip()
        model = str(item.get("model") or "").strip()
        size = _integer(item.get("H"), f"H/{offer}")
        if not offer or not model or size == 0 or offer in articles or model not in models:
            raise ValueError(f"invalid article {offer!r}")
        articles[offer] = (model, size)
        groups[model].append(offer)

    confirmed_returns: dict[tuple[str, str], int] = defaultdict(int)
    seen_return_ids = set()
    for entry in payload.get("returns", []):
        return_id = str(entry.get("id") or "")
        if not return_id:
            raise ValueError("return without id")
        if return_id in seen_return_ids:
            continue
        seen_return_ids.add(return_id)
        if str(entry.get("schema", "")).lower() != "fbs":
            continue
        if ((entry.get("visual") or {}).get("status") or {}).get("sys_name") != RECEIVED_RETURN_STATUS:
            continue
        number = str(entry.get("posting_number") or "").strip()
        product = entry.get("product") or {}
        offer = str(product.get("offer_id") or "").strip()
        if not number or not offer:
            raise ValueError(f"accepted return {return_id} lacks posting or article")
        confirmed_returns[(number, offer)] += _integer(product.get("quantity"), f"return/{return_id}")

    holds: dict[str, int] = defaultdict(int)
    return_waiting: dict[str, int] = defaultdict(int)
    seen_postings = set()
    outbound = payload.get("outbound_booked", {})
    reconciled = payload.get("return_reconciled", {})
    for posting in payload.get("postings", []):
        number = str(posting.get("posting_number") or "").strip()
        if not number or number in seen_postings:
            raise ValueError(f"missing or duplicate posting {number!r}")
        seen_postings.add(number)
        items = _quantities(posting.get("items", []), number)
        status = str(posting.get("status") or "").strip()
        if not status:
            raise ValueError(f"missing status for {number}")
        cancelled = status in CANCELLED_STATUSES
        handoff = posting.get("ever_handed_over")
        if handoff is not None and not isinstance(handoff, bool):
            raise ValueError(f"invalid ever_handed_over for {number}")
        # A missing history must never release a cancelled order prematurely.
        handed_over = handoff is not False
        for offer, ordered in items.items():
            if offer not in articles:
                continue
            booked = _integer(outbound.get(number, {}).get(offer, 0), f"outbound/{number}/{offer}")
            returned = confirmed_returns[(number, offer)]
            credited = _integer(reconciled.get(number, {}).get(offer, 0), f"return_reconciled/{number}/{offer}")
            if booked > ordered or returned > ordered or credited > min(returned, ordered - booked):
                raise ValueError(f"inconsistent movement for {number}/{offer}")
            if not cancelled or handed_over:
                holds[offer] += ordered - booked - credited
                return_waiting[offer] += min(returned, ordered - booked) - credited

    manual = payload.get("manual_k", {})
    manual_booked = payload.get("manual_booked", {})
    for offer in set(manual) | set(manual_booked):
        if offer not in articles:
            raise ValueError(f"unknown manual article {offer}")
        requested = _integer(manual.get(offer, 0), f"K/{offer}")
        booked = _integer(manual_booked.get(offer, 0), f"manual_booked/{offer}")
        if booked > requested:
            raise ValueError(f"manual booked exceeds K for {offer}")
        holds[offer] += requested - booked

    result: dict[str, int] = {}
    physical_holds: dict[str, int] = {}
    overdrawn: dict[str, int] = {}
    for model, offers in groups.items():
        sizes = {offer: articles[offer][1] for offer in offers}
        baseline = _base_allocation(models[model], offers, sizes)
        cap = {offer: max(0, baseline[offer] - holds[offer]) for offer in offers}
        reserved = sum(holds[offer] * sizes[offer] for offer in offers)
        physical_holds[model] = reserved
        capacity = max(0, models[model] - reserved)
        if reserved > models[model]:
            overdrawn[model] = reserved - models[model]
        # Only reduce further if a hold exceeds its original article allocation.
        # Larger packs are reduced first, with offer_id as a stable tie breaker.
        used = sum(cap[offer] * sizes[offer] for offer in offers)
        for offer in sorted(offers, key=lambda item: (-sizes[item], item)):
            if used <= capacity:
                break
            drop = min(cap[offer], (used - capacity + sizes[offer] - 1) // sizes[offer])
            cap[offer] -= drop
            used -= drop * sizes[offer]
        result.update(cap)

    return {
        "L_by_offer": result,
        "unreflected_units_by_offer": dict(holds),
        "unreflected_physical_by_model": physical_holds,
        "accepted_return_waiting_for_warehouse_by_offer": dict(return_waiting),
        "overdrawn_physical_by_model": overdrawn,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="local JSON input snapshot")
    args = parser.parse_args()
    print(json.dumps(calculate(json.loads(args.input.read_text(encoding="utf-8"))),
                     ensure_ascii=False, indent=2, sort_keys=True))
