#!/usr/bin/env python3
"""Attach the two current FSA documents to the exact Navigator 93812 WB cards."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, norm_number  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

PREFLIGHT = HERE / "navigator_93812_two_docs_live_preflight_20261023.json"
OUT = HERE / "navigator_93812_wb_execution_20261023.json"
JOURNAL = HERE / "navigator_93812_two_docs_mutation_journal_20261023.jsonl"
OFFERS = {"93812-5", "93812-10"}
DOCS = {
    "declaration": {"number": "ЕАЭС N RU Д-CN.РА11.В.08110/24", "type": 2,
                    "issue_date": "2024-12-02", "expire_date": "2029-12-01"},
    "certificate": {"number": "ЕАЭС RU С-CN.НВ93.В.03629/23", "type": 1,
                    "issue_date": "2023-07-18", "expire_date": "2028-07-17"},
}


def save(state: dict) -> None:
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(OUT)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now(), **row}, ensure_ascii=False) + "\n")
        stream.flush()


def card_codes(card: dict) -> set[str]:
    values = []
    for row in card.get("characteristics") or []:
        name = "".join(str(row.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            value = row.get("value")
            values.extend(value if isinstance(value, list) else [value])
    return {str(x or "").split(" - ", 1)[0].strip() for x in values
            if str(x or "").split(" - ", 1)[0].strip()}


def exact_matches(card: dict, doc: dict) -> list[dict]:
    return [x for x in ((card.get("documents") or {}).get("items") or [])
            if norm_number(x.get("number")) == norm_number(doc["number"])
            and int(x.get("type") or 0) == doc["type"]
            and str(x.get("startDate") or "")[:10] == doc["issue_date"]
            and str(x.get("endDate") or "")[:10] == doc["expire_date"]]


def doc_verdict(matches: list[dict]) -> dict:
    verdicts = [x.get("verdict") or {} for x in matches]
    valid = any(v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid"
                for v in verdicts)
    rejected = any(v.get("status") not in (None, 1) or v.get("reason") not in (None, "", "valid")
                   for v in verdicts)
    status = "valid" if valid else ("rejected_or_invalid" if rejected else "pending_or_verdict_absent")
    return {"count": len(matches), "status": status, "verdicts": verdicts}


def main() -> None:
    pre = json.loads(PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(str(pre["checked_at_utc"]).replace("Z", "+00:00"))
    if (pre.get("read_only") is not True or pre.get("target_count") != 2
            or (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 1800):
        raise RuntimeError("read_only_preflight_not_current_or_complete")
    if set(pre.get("wb", {})) != OFFERS:
        raise RuntimeError("wb_preflight_target_set_changed")
    state = {"started_at_utc": now(), "phase": "fresh_wb_preflight", "target_count": 2,
             "documents": list(DOCS), "cards": [], "mutation": {"sent": False},
             "left_for_marketplace_review": True, "local_source_files_deleted": False}
    save(state)
    client = Client()
    before_cards = {}
    payloads = []
    target_states = {}
    for offer in sorted(OFFERS):
        pre_row = pre["wb"][offer]
        cards = client.wb_cards(offer)
        if len(cards) != 1 or str(cards[0].get("vendorCode") or "") != offer:
            raise RuntimeError("wb_exact_card_missing_or_ambiguous:" + offer)
        card = cards[0]
        if str(card.get("nmID")) != str(pre_row.get("nmID")):
            raise RuntimeError("wb_nmid_changed_since_preflight:" + offer)
        if card.get("brand") != "Navigator" or card_codes(card) != {"8539520009"}:
            raise RuntimeError("wb_scope_changed_before_write:" + offer)
        existing = copy_documents(card)
        per_doc = {}
        for name, doc in DOCS.items():
            same_number = [x for x in existing if norm_number(x.get("number")) == norm_number(doc["number"])]
            if same_number and any(int(x.get("type") or 0) != doc["type"]
                                   or (str(x.get("startDate") or "")[:10],
                                       str(x.get("endDate") or "")[:10]) !=
                                      (doc["issue_date"], doc["expire_date"]) for x in same_number):
                raise RuntimeError("wb_existing_document_conflict:" + offer + ":" + name)
            per_doc[name] = doc_verdict(exact_matches(card, doc))
        desired = [{"type": doc["type"], "number": doc["number"],
                    "startDate": doc["issue_date"] + "T00:00:00Z",
                    "endDate": doc["expire_date"] + "T00:00:00Z", "isEndless": False}
                   for doc in DOCS.values()]
        payload = merge_wb(card, desired)
        before_cards[offer] = card
        target_states[offer] = {"nmID": str(card.get("nmID")), "documents_before": per_doc}
        if payload is not None:
            payloads.append({"offer_id": offer, "nmID": str(card.get("nmID")), "payload": payload})

    payload_json = [x["payload"] for x in payloads]
    if payload_json:
        marker = hashlib.sha256(json.dumps(payload_json, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        state["mutation"] = {"sent": True, "endpoint": "/content/v2/cards/update", "items": len(payload_json),
                              "offers": [x["offer_id"] for x in payloads], "payload_sha256": marker,
                              "response": None, "uncertain": False}
        state["phase"] = "wb_update_in_progress"
        save(state)
        journal({"platform": "wb", "phase": "prepared", "endpoint": "/content/v2/cards/update",
                 "items": len(payload_json), "offers": [x["offer_id"] for x in payloads],
                 "payload_sha256": marker})
        try:
            response = client.call("wb", "/content/v2/cards/update", payload_json, mutation=True)
            state["mutation"]["response"] = response
            state["mutation"]["accepted"] = isinstance(response, dict) and response.get("error") is False
            journal({"platform": "wb", "phase": "response", "endpoint": "/content/v2/cards/update",
                     "payload_sha256": marker, "response": response})
        except Exception as exc:
            state["mutation"]["uncertain"] = True
            state["mutation"]["error_type"] = type(exc).__name__
            journal({"platform": "wb", "phase": "uncertain", "endpoint": "/content/v2/cards/update",
                     "payload_sha256": marker, "error_type": type(exc).__name__})
            save(state)
            # Continue with read-only reconciliation; never resend this uncertain batch.
    else:
        state["mutation"] = {"sent": False, "reason": "documents_already_present_exactly"}
    save(state)

    # Read every target card after the single mutation, without retrying writes.
    unresolved_offers = set()
    for offer in sorted(OFFERS):
        rows = client.wb_cards(offer)
        if len(rows) != 1:
            state["cards"].append({"offer_id": offer, "error": "readback_card_missing_or_ambiguous"})
            unresolved_offers.add(offer)
            continue
        card = rows[0]
        docs_after = copy_documents(card)
        before = before_cards[offer]
        before_keys = {(int(x.get("type") or 0), norm_number(x.get("number")),
                        str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10])
                       for x in copy_documents(before)}
        after_keys = {(int(x.get("type") or 0), norm_number(x.get("number")),
                       str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10])
                      for x in docs_after}
        if not before_keys <= after_keys:
            raise RuntimeError("wb_prior_documents_not_preserved:" + offer)
        unchanged = comparable_card(before) == comparable_card(card)
        if not unchanged:
            raise RuntimeError("wb_non_document_card_fields_changed:" + offer)
        documents = {name: doc_verdict(exact_matches(card, doc)) for name, doc in DOCS.items()}
        visible_all = all(documents[name]["count"] == 1 for name in DOCS)
        if not visible_all:
            unresolved_offers.add(offer)
        state["cards"].append({"offer_id": offer, "nmID": str(card.get("nmID")),
                               "documents": documents, "all_exact_documents_visible": visible_all,
                               "prior_documents_preserved": True, "non_document_fields_unchanged": True})
    save(state)

    for wait_seconds in (60, 120):
        if not unresolved_offers:
            break
        time.sleep(wait_seconds)
        still_missing = set()
        for offer in sorted(unresolved_offers):
            rows = client.wb_cards(offer)
            if len(rows) != 1:
                state.setdefault("delayed_readback", []).append({"offer_id": offer, "error": "card_missing"})
                still_missing.add(offer)
                continue
            card = rows[0]
            docs = {name: doc_verdict(exact_matches(card, doc)) for name, doc in DOCS.items()}
            state.setdefault("delayed_readback", []).append({"offer_id": offer, "nmID": str(card.get("nmID")),
                "documents": docs, "all_exact_documents_visible": all(docs[name]["count"] == 1 for name in DOCS)})
            if not all(docs[name]["count"] == 1 for name in DOCS):
                still_missing.add(offer)
        unresolved_offers = still_missing
        save(state)
    state["still_not_visible_after_delayed_recheck"] = len(unresolved_offers)
    state["phase"] = "finished" if not unresolved_offers else "needs_visibility_reconciliation"
    state["finished_at_utc"] = now()
    save(state)
    summary = {"execution_file": str(OUT), "phase": state["phase"],
               "mutation": {k: v for k, v in state["mutation"].items() if k != "response"},
               "cards": len([x for x in state["cards"] if "documents" in x]),
               "document_visibility": {name: sum(1 for row in state["cards"]
                   if row.get("documents", {}).get(name, {}).get("count") == 1) for name in DOCS},
               "verdict_counts": {name: dict(collections.Counter(
                   row.get("documents", {}).get(name, {}).get("status") for row in state["cards"])) for name in DOCS},
               "still_not_visible_after_delayed_recheck": state["still_not_visible_after_delayed_recheck"],
               "local_source_files_deleted": False}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
