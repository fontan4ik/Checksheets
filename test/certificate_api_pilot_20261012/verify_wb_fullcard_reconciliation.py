"""Read back live WB cards and the processing-error batches after a full-card update."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from api_client import BASE, Client, now, save
from group4_ozon import norm

PLAN = BASE / "wb_fullcard_reconciliation_plan.json"
EXEC = BASE / "wb_fullcard_reconciliation_execution.json"
AFTER = BASE / "wb_target_full_after.json"
ERRORS = BASE / "wb_cards_error_list_after_full_reconciliation.json"
OUT = BASE / "wb_fullcard_reconciliation_verification.json"
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}
COMPARE_FIELDS = ("nmID", "imtID", "nmUUID", "subjectID", "subjectName", "vendorCode", "brand", "title",
                  "description", "needKiz", "kizMarked", "photos", "video", "tags", "dimensions", "sizes")


def char_signature(card: dict) -> list[tuple]:
    result = []
    for row in card.get("characteristics") or []:
        if int(row.get("id", -1)) in DOC_CHAR_IDS:
            continue
        result.append((int(row.get("id", -1)), row.get("name"), json.dumps(row.get("value"), ensure_ascii=False, sort_keys=True)))
    return sorted(result)


def doc_signature(doc: dict) -> tuple:
    return (int(doc.get("type", 0)), norm(doc.get("number", "")),
            str(doc.get("startDate", ""))[:10], str(doc.get("endDate", ""))[:10], bool(doc.get("isEndless", False)))


def get_all_error_batches(client: Client) -> list[dict]:
    batches = []
    cursor = {"limit": 100}
    for _ in range(100):
        body = client.call("wb", "/content/v2/cards/error/list", {"cursor": cursor, "order": {"ascending": True}})
        if body.get("error"):
            raise RuntimeError("WB error-list call returned an API error")
        data = body.get("data") or {}
        batches.extend(data.get("items") or [])
        c = data.get("cursor") or {}
        if c.get("next") is not True:
            return batches
        if not c.get("updatedAt") or not c.get("batchUUID"):
            raise RuntimeError("WB error-list pagination cursor incomplete")
        cursor = {"limit": 100, "updatedAt": c["updatedAt"], "batchUUID": c["batchUUID"]}
    raise RuntimeError("WB error-list pagination exceeded 100 batches")


def main() -> None:
    plan, execution, after = (json.loads(p.read_text()) for p in (PLAN, EXEC, AFTER))
    if execution.get("phase") != "accepted_waiting_for_wb_sync" or not after.get("complete"):
        raise RuntimeError("WB update acceptance and complete after-readback are required")
    targets = after.get("cards_by_offer") or {}
    by_offer = {x["offer_id"]: x for x in plan["updates"]}
    pilots = plan.get("already_present") or []
    all_expected_offers = set(by_offer) | {x["offer_id"] for x in pilots}
    if len(targets) != len(all_expected_offers) or set(targets) != all_expected_offers:
        raise RuntimeError("Fresh WB full-card target set differs from the reviewed candidate set")
    if len(by_offer) != execution.get("cards"):
        raise RuntimeError("WB execution card count differs from the update plan")

    card_results = []
    verdicts = Counter()
    for offer, item in by_offer.items():
        before = item["before"]
        after_card = targets[offer]
        if str(after_card.get("nmID")) != str(item["nmID"]) or after_card.get("vendorCode") != offer:
            raise RuntimeError(f"Live WB identity changed for {offer}")
        changed = [field for field in COMPARE_FIELDS if before.get(field) != after_card.get(field)]
        if char_signature(before) != char_signature(after_card):
            changed.append("characteristics_other_than_document_fields")
        if changed:
            raise RuntimeError(f"Unrelated WB card fields changed for {offer}: {changed}")
        before_docs = Counter(doc_signature(d) for d in ((before.get("documents") or {}).get("items") or []))
        after_docs = Counter(doc_signature(d) for d in ((after_card.get("documents") or {}).get("items") or []))
        if any(after_docs[sig] < count for sig, count in before_docs.items()):
            raise RuntimeError(f"A pre-existing WB document disappeared from {offer}")
        actual_docs = ((after_card.get("documents") or {}).get("items") or [])
        for desired in item["additions"]:
            signature = (int(desired["type"]), norm(desired["number"]),
                         str(desired["startDate"])[:10], str(desired["endDate"])[:10], bool(desired["isEndless"]))
            if not any(doc_signature(d) == signature for d in actual_docs):
                raise RuntimeError(f"WB readback is missing exact document {desired['number']} on {offer}")
        docs = after_card.get("documents") or {}
        if docs.get("excludeDocuments") is not False:
            raise RuntimeError(f"WB still excludes documents on {offer}")
        verdict = docs.get("overallVerdict") or {}
        verdicts[str(verdict.get("status", "missing")) + ":" + str(verdict.get("reason", ""))] += 1
        card_results.append({"offer_id": offer, "nmID": item["nmID"], "documents_added": len(item["additions"]),
                             "documents_visible": True, "preexisting_docs_preserved": True,
                             "fields_preserved": True, "excludeDocuments": False,
                             "overallVerdict": verdict})

    pilot_files = (BASE / "wb_fullcard_pilot_execution.json", BASE / "wb_fullcard_exclude_pilot_execution.json")
    for path in pilot_files:
        pilot = json.loads(path.read_text())
        if pilot.get("state") not in {"accepted_readback_checked", "pilot_readback_complete"}:
            raise RuntimeError(f"WB document pilot does not have a successful readback: {path.name}")
    for item in pilots:
        card = targets[item["offer_id"]]
        if str(card.get("nmID")) != str(item["nmID"]):
            raise RuntimeError(f"WB pilot card identity changed for {item['offer_id']}")
        docs = ((card.get("documents") or {}).get("items") or [])
        for wanted in item.get("documents") or []:
            if not any(doc_signature(actual) == doc_signature(wanted) for actual in docs):
                raise RuntimeError(f"Previously verified WB pilot document disappeared: {item['offer_id']}")
        if (card.get("documents") or {}).get("excludeDocuments") is not False:
            raise RuntimeError(f"WB pilot documents are still excluded: {item['offer_id']}")
        verdict = (card.get("documents") or {}).get("overallVerdict") or {}
        verdicts[str(verdict.get("status", "missing")) + ":" + str(verdict.get("reason", ""))] += 1
        card_results.append({"offer_id": item["offer_id"], "nmID": item["nmID"], "documents_added": 0,
                             "documents_visible": True, "preexisting_docs_preserved": True,
                             "fields_preserved": True, "excludeDocuments": False,
                             "overallVerdict": verdict, "prior_pilot_readback": True})

    client = Client()
    batches = get_all_error_batches(client)
    save(ERRORS.name, {"checked_at": now(), "response": {"data": {"items": batches,
                 "cursor": {"next": False}}}})
    start = datetime.fromisoformat(execution["finished_at"].replace("Z", "+00:00"))
    target_offers = all_expected_offers
    relevant = []
    for batch in batches:
        try:
            updated = datetime.fromisoformat(str(batch.get("updatedAt", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        vendor_codes = set(batch.get("vendorCodes") or [])
        errors = batch.get("errors") or {}
        intersection = target_offers & (vendor_codes | set(errors))
        if updated >= start and intersection:
            relevant.append({"batchUUID": batch.get("batchUUID"), "updatedAt": batch.get("updatedAt"),
                             "target_vendor_codes": sorted(intersection), "errors": {k: errors[k] for k in intersection if k in errors}})
    if relevant:
        raise RuntimeError(f"WB returned a post-update error batch for {len(relevant)} target cards")

    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "execution_started_at": execution.get("started_at"),
              "execution_finished_at": execution.get("finished_at"), "wb_after_catalog_checked_at": after.get("checked_at"),
              "cards_checked": len(card_results), "documents_expected": sum(len(x["additions"]) for x in by_offer.values()) + len(pilots),
              "documents_visible": sum(len(x["additions"]) for x in by_offer.values()) + len(pilots),
              "preexisting_document_rows_preserved": True, "all_unrelated_fields_preserved": True,
              "all_exclude_documents_false": True, "post_update_error_batches_for_targets": 0,
              "overall_verdict_counts": dict(verdicts), "errors_checked": len(batches),
              "cards": card_results}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ("cards_checked", "documents_expected", "documents_visible",
                  "preexisting_document_rows_preserved", "all_unrelated_fields_preserved",
                  "all_exclude_documents_false", "post_update_error_batches_for_targets",
                  "overall_verdict_counts", "errors_checked")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
