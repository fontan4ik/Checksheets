"""Attach verified Feron certificate 01324/22 to five existing WB cards once."""
from __future__ import annotations

import json
import time
from pathlib import Path

from api_client import Client, now
from group4_wb import compare_readback, prepare_card, signature

BASE = Path(__file__).resolve().parent
PREFLIGHT = BASE / "feron_01324_live_preflight.json"
PREUPDATE = BASE / "feron_01324_wb_preupdate_readback.json"
PLAN = BASE / "feron_01324_wb_plan.json"
EXECUTION = BASE / "feron_01324_wb_execution.json"
READBACK = BASE / "feron_01324_wb_readback.json"
VERIFICATION = BASE / "feron_01324_wb_verification.json"
NUMBER = "ЕАЭС RU С-CN.НВ85.В.01324/22"
OFFER_IDS = {"21488-1", "21496-1", "21499-1", "41349-1", "41350-1"}
ISSUE_DATE, EXPIRY_DATE = "2022-08-17", "2027-08-16"


def save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if any(p.exists() for p in (PLAN, EXECUTION, READBACK, VERIFICATION)):
        raise RuntimeError("WB execution evidence exists; reconcile before any write")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    source = json.loads(PREUPDATE.read_text(encoding="utf-8"))
    targets = {x["offer_id"]: x for x in preflight["wb"]["rows"]
               if x.get("nmID") and not any("01324/22" in d.get("number", "")
                                               for d in (x.get("documents") or []))}
    if set(targets) != OFFER_IDS or preflight["wb"].get("snapshot_complete") is not True:
        raise RuntimeError("WB target set changed or complete catalog snapshot is missing")
    cards = source.get("cards_by_offer") or {}
    if set(cards) != OFFER_IDS or source.get("target_count") != 5:
        raise RuntimeError("Fresh WB preupdate readback does not match exact five-card scope")
    desired = {"type": 1, "number": NUMBER,
               "startDate": ISSUE_DATE + "T00:00:00Z",
               "endDate": EXPIRY_DATE + "T00:00:00Z", "isEndless": False}
    planned = []
    for offer in sorted(OFFER_IDS):
        card = cards[offer]
        expected = targets[offer]
        if card.get("vendorCode") != offer or str(card.get("nmID")) != str(expected["nmID"]):
            raise RuntimeError("Fresh WB identity does not match workbook/catalog for " + offer)
        before_docs = (card.get("documents") or {}).get("items") or []
        if any("01324/22" in d.get("number", "") for d in before_docs):
            raise RuntimeError("Certificate appeared in live WB card; reconcile instead of duplicating")
        if (card.get("documents") or {}).get("excludeDocuments") is True:
            raise RuntimeError("WB card excludes documents: " + offer)
        item = prepare_card(card, [desired])
        if len(item["additions"]) != 1 or signature(item["additions"][0]) != signature(desired):
            raise RuntimeError("Exact new certificate row not prepared for " + offer)
        planned.append(item)
    payloads = [x["payload"] for x in planned]
    encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payloads) > 3000 or len(encoded) > 10_000_000:
        raise RuntimeError("WB update exceeds documented batch limit")
    plan = {"planned_at": now(), "number": NUMBER, "type": 1,
            "issue_date": ISSUE_DATE, "expire_date": EXPIRY_DATE,
            "live_catalog_checked_at": preflight["wb"]["snapshot_checked_at"],
            "preupdate_cards_checked_at": source["read_at"],
            "card_count": len(planned), "document_rows_to_add": len(planned),
            "payload_bytes": len(encoded), "local_cleanup_allowed": False,
            "absent_card_offers_not_created": sorted(set(
                preflight["wb"]["target_cards_missing"])),
            "updates": [{"offer_id": x["vendorCode"], "nmID": x["nmID"],
                         "before": x["before"], "payload": x["payload"],
                         "additions": x["additions"]} for x in planned]}
    save(PLAN, plan)
    state = {"started_at": now(), "phase": "prepared", "number": NUMBER,
             "card_count": len(payloads), "payload_bytes": len(encoded),
             "request_sha256": __import__("hashlib").sha256(encoded).hexdigest(),
             "cards": [{"offer_id": x["vendorCode"], "nmID": x["nmID"]} for x in planned]}
    save(EXECUTION, state)
    # Wildberries documents a six-second interval for this endpoint.
    time.sleep(5.4)
    client = Client()
    try:
        response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
    except Exception as exc:
        state.update({"phase": "uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("WB update outcome uncertain; read the five cards before retry") from None
    state["response"] = response
    if response.get("error") is not False:
        state.update({"phase": "response_error", "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("WB did not accept update; reconcile before retry")
    state.update({"phase": "accepted_waiting_for_sync", "accepted_at": now()})
    save(EXECUTION, state)
    readback = {"started_at": now(), "complete": False, "cards_by_offer": {}, "failures": []}
    save(READBACK, readback)
    wanted = signature(desired)
    for index, item in enumerate(planned):
        if index:
            time.sleep(5.4)
        offer = item["vendorCode"]
        try:
            found = client.wb_cards(offer)
        except Exception as exc:
            readback["failures"].append({"offer_id": offer, "error_type": type(exc).__name__})
            readback["updated_at"] = now()
            save(READBACK, readback)
            state.update({"phase": "readback_incomplete", "updated_at": now()})
            save(EXECUTION, state)
            raise
        if len(found) != 1 or str(found[0].get("nmID")) != str(item["nmID"]):
            readback["failures"].append({"offer_id": offer, "error_type": "card_identity_missing_or_duplicate"})
            continue
        after = found[0]
        readback["cards_by_offer"][offer] = after
        readback["updated_at"] = now()
        save(READBACK, readback)
    readback["complete"] = len(readback["cards_by_offer"]) == len(planned) and not readback["failures"]
    save(READBACK, readback)
    results = {}
    for item in planned:
        offer = item["vendorCode"]
        after = readback["cards_by_offer"].get(offer)
        if not after:
            continue
        docs = (after.get("documents") or {}).get("items") or []
        rows = [d for d in docs if signature(d) == wanted]
        preservation = compare_readback(item["before"], after)
        results[offer] = {
            "nmID": str(after.get("nmID")), "matching_document_rows": len(rows),
            "document": rows[0] if len(rows) == 1 else None,
            "document_dates_correct": len(rows) == 1 and
                str(rows[0].get("startDate", ""))[:10] == ISSUE_DATE and
                str(rows[0].get("endDate", ""))[:10] == EXPIRY_DATE,
            "documents_enabled": (after.get("documents") or {}).get("excludeDocuments") is False,
            "preservation": preservation,
        }
    verification = {"verified_at": now(), "number": NUMBER, "type": 1,
        "issue_date": ISSUE_DATE, "expire_date": EXPIRY_DATE,
        "target_card_count": 5, "readback_card_count": len(readback["cards_by_offer"]),
        "document_rows_added_and_visible": sum(x["matching_document_rows"] == 1 for x in results.values()),
        "all_documents_visible": len(results) == 5 and all(x["matching_document_rows"] == 1 for x in results.values()),
        "all_dates_correct": len(results) == 5 and all(x["document_dates_correct"] for x in results.values()),
        "all_card_fields_preserved": len(results) == 5 and all(x["preservation"]["preserved"] for x in results.values()),
        "cards": results, "failures": readback["failures"],
        "wb_verdicts": {offer: (x.get("document") or {}).get("verdict") for offer, x in results.items()},
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "17 target WB offers still have no cards; WB verdicts for these five additions are pending review."}
    verification["all_verified"] = (verification["all_documents_visible"] and
        verification["all_dates_correct"] and verification["all_card_fields_preserved"] and
        all((x.get("document") or {}).get("verdict", {}).get("verified") is True and
            (x.get("document") or {}).get("verdict", {}).get("status") == 1 for x in results.values()))
    save(VERIFICATION, verification)
    state.update({"phase": "all_verified" if verification["all_verified"] else "visible_waiting_for_final_verdict",
                  "finished_at": now(), "verification_path": str(VERIFICATION)})
    save(EXECUTION, state)
    print(json.dumps({k: verification[k] for k in
        ("number", "target_card_count", "document_rows_added_and_visible", "all_dates_correct",
         "all_card_fields_preserved", "wb_verdicts", "all_verified", "local_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
