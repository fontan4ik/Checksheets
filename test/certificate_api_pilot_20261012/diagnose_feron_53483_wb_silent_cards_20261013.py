"""Read-only comparison of the five unchanged Feron cards with one successful peer."""
from __future__ import annotations

import json

from api_client import BASE, Client, now, save

OUT = "feron_53483_wb_silent_cards_diagnostic_20261013.json"
TARGETS = ["21488-1", "21496-1", "21499-1", "41349-1", "41350-1"]
CONTROL = "21480-1"
NUMBER = "ЕАЭС N RU Д-CN.PA06.B.53483/22"


def main() -> None:
    client = Client()
    cards = []
    for offer in TARGETS + [CONTROL]:
        found = client.wb_cards(offer)
        if len(found) != 1 or str(found[0].get("vendorCode") or "") != offer:
            raise RuntimeError(f"Expected one exact WB card for {offer}")
        card = found[0]
        docs = card.get("documents") or card.get("docs") or {}
        chars = card.get("characteristics") or []
        rows = docs.get("items") or []
        cards.append({
            "offer_id": offer,
            "nmID": str(card.get("nmID") or ""),
            "updatedAt": card.get("updatedAt"),
            "brand": card.get("brand"),
            "subjectID": card.get("subjectID"),
            "subjectName": card.get("subjectName"),
            "title": card.get("title"),
            "characteristics_count": len(chars),
            "certificate_brand_characteristics": [x for x in chars if "бренд" in str(x.get("name") or "").casefold()],
            "excludeDocuments": docs.get("excludeDocuments"),
            "matching_document_rows": [x for x in rows if x.get("number") == NUMBER],
            "document_rows_count": len(rows),
            "overallVerdict": docs.get("overallVerdict"),
        })
    subject_ids = sorted({int(x["subjectID"]) for x in cards if x.get("subjectID") is not None})
    brand_lists = {}
    for subject_id in subject_ids:
        body = client.call("wb", f"/api/content/v1/brands?subjectId={subject_id}", {}, method="GET")
        brands = body.get("brands") or []
        brand_lists[str(subject_id)] = {
            "count": len(brands),
            "feron_exact_matches": [x for x in brands if str(x.get("name") or "").casefold() == "feron"],
        }
    state = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
             "target_count": len(TARGETS), "control_offer": CONTROL,
             "cards": cards, "brand_directory": brand_lists}
    save(OUT, state)
    print(json.dumps({"artifact": str(BASE / OUT), "checked_at_utc": state["checked_at_utc"],
                      "cards": [{k: x.get(k) for k in ("offer_id", "nmID", "brand", "subjectID", "subjectName", "updatedAt", "matching_document_rows")}
                                for x in cards],
                      "brand_directory": brand_lists}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
