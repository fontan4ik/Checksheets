"""Attach the remaining exact Ozon-approved Jazzway rows using WB RFC3339 dates."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from api_client import Client, now
from reconcile_approved_ozon_docs_to_wb import (
    DOC_FIELDS, UPDATE_CARD_FIELDS, comparable_card, doc_key, norm_number,
)

BASE_DIR = Path(__file__).resolve().parent
OZON_PREFLIGHT = BASE_DIR / "jazzway_37909_approved_ozon_to_wb_preflight_20261014.json"
PREFLIGHT = BASE_DIR / "jazzway_37909_wb_remaining_preflight_rfc3339_20261014.json"
RUN = BASE_DIR / "jazzway_37909_wb_remaining_run_rfc3339_20261014.json"
READBACK = BASE_DIR / "jazzway_37909_wb_remaining_readback_rfc3339_20261014.json"
NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
WB_TYPE = 2
TNVED = "8539520009"
ALREADY_SUBMITTED = "1025326-25"


def wb_datetime(value: str) -> str:
    value = str(value or "")
    return value if "T" in value else f"{value}T00:00:00Z"


def card_documents(card: dict) -> list[dict]:
    return [{k: item[k] for k in DOC_FIELDS if k in item}
            for item in ((card.get("documents") or {}).get("items") or [])]


def wb_tnved(card: dict) -> list[str]:
    result = []
    for ch in card.get("characteristics") or []:
        if "тнвэд" in str(ch.get("name") or "").lower().replace("ё", "е"):
            raw = ch.get("value")
            vals = raw if isinstance(raw, list) else [raw]
            result.extend(str(v).strip() for v in vals if v not in (None, ""))
    return sorted(set(result))


def signatures(docs: list[dict]) -> collections.Counter:
    return collections.Counter((doc_key(d), str(d.get("startDate") or "")[:10],
                                str(d.get("endDate") or "")[:10]) for d in docs)


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Unique run marker already exists; reconcile live state before another write")
    ozon = json.loads(OZON_PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(ozon["checked_at"].replace("Z", "+00:00"))
    if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 1200:
        raise RuntimeError("Fresh Ozon approval preflight is older than 20 minutes")
    all_candidates = ozon.get("wb_candidates") or []
    if len(all_candidates) != 140 or ozon.get("declined_targets") != 18:
        raise RuntimeError("Expected exactly 140 approved Jazzway Ozon products and 18 skipped declines")
    if sum(x.get("offer_id") == ALREADY_SUBMITTED for x in all_candidates) != 1:
        raise RuntimeError("Previously submitted offer identity changed; reconcile before continuing")
    candidates = [x for x in all_candidates if x.get("offer_id") != ALREADY_SUBMITTED]
    if len(candidates) != 139:
        raise RuntimeError("Expected 139 unsubmitted approved targets")
    if ozon.get("certificate", {}).get("status_code") != "approved":
        raise RuntimeError("Ozon document status is not approved")
    record = ozon["certificate"]
    issue = str(record.get("issue_date") or "")[:10]
    expiry = str(record.get("expire_date") or "")[:10]
    if not issue or not expiry or expiry < dt.datetime.now(dt.timezone.utc).date().isoformat():
        raise RuntimeError("Ozon record dates are missing or expired")
    client = Client()
    results = []
    for index, target in enumerate(candidates, 1):
        offer = target["offer_id"]
        try:
            cards = client.wb_cards(offer)
        except Exception as exc:
            results.append({"offer_id": offer, "state": "read_error", "error": type(exc).__name__})
            continue
        if len(cards) != 1:
            results.append({"offer_id": offer, "state": "missing_or_ambiguous", "matches": len(cards),
                            "nmIDs": [c.get("nmID") for c in cards]})
            continue
        card = cards[0]
        if card.get("vendorCode") != offer or not card.get("nmID"):
            results.append({"offer_id": offer, "state": "identity_mismatch", "nmID": card.get("nmID")})
            continue
        if card.get("brand") != "Jazzway":
            results.append({"offer_id": offer, "state": "brand_mismatch", "brand": card.get("brand"),
                            "nmID": card.get("nmID")})
            continue
        codes = wb_tnved(card)
        if codes != [TNVED]:
            results.append({"offer_id": offer, "state": "tnved_mismatch_or_missing", "tnved_values": codes,
                            "nmID": card.get("nmID")})
            continue
        existing = card_documents(card)
        number_key = norm_number(NUMBER)
        same_number = [d for d in existing if norm_number(d.get("number", "")) == number_key]
        desired = {"type": WB_TYPE, "number": NUMBER, "startDate": wb_datetime(issue),
                   "endDate": wb_datetime(expiry), "isEndless": False}
        if same_number:
            same_exact = [d for d in same_number if doc_key(d) == doc_key(desired)
                          and str(d.get("startDate") or "")[:10] == issue
                          and str(d.get("endDate") or "")[:10] == expiry]
            if len(same_exact) == 1 and len(same_number) == 1:
                results.append({"offer_id": offer, "nmID": card["nmID"], "state": "already_visible",
                                "verdict": same_exact[0].get("verdict"), "before": card})
            else:
                results.append({"offer_id": offer, "nmID": card["nmID"], "state": "number_or_date_conflict",
                                "current_documents": same_number})
            continue
        payload = {k: card[k] for k in UPDATE_CARD_FIELDS if k in card}
        if isinstance(payload.get("dimensions"), dict):
            # `isValid` is a read-only computed field returned by WB's list API.
            payload["dimensions"] = {
                k: payload["dimensions"][k]
                for k in ("length", "width", "height", "weightBrutto")
                if k in payload["dimensions"]
            }
            if set(payload["dimensions"]) != {"length", "width", "height", "weightBrutto"}:
                results.append({"offer_id": offer, "state": "invalid_dimensions_shape",
                                "nmID": card.get("nmID")})
                continue
        payload["nmID"] = card["nmID"]
        payload["vendorCode"] = offer
        payload["documents"] = {"items": existing + [desired], "excludeDocuments": False}
        results.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                        "nmID": card["nmID"], "state": "ready", "addition": desired,
                        "before": card, "payload": payload,
                        "ozon_binding_status": target["ozon_binding_status"]})
        if index % 20 == 0:
            print(f"read {index}/{len(candidates)} exact WB offers", flush=True)

    counts = dict(collections.Counter(x["state"] for x in results))
    plan = {"checked_at": now(), "ozon_preflight": OZON_PREFLIGHT.name,
            "record": record, "candidate_count": len(candidates), "counts": counts,
            "results": results}
    PREFLIGHT.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    ready = [x for x in results if x["state"] == "ready"]
    if not ready:
        print(json.dumps({"state": "no_updates_needed", "counts": counts,
                          "preflight": PREFLIGHT.name}, ensure_ascii=False), flush=True)
        return
    payload = [x["payload"] for x in ready]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 10_000_000 or len(payload) > 1000:
        raise RuntimeError("WB request exceeds verified API limits")
    run = {"started_at": now(), "state": "prepared", "cards": len(ready),
           "documents": len(ready), "request_sha256": hashlib.sha256(encoded).hexdigest(),
           "request_bytes": len(encoded), "offers": [x["offer_id"] for x in ready],
           "skipped_counts": counts}
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    run["state"] = "submitting_once"
    run["submitted_at"] = now()
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    try:
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
    except Exception as exc:
        run["state"] = "write_outcome_uncertain_reconcile_only"
        run["error_type"] = type(exc).__name__
        run["finished_at"] = now()
        RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
        raise
    run["response"] = response
    run["state"] = "accepted_readback_pending" if response.get("error") is False else "response_error_reconcile_only"
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))

    read_results = {}
    for index, row in enumerate(ready, 1):
        try:
            cards = client.wb_cards(row["offer_id"])
        except Exception as exc:
            read_results[row["offer_id"]] = {"state": "read_error", "error": type(exc).__name__}
            continue
        if len(cards) != 1:
            read_results[row["offer_id"]] = {"state": "missing_or_ambiguous", "matches": len(cards)}
            continue
        after = cards[0]
        docs = card_documents(after)
        want = row["addition"]
        found = [d for d in docs if doc_key(d) == doc_key(want)
                 and str(d.get("startDate") or "")[:10] == issue
                 and str(d.get("endDate") or "")[:10] == expiry]
        old = card_documents(row["before"])
        read_results[row["offer_id"]] = {
            "state": "visible_pending_or_reviewing" if len(found) == 1 else "missing",
            "nmID": after.get("nmID"), "documents_visible": len(found) == 1,
            "verdict": found[0].get("verdict") if len(found) == 1 else None,
            "unrelated_fields_preserved": comparable_card(row["before"]) == comparable_card(after),
            "preexisting_documents_preserved": not bool(signatures(old) - signatures(docs)),
            "overallVerdict": (after.get("documents") or {}).get("overallVerdict"),
        }
        if index % 20 == 0:
            print(f"read back {index}/{len(ready)} exact WB cards", flush=True)
    read_counts = dict(collections.Counter(x["state"] for x in read_results.values()))
    summary = {
        "checked_at": now(), "cards_submitted": len(ready), "documents_submitted": len(ready),
        "accepted_response": response.get("error") is False, "readback_counts": read_counts,
        "all_visible": all(x.get("documents_visible") for x in read_results.values()),
        "all_unrelated_fields_preserved": all(x.get("unrelated_fields_preserved") for x in read_results.values()),
        "all_old_documents_preserved": all(x.get("preexisting_documents_preserved") for x in read_results.values()),
        "results": read_results,
    }
    READBACK.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    run["readback"] = {k: v for k, v in summary.items() if k != "results"}
    run["finished_at"] = now()
    run["state"] = ("readback_complete" if summary["accepted_response"] and summary["all_visible"]
                    and summary["all_unrelated_fields_preserved"] and summary["all_old_documents_preserved"]
                    else "readback_needs_review")
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
