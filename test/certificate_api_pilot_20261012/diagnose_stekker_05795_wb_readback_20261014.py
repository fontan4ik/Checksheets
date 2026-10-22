"""Read back only Stekker 05795/22 WB discrepancies without mutation or logs."""
from __future__ import annotations

import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from api_client import BASE, Client
from preflight_stekker_05795_20261014 import read_wb_cards

PREFLIGHT = BASE / "stekker_05795_live_preflight_20261014.json"
VERIFY = BASE / "stekker_05795_verification_20261014.json"
EXEC = BASE / "stekker_05795_execution_20261014.json"
OUT = BASE / "stekker_05795_wb_discrepancy_readback_20261014.json"
SUFFIX = "0579522"


def digits(value: object) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def doc_signature(doc: dict) -> tuple:
    return (int(doc.get("type") or 0), digits(doc.get("number")),
            str(doc.get("startDate") or "")[:10], str(doc.get("endDate") or "")[:10],
            bool(doc.get("isEndless", False)))


def main() -> None:
    old = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    verification = json.loads(VERIFY.read_text(encoding="utf-8"))
    execution = json.loads(EXEC.read_text(encoding="utf-8"))
    mismatches = sorted(set(verification["wb_missing_or_conflicting_rows"])
                        | {x["offer_id"] for x in verification["wb_unrelated_field_or_prior_doc_conflicts"]})
    old_cards = {row["offer_id"]: row["cards"][0] for row in old["wb_cards_by_offer"]
                 if len(row["cards"]) == 1}
    client = Client()
    result = []
    for offer in mismatches:
        cards = [x for x in read_wb_cards(client, offer) if x.get("vendorCode") == offer]
        documents = []
        for card in cards:
            docs = card.get("documents") or {}
            target = [x for x in docs.get("items") or [] if digits(x.get("number")).endswith(SUFFIX)]
            documents.append({
                "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"),
                "target_rows": [{"type": x.get("type"), "number": x.get("number"),
                                 "startDate": x.get("startDate"), "endDate": x.get("endDate"),
                                 "isEndless": x.get("isEndless"), "verdict": x.get("verdict")}
                                for x in target],
                "overallVerdict": docs.get("overallVerdict"),
                "excludeDocuments": docs.get("excludeDocuments"),
                "document_count": len(docs.get("items") or []),
            })
            before = old_cards.get(offer)
            if before:
                fields = ("nmID", "vendorCode", "brand", "title", "gtin", "description",
                          "dimensions", "characteristics", "sizes", "kizMarked")
                changed = [field for field in fields if before.get(field) != card.get(field)]
                documents[-1]["preflight_changed_card_fields"] = changed
                documents[-1]["preflight_changed_non_characteristic_fields"] = [
                    field for field in changed if field != "characteristics"]
                old_chars = {int(x.get("id", -1)): x for x in before.get("characteristics") or []}
                new_chars = {int(x.get("id", -1)): x for x in card.get("characteristics") or []}
                documents[-1]["changed_characteristics"] = [
                    {"id": key, "name": value.get("name"), "value": value.get("value")}
                    for key, value in new_chars.items() if old_chars.get(key) != value]
                documents[-1]["removed_characteristic_ids"] = sorted(set(old_chars) - set(new_chars))
                before_docs = collections.Counter(doc_signature(x) for x in
                    (((before.get("documents") or {}).get("items") or [])))
                after_docs = collections.Counter(doc_signature(x) for x in
                    ((docs.get("items") or [])))
                documents[-1]["preflight_prior_document_rows_preserved"] = all(
                    after_docs[sig] >= count for sig, count in before_docs.items())
        result.append({"offer_id": offer, "card_count": len(cards), "cards": documents})
    output = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "read_only": True, "offers_checked": mismatches, "rows": result}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"read_only": True, "offers_checked": len(mismatches),
                      "offer_results": [{"offer_id": x["offer_id"], "card_count": x["card_count"],
                                         "target_rows": [len(c["target_rows"]) for c in x["cards"]],
                                         "changed_fields": [c.get("preflight_changed_card_fields") for c in x["cards"]]}
                                        for x in result],
                      "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
