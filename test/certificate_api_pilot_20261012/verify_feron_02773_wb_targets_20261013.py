"""Current targeted WB readback for all Feron 02773/24 source-mapped articles."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
SOURCE = json.loads((BASE / "feron_02773_live_verification.json").read_text(encoding="utf-8"))
PRIOR_WB = json.loads((BASE / "wb_live.json").read_text(encoding="utf-8"))
NUMBER = SOURCE["certificate"]["canonical_number"]
ISSUE = SOURCE["certificate"]["issue_date"]
EXPIRY = SOURCE["certificate"]["expiry_date"]

def normalize(value: object) -> str:
    homoglyphs = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
                                "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                                "У": "Y", "Х": "X", "Ё": "E"})
    return "".join(ch for ch in str(value or "").upper().translate(homoglyphs) if ch.isalnum())

targets = SOURCE["workbook"]["targets"]
by_offer = {str(row["offer_id"]): row for row in targets}
if len(by_offer) != 159 or len({str(row["feron_article"]) for row in targets}) != 133:
    raise RuntimeError("Source scope matrix changed from 159 offers / 133 Feron articles")
prior_cards = {str(card.get("vendorCode")): card for card in PRIOR_WB.get("cards") or []}
expected_exact = {
    offer: prior_cards[offer]
    for offer in by_offer
    if offer in prior_cards and prior_cards[offer].get("vendorCode") == offer
}
if len(expected_exact) != 135:
    raise RuntimeError(f"Expected 135 exact WB cards from the last complete WB snapshot, got {len(expected_exact)}")

client = Client()
live_cards: dict[str, dict] = {}
missing_exact: list[str] = []
problems: list[dict] = []
for index, offer in enumerate(sorted(by_offer), 1):
    found = client.wb_cards(offer)
    exact = [card for card in found if str(card.get("vendorCode")) == offer]
    if not exact:
        missing_exact.append(offer)
        continue
    if len(exact) != 1:
        problems.append({"offer_id": offer, "problem": "multiple exact vendorCode cards",
                         "nmIDs": [str(x.get("nmID")) for x in exact]})
        continue
    card = exact[0]
    if not card.get("nmID"):
        problems.append({"offer_id": offer, "problem": "exact WB card has no nmID"})
        continue
    baseline = expected_exact.get(offer)
    if baseline and str(baseline.get("nmID")) != str(card.get("nmID")):
        problems.append({"offer_id": offer, "problem": "WB nmID changed from last complete snapshot",
                         "expected_nmID": str(baseline.get("nmID")), "actual_nmID": str(card.get("nmID"))})
        continue
    docs = card.get("documents") or {}
    exact_docs = [doc for doc in docs.get("items") or []
                  if int(doc.get("type", 0)) == 1
                  and normalize(doc.get("number")) == normalize(NUMBER)
                  and str(doc.get("startDate", ""))[:10] == ISSUE
                  and str(doc.get("endDate", ""))[:10] == EXPIRY]
    if (len(exact_docs) != 1 or docs.get("excludeDocuments") is not False
            or (exact_docs[0].get("verdict") or {}).get("verified") is not True
            or (exact_docs[0].get("verdict") or {}).get("status") != 1
            or (exact_docs[0].get("verdict") or {}).get("reason") != "valid"
            or (docs.get("overallVerdict") or {}).get("isFullyChecked") is not True
            or (docs.get("overallVerdict") or {}).get("status") != 1):
        problems.append({"offer_id": offer, "nmID": str(card["nmID"]),
                         "problem": "document or overall verdict is not finally valid",
                         "matching_document_count": len(exact_docs),
                         "excludeDocuments": docs.get("excludeDocuments"),
                         "document_verdicts": [x.get("verdict") for x in exact_docs],
                         "overallVerdict": docs.get("overallVerdict")})
        continue
    live_cards[offer] = {
        "offer_id": offer,
        "nmID": str(card["nmID"]),
        "feron_article": str(by_offer[offer]["feron_article"]),
        "document_number": exact_docs[0].get("number"),
        "document_type": exact_docs[0].get("type"),
        "startDate": str(exact_docs[0].get("startDate", ""))[:10],
        "endDate": str(exact_docs[0].get("endDate", ""))[:10],
        "document_verdict": exact_docs[0].get("verdict"),
        "overallVerdict": docs.get("overallVerdict"),
    }
    if index % 25 == 0:
        print(json.dumps({"offers_checked": index, "exact_cards": len(live_cards),
                          "no_exact_vendorCode": len(missing_exact), "problems": len(problems)},
                         ensure_ascii=False), flush=True)

articles = {str(x["feron_article"]) for x in targets}
covered_articles = {row["feron_article"] for row in live_cards.values()}
article_missing = sorted(articles - covered_articles)
result = {
    "checked_at_utc": now(),
    "read_method": "Live WB textSearch by each of 159 source offer codes; exact vendorCode filtered and individually read back",
    "source_target_offer_count": len(targets),
    "source_target_article_count": len(articles),
    "baseline_exact_card_count": len(expected_exact),
    "current_exact_card_count": len(live_cards),
    "current_exact_cards": live_cards,
    "offers_without_exact_wb_vendorCode": missing_exact,
    "uncovered_target_articles": article_missing,
    "problems": problems,
    "articles_covered_by_current_valid_exact_cards": len(covered_articles),
    "all_current_exact_cards_finally_valid": bool(live_cards) and not problems,
    "all_133_target_articles_have_current_valid_wb_card": len(covered_articles) == len(articles) and not article_missing,
    "all_target_offers_resolved_by_exact_card_or_same_article_card": (
        not problems and len(covered_articles) == len(articles) and not article_missing
    ),
    "wb_rows_all_valid": not problems and len(live_cards) == len(expected_exact),
}
save("feron_02773_wb_targets_verification_20261013.json", result)
print(json.dumps({k: v for k, v in result.items() if k != "current_exact_cards"}, ensure_ascii=False, indent=2))
if not result["all_target_offers_resolved_by_exact_card_or_same_article_card"]:
    raise RuntimeError("Current targeted WB verification is incomplete or found invalid rows")
