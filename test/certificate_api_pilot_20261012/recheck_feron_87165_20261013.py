"""Fresh read-only reconciliation for Feron declaration 87165/22 on Ozon and WB."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
PLAN = json.loads((BASE / "feron_87165_ozon_plan.json").read_text(encoding="utf-8"))
NUMBER = PLAN["number"]
EXPECTED_ISSUE = PLAN["issue_date"]
EXPECTED_EXPIRY = PLAN["expire_date"]


def norm(value: object) -> str:
    homoglyphs = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
                                "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                                "У": "Y", "Х": "X", "Ё": "E"})
    return "".join(ch for ch in str(value or "").upper().translate(homoglyphs) if ch.isalnum())


client = Client()
targets = PLAN["targets"]
expected = {str(x["sku"]): str(x["product_id"]) for x in targets}
if len(expected) != 13 or len(targets) != 13:
    raise RuntimeError("The source-mapped Ozon target set changed")

info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
if not isinstance(info, dict) or str(info.get("certificate_id")) != "5610374":
    raise RuntimeError("Current Ozon certificate identity differs from the saved execution")
bindings = client.ozon_bindings(int(info["certificate_id"]))
by_sku: dict[str, dict] = {}
duplicates: list[str] = []
for row in bindings:
    sku = str(row.get("sku") or "")
    if not sku or sku in by_sku:
        duplicates.append(sku or "<missing>")
    else:
        by_sku[sku] = row
missing = sorted(set(expected) - set(by_sku))
unexpected = sorted(set(by_sku) - set(expected))
id_mismatches = [
    {"sku": sku, "expected_product_id": expected[sku],
     "actual_product_id": str(by_sku[sku].get("product_id") or "")}
    for sku in sorted(set(expected) & set(by_sku))
    if expected[sku] != str(by_sku[sku].get("product_id") or "")
]
ozon_statuses = collections.Counter(str(x.get("product_status_code") or "MISSING") for x in bindings)
ozon_ok = (len(bindings) == len(expected) and not missing and not unexpected
           and not duplicates and not id_mismatches)

wb_cards: dict[str, dict] = {}
wb_missing: list[str] = []
wb_problems: list[dict] = []
for target in sorted(targets, key=lambda x: str(x["offer_id"])):
    offer = str(target["offer_id"])
    found = client.wb_cards(offer)
    exact = [card for card in found if str(card.get("vendorCode")) == offer]
    if not exact:
        wb_missing.append(offer)
        continue
    if len(exact) != 1:
        wb_problems.append({"offer_id": offer, "problem": "multiple exact vendorCode cards",
                            "nmIDs": [str(x.get("nmID")) for x in exact]})
        continue
    card = exact[0]
    docs = card.get("documents") or {}
    matches = [d for d in docs.get("items") or []
               if int(d.get("type", 0)) == 2 and norm(d.get("number")) == norm(NUMBER)
               and str(d.get("startDate", ""))[:10] == EXPECTED_ISSUE
               and str(d.get("endDate", ""))[:10] == EXPECTED_EXPIRY]
    valid = (len(matches) == 1 and docs.get("excludeDocuments") is False
             and (matches[0].get("verdict") or {}).get("verified") is True
             and (matches[0].get("verdict") or {}).get("status") == 1
             and (matches[0].get("verdict") or {}).get("reason") == "valid"
             and (docs.get("overallVerdict") or {}).get("isFullyChecked") is True
             and (docs.get("overallVerdict") or {}).get("status") == 1)
    if not card.get("nmID") or not valid:
        wb_problems.append({"offer_id": offer, "problem": "card or declaration lacks final valid readback",
                            "nmID": str(card.get("nmID") or ""), "matching_document_count": len(matches),
                            "excludeDocuments": docs.get("excludeDocuments"),
                            "document_verdicts": [d.get("verdict") for d in matches],
                            "overallVerdict": docs.get("overallVerdict")})
        continue
    wb_cards[offer] = {
        "offer_id": offer, "nmID": str(card["nmID"]),
        "document_number": matches[0].get("number"), "document_type": matches[0].get("type"),
        "startDate": str(matches[0].get("startDate", ""))[:10],
        "endDate": str(matches[0].get("endDate", ""))[:10],
        "document_verdict": matches[0].get("verdict"),
        "overallVerdict": docs.get("overallVerdict"),
    }

result = {
    "checked_at_utc": now(), "read_only": True,
    "certificate_number": NUMBER,
    "date_note": PLAN.get("date_note"),
    "ozon": {
        "certificate_id": str(info.get("certificate_id")),
        "stored_number": info.get("certificate_number"),
        "record_status": info.get("status_code"), "type_code": info.get("type_code"),
        "issue_date": str(info.get("issue_date", ""))[:10],
        "expire_date": str(info.get("expire_date", ""))[:10],
        "target_count": len(expected), "binding_count": len(bindings),
        "binding_status_counts": dict(ozon_statuses), "missing_skus": missing,
        "unexpected_skus": unexpected, "duplicate_skus": sorted(duplicates),
        "product_id_mismatches": id_mismatches, "full_exact_target_set_bound": ozon_ok,
        "all_bindings_approved": bool(bindings) and set(ozon_statuses) == {"approved"},
    },
    "wb": {
        "target_offer_count": len(targets), "exact_cards_finally_valid_count": len(wb_cards),
        "current_exact_cards": wb_cards, "offers_without_exact_wb_vendorCode": wb_missing,
        "problems": wb_problems,
        "all_exact_target_cards_finally_valid": len(wb_cards) == len(targets) and not wb_missing and not wb_problems,
    },
}
save("feron_87165_status_latest_20261013.json", result)
print(json.dumps({
    "checked_at_utc": result["checked_at_utc"],
    "ozon": {k: v for k, v in result["ozon"].items() if k not in {"binding_status_counts"}},
    "wb": {k: v for k, v in result["wb"].items() if k != "current_exact_cards"},
}, ensure_ascii=False, indent=2))
