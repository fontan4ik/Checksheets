"""Independent full readback of all 55 Stekker 05795/22 marketplace links."""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
from pathlib import Path

from api_client import BASE, Client
from preflight_stekker_05795_20261014 import read_ozon_certificates, read_wb_cards

PREFLIGHT = BASE / "stekker_05795_live_preflight_20261014.json"
RUN = BASE / "stekker_05795_execution_20261014.json"
VERIFY = BASE / "stekker_05795_verification_20261014.json"
OUT = BASE / "stekker_05795_all_55_independent_readback_20261014.json"
NUMBER_SUFFIX = "0579522"
OZON_CERT_ID = "5661327"
DOC_CHAR_IDS = {15001135, 15001136, 15001137, 15001138}


def digits(value: object) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def doc_signature(doc: dict) -> tuple:
    return (int(doc.get("type") or 0), digits(doc.get("number")),
            str(doc.get("startDate") or "")[:10], str(doc.get("endDate") or "")[:10],
            bool(doc.get("isEndless", False)))


def char_map(card: dict) -> dict[int, dict]:
    return {int(x.get("id", -1)): x for x in card.get("characteristics") or []}


def main() -> None:
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    run = json.loads(RUN.read_text(encoding="utf-8"))
    offers = preflight["offers"]
    before_cards = {x["offer_id"]: x["cards"][0] for x in preflight["wb_cards_by_offer"]
                    if len(x["cards"]) == 1}
    if len(before_cards) != len(offers):
        raise RuntimeError("The saved WB preflight does not cover all 55 offers")
    client = Client()
    certs = read_ozon_certificates(client)
    exact = [x for x in certs if str(x.get("certificate_id")) == OZON_CERT_ID]
    if len(exact) != 1 or digits(exact[0].get("certificate_number")).endswith(NUMBER_SUFFIX) is False:
        raise RuntimeError("Independent Ozon certificate list readback differs from certificate 5661327")
    rows = []
    missing, duplicate, card_conflicts, prior_docs_missing = [], [], [], []
    verdicts = collections.Counter()
    old_doc_changes = collections.Counter()
    field_counts = collections.Counter()
    for offer in offers:
        found = [x for x in read_wb_cards(client, offer) if x.get("vendorCode") == offer]
        if len(found) != 1:
            (missing if not found else duplicate).append(offer)
            continue
        card = found[0]
        before = before_cards[offer]
        if str(card.get("nmID")) != str(before.get("nmID")):
            card_conflicts.append({"offer_id": offer, "field": "nmID"})
        for field in ("vendorCode", "brand", "title", "gtin", "description",
                      "dimensions", "sizes", "kizMarked"):
            if before.get(field) != card.get(field):
                card_conflicts.append({"offer_id": offer, "field": field})
        before_chars, after_chars = char_map(before), char_map(card)
        for char_id in sorted(set(before_chars) | set(after_chars)):
            if before_chars.get(char_id) == after_chars.get(char_id):
                continue
            if char_id in DOC_CHAR_IDS:
                continue
            field_counts["non_document_characteristic_changes"] += 1
            if char_id in before_chars and char_id not in after_chars:
                old_doc_changes["removed_characteristics"] += 1
            card_conflicts.append({"offer_id": offer, "field": "characteristic", "id": char_id,
                                   "name": (after_chars.get(char_id) or before_chars.get(char_id) or {}).get("name"),
                                   "before": (before_chars.get(char_id) or {}).get("value"),
                                   "after": (after_chars.get(char_id) or {}).get("value")})
        old_docs = (before.get("documents") or {}).get("items") or []
        new_docs = ((card.get("documents") or {}).get("items") or [])
        old_signatures = collections.Counter(doc_signature(x) for x in old_docs)
        new_signatures = collections.Counter(doc_signature(x) for x in new_docs)
        if any(new_signatures[sig] < count for sig, count in old_signatures.items()):
            prior_docs_missing.append(offer)
        target = [x for x in new_docs if digits(x.get("number")).endswith(NUMBER_SUFFIX)]
        if len(target) != 1 or doc_signature(target[0]) != (1, "530579522", "2022-10-05", "2027-10-04", False):
            missing.append(offer)
            continue
        verdict = target[0].get("verdict") or {}
        verdicts[str(verdict.get("status") or verdict.get("reason") or "pending")] += 1
        rows.append({"offer_id": offer, "nmID": str(card["nmID"]), "document": {
            "type": target[0].get("type"), "number": target[0].get("number"),
            "startDate": target[0].get("startDate"), "endDate": target[0].get("endDate"),
            "verdict": verdict}, "overallVerdict": (card.get("documents") or {}).get("overallVerdict")})
    verification = {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ozon_certificate_id": OZON_CERT_ID,
        "ozon_certificate_status": exact[0].get("status_code"),
        "ozon_binding_status_counts": run.get("ozon", {}).get("product_status_counts", {}),
        "target_count": len(offers), "wb_exact_rows": len(rows),
        "wb_document_verdict_counts": dict(verdicts),
        "wb_missing_cards": missing, "wb_duplicate_cards": duplicate,
        "wb_card_field_conflicts": card_conflicts,
        "wb_prior_document_rows_missing": prior_docs_missing,
        "wb_all_documents_present": len(rows) == len(offers) and not missing and not duplicate,
        "wb_prior_documents_preserved": not prior_docs_missing,
        "wb_unrelated_fields_preserved": not card_conflicts,
        "wb_rows": rows,
        "local_cleanup_allowed": False,
    }
    OUT.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prior = json.loads(VERIFY.read_text(encoding="utf-8"))
    prior.update({"independent_readback_file": str(OUT),
                  "independent_checked_at_utc": verification["checked_at_utc"],
                  "wb_exact_rows_verified": len(rows),
                  "wb_document_verdict_counts": dict(verdicts),
                  "wb_missing_or_conflicting_rows": sorted(set(missing + duplicate)),
                  "wb_unrelated_field_or_prior_doc_conflicts": card_conflicts,
                  "wb_readback_verified": verification["wb_all_documents_present"]})
    VERIFY.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked_at_utc": verification["checked_at_utc"],
                      "ozon_certificate_status": verification["ozon_certificate_status"],
                      "wb_exact_rows": f"{len(rows)}/{len(offers)}",
                      "wb_document_verdict_counts": dict(verdicts),
                      "wb_prior_documents_preserved": verification["wb_prior_documents_preserved"],
                      "wb_unrelated_fields_preserved": verification["wb_unrelated_fields_preserved"],
                      "wb_conflicts": card_conflicts,
                      "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
