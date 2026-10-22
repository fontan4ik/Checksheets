"""Monitor already submitted WB documents; never resubmit automatically.

The known approved Ozon bindings are polled every 30 minutes for up to 72 hours.
WB's API documents asynchronous synchronization and document checks. Any WB
error or validation rejection is recorded as a skip for separate handling.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import time
from pathlib import Path

from api_client import Client, now, save
from reconcile_approved_ozon_docs_to_wb import doc_key

BASE_DIR = Path(__file__).resolve().parent
PREFLIGHT = BASE_DIR / "jazzway_37909_approved_ozon_to_wb_preflight_20261014.json"
ONE_WRITE = BASE_DIR / "jazzway_37909_wb_single_rfc3339_probe_20261014.json"
BATCH_WRITE = BASE_DIR / "jazzway_37909_wb_remaining_run_rfc3339_20261014.json"
OUT = BASE_DIR / "jazzway_37909_wb_monitor_until_final_20261014.json"
CERT_NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
TNVED = "8539520009"
POLL_SECONDS = 1800
MAX_HOURS = 72


def read_recent_errors(client: Client, offers: set[str]) -> dict[str, list[str]]:
    body = client.call("wb", "/content/v2/cards/error/list", {
        "cursor": {"limit": 100}, "order": {"ascending": False},
    })
    data = body.get("data") or {}
    errors: dict[str, list[str]] = {}
    for batch in data.get("items") or []:
        for offer, messages in (batch.get("errors") or {}).items():
            if offer in offers:
                errors.setdefault(offer, []).extend(str(x) for x in messages or [])
    return errors


def card_tnved(card: dict) -> list[str]:
    values = []
    for char in card.get("characteristics") or []:
        if "тнвэд" in str(char.get("name") or "").lower().replace("ё", "е"):
            raw = char.get("value")
            values.extend(str(x).strip() for x in (raw if isinstance(raw, list) else [raw])
                          if x not in (None, ""))
    return sorted(set(values))


def matching_docs(card: dict, target: dict, issue: str, expiry: str) -> list[dict]:
    items = ((card.get("documents") or {}).get("items") or [])
    return [doc for doc in items
            if doc_key(doc) == doc_key(target)
            and str(doc.get("startDate") or "")[:10] == issue
            and str(doc.get("endDate") or "")[:10] == expiry]


def main() -> None:
    preflight = json.loads(PREFLIGHT.read_text())
    if len(preflight.get("wb_candidates") or []) != 140 or preflight.get("declined_targets") != 18:
        raise RuntimeError("Ozon approval snapshot changed; refresh and reconcile before monitoring")
    if preflight.get("certificate", {}).get("status_code") != "approved":
        raise RuntimeError("Ozon document is no longer approved")
    record = preflight["certificate"]
    issue = str(record.get("issue_date") or "")[:10]
    expiry = str(record.get("expire_date") or "")[:10]
    if not issue or not expiry:
        raise RuntimeError("Ozon certificate dates are missing")
    targets = preflight["wb_candidates"]
    offers = {x["offer_id"] for x in targets}
    if len(offers) != 140:
        raise RuntimeError("Duplicate Jazzway offers in monitoring input")
    earliest = dt.datetime.fromisoformat(
        json.loads(ONE_WRITE.read_text())["finished_at"].replace("Z", "+00:00"))
    batch = json.loads(BATCH_WRITE.read_text())
    submitted = dt.datetime.fromisoformat(batch["submitted_at"].replace("Z", "+00:00"))
    started = min(earliest, submitted)
    deadline = started + dt.timedelta(hours=MAX_HOURS)
    client = Client()
    cycle = 0

    while dt.datetime.now(dt.timezone.utc) < deadline:
        cycle += 1
        checked_at = now()
        error_state = {}
        try:
            recent_errors = read_recent_errors(client, offers)
        except Exception as exc:
            recent_errors = {}
            error_state = {"read_error": type(exc).__name__}

        results = []
        for index, target in enumerate(targets, 1):
            offer = target["offer_id"]
            try:
                cards = client.wb_cards(offer)
            except Exception as exc:
                results.append({"offer_id": offer, "state": "read_error", "error": type(exc).__name__})
                continue
            if len(cards) != 1:
                results.append({"offer_id": offer, "state": "missing_or_ambiguous_card", "matches": len(cards)})
                continue
            card = cards[0]
            if card.get("vendorCode") != offer or card.get("brand") != "Jazzway":
                results.append({"offer_id": offer, "nmID": card.get("nmID"), "state": "identity_or_brand_conflict"})
                continue
            if card_tnved(card) != [TNVED]:
                results.append({"offer_id": offer, "nmID": card.get("nmID"), "state": "tnved_conflict"})
                continue
            doc = {"type": 2, "number": CERT_NUMBER}
            matches = matching_docs(card, doc, issue, expiry)
            if len(matches) > 1:
                state = "duplicate_document"
                verdict = None
            elif not matches:
                state = "wb_error" if recent_errors.get(offer) else "pending_not_visible"
                verdict = None
            else:
                verdict = matches[0].get("verdict") or {}
                reason = str(verdict.get("reason") or "").lower()
                if verdict.get("verified") is True and verdict.get("status") == 1 and reason == "valid":
                    state = "valid"
                elif verdict.get("status") == 2 or reason in {"invalid", "declined", "document_not_found", "document_expired"}:
                    state = "wb_rejected"
                else:
                    state = "pending_validation"
            if recent_errors.get(offer):
                state = "wb_error"
            results.append({
                "offer_id": offer, "nmID": card.get("nmID"), "state": state,
                "verdict": verdict or None, "overallVerdict": (card.get("documents") or {}).get("overallVerdict"),
                "wb_errors": recent_errors.get(offer, []),
            })
            if index % 25 == 0:
                print(f"monitor cycle {cycle}: checked {index}/{len(targets)}", flush=True)

        counts = dict(collections.Counter(x["state"] for x in results))
        pending_states = {"read_error", "missing_or_ambiguous_card", "pending_not_visible", "pending_validation"}
        terminal = not any(x["state"] in pending_states for x in results)
        result = {
            "checked_at": checked_at, "cycle": cycle, "submission_started_at": started.isoformat(),
            "deadline": deadline.isoformat(), "poll_interval_seconds": POLL_SECONDS,
            "ozon_approved_targets": 140, "ozon_declined_skipped": 18,
            "out_of_scope_skipped": 119, "states": counts,
            "wb_recent_error_list": error_state or {"checked": True, "matched_target_count": sum(bool(v) for v in recent_errors.values())},
            "terminal": terminal, "results": results,
        }
        save(OUT.name, result)
        print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False), flush=True)
        if terminal:
            return
        remaining = (deadline - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(POLL_SECONDS, remaining))

    final = json.loads(OUT.read_text()) if OUT.exists() else {}
    final["stopped_at"] = now()
    final["terminal"] = False
    final["timeout_state"] = "WB validation/synchronization did not reach a terminal result within 72 hours"
    save(OUT.name, final)
    print(json.dumps({"state": "monitor_deadline_reached", "artifact": OUT.name}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
