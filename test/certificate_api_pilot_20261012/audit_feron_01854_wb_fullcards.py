"""Fresh read-only full-card audit for Feron 01854/22 WB offers."""
from __future__ import annotations

import json
import time
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
PLAN = BASE / "feron_01854_ozon_plan.json"
OZON_AUDIT = BASE / "feron_01854_ozon_reconciliation_20261012.json"
OUT = BASE / "feron_01854_wb_fullcards_20261012.json"
NUMBER_OLD = "ЕАЭС RU C-CN.HA83.B.01854/22"
NUMBER_FSA = "ЕАЭС RU С-CN.НА83.В.01854/22"
ISSUE_DATE = "2022-04-11"
EXPIRY_DATE = "2027-04-10"


def write(state: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)


def main() -> None:
    if OUT.exists():
        raise RuntimeError("Read-only audit artifact already exists; inspect it before another read")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ozon = json.loads(OZON_AUDIT.read_text(encoding="utf-8"))
    targets = plan.get("targets") or []
    ozon_codes = {str(row["offer_id"]): row.get("tnved_attribute_22232", [])
                  for row in ozon.get("tnved_attribute_rows", [])}
    if len(targets) != 188 or len({x["offer_id"] for x in targets}) != 188:
        raise RuntimeError("Ozon plan target identity set changed")
    if set(ozon_codes) != {x["offer_id"] for x in targets}:
        raise RuntimeError("Ozon TNVED audit does not cover the WB target offer set")

    client = Client()
    state = {"started_at": now(), "complete": False, "target_count": len(targets),
             "read_count": 0, "cards_by_offer": {}, "missing": [], "duplicates": [],
             "failures": [], "ozon_tnved_by_offer": ozon_codes}
    write(state)
    for index, target in enumerate(sorted(targets, key=lambda x: x["offer_id"]), 1):
        offer = target["offer_id"]
        try:
            cards = client.wb_cards(offer)
            if len(cards) == 0:
                state["missing"].append(offer)
            elif len(cards) != 1:
                state["duplicates"].append({"offer_id": offer, "nmIDs": [str(x.get("nmID")) for x in cards]})
            else:
                card = cards[0]
                if str(card.get("vendorCode")) != offer:
                    raise RuntimeError("exact vendorCode mismatch")
                card["_ozon_tnved_attribute_22232"] = ozon_codes[offer]
                state["cards_by_offer"][offer] = card
        except Exception as exc:
            state["failures"].append({"offer_id": offer, "error_type": type(exc).__name__, "error": str(exc)})
        state["read_count"] = index
        state["updated_at"] = now()
        if index % 20 == 0 or index == len(targets):
            write(state)
            print(json.dumps({"read": index, "target_count": len(targets),
                              "cards": len(state["cards_by_offer"]),
                              "missing": len(state["missing"]),
                              "duplicates": len(state["duplicates"]),
                              "failures": len(state["failures"])}, ensure_ascii=False), flush=True)
        time.sleep(0.55)

    document_variants = {}
    tnved_counts = {}
    out_of_scope = []
    fsa_codes = {"9405190029", "9405190039", "9405190015"}
    for offer, card in state["cards_by_offer"].items():
        docs = ((card.get("documents") or {}).get("items") or [])
        matches = [d for d in docs if int(d.get("type") or 0) == 1
                   and str(d.get("number", "")).endswith("01854/22")]
        if len(matches) == 1:
            d = matches[0]
            key = str(d.get("number"))
            document_variants[key] = document_variants.get(key, 0) + 1
            if str(d.get("startDate", ""))[:10] != ISSUE_DATE or str(d.get("endDate", ""))[:10] != EXPIRY_DATE:
                state["failures"].append({"offer_id": offer, "error_type": "existing_document_date_mismatch"})
        else:
            state["failures"].append({"offer_id": offer, "error_type": "missing_or_duplicate_01854_rows",
                                      "match_count": len(matches)})
        codes = card.get("_ozon_tnved_attribute_22232") or []
        tnved_counts[" | ".join(codes) if codes else "(missing)"] = tnved_counts.get(" | ".join(codes) if codes else "(missing)", 0) + 1
        normalized_codes = {code.split(" ", 1)[0] for code in codes}
        if normalized_codes and not normalized_codes.issubset(fsa_codes):
            out_of_scope.append({"offer_id": offer, "nmID": str(card.get("nmID")), "tnved_codes": sorted(normalized_codes)})

    state["document_number_variants"] = document_variants
    state["tnved_counts_by_offer"] = tnved_counts
    state["offers_with_tnved_codes_outside_fsa_scope"] = out_of_scope
    state["complete"] = state["read_count"] == len(targets) and len(state["cards_by_offer"]) + len(state["missing"]) + len(state["duplicates"]) == len(targets) and not state["failures"]
    state["updated_at"] = now()
    write(state)
    print(json.dumps({"complete": state["complete"], "target_count": len(targets),
                      "cards": len(state["cards_by_offer"]), "missing": state["missing"],
                      "duplicates": state["duplicates"], "failures": state["failures"],
                      "document_number_variants": document_variants,
                      "tnved_counts_by_offer": tnved_counts,
                      "offers_with_tnved_codes_outside_fsa_scope": out_of_scope,
                      "audit_path": str(OUT)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
