"""Read-only exact-card status recheck for previously accepted WB updates."""
import json
from pathlib import Path
from api_client import Client, now, save

BASE = Path(__file__).resolve().parent
client = Client()
checks = []
for spec in [
    ("ЕАЭС N RU Д-CN.PA06.B.53483/22", BASE / "feron_53483_wb_execution_20261013.json"),
    ("ЕАЭС RU С-RU.АД38.В.00103/25", BASE / "alphacable_00103_live_preflight_20261013.json"),
]:
    number, path = spec
    source = json.loads(path.read_text(encoding="utf-8"))
    targets = source.get("targets") or source.get("ozon", {}).get("products") or []
    for target in targets:
        offer = target.get("offer_id")
        expected_nmid = str(target.get("nmID") or target.get("expected_nmID") or "")
        if not offer:
            continue
        found = [c for c in client.wb_cards(offer) if c.get("vendorCode") == offer and
                 (not expected_nmid or str(c.get("nmID")) == expected_nmid)]
        rows = []
        for card in found:
            docs = (card.get("documents") or {}).get("items") or []
            matching = [d for d in docs if str(d.get("number", "")).replace(" ", "").upper() == number.replace(" ", "").upper()
                        or (number.replace("РА", "PA").replace("В", "B") in str(d.get("number", "")).replace(" ", "").upper())]
            rows.append({
                "nmID": str(card.get("nmID")),
                "updatedAt": card.get("updatedAt"),
                "brand": card.get("brand"),
                "document_count": len(docs),
                "matching_rows": [{"type": d.get("type"), "number": d.get("number"), "startDate": d.get("startDate"),
                                   "endDate": d.get("endDate"), "verdict": d.get("verdict")} for d in matching],
                "overallVerdict": (card.get("documents") or {}).get("overallVerdict"),
                "excludeDocuments": (card.get("documents") or {}).get("excludeDocuments"),
            })
        checks.append({"document_number": number, "offer_id": offer, "expected_nmID": expected_nmid,
                       "card_matches": len(rows), "cards": rows})
result = {"checked_at_utc": now(), "read_only": True, "documents": {}, "checks": checks}
for number in sorted({x["document_number"] for x in checks}):
    related = [x for x in checks if x["document_number"] == number]
    result["documents"][number] = {
        "target_count": len(related),
        "cards_found": sum(x["card_matches"] == 1 for x in related),
        "rows_visible": sum(bool(c["matching_rows"]) for x in related for c in x["cards"]),
        "verified_rows": sum(1 for x in related for c in x["cards"] for r in c["matching_rows"]
                             if (r.get("verdict") or {}).get("verified") is True and
                             (r.get("verdict") or {}).get("status") == 1),
        "item_verdict_counts": {},
    }
    counts = result["documents"][number]["item_verdict_counts"]
    for x in related:
        for c in x["cards"]:
            for r in c["matching_rows"]:
                verdict = r.get("verdict") or {}
                key = f"{verdict.get('status')}:{verdict.get('reason')}:{verdict.get('verified')}"
                counts[key] = counts.get(key, 0) + 1
save("wb_async_upload_recheck_20261013_1359Z.json", result)
print(json.dumps({"checked_at_utc": result["checked_at_utc"], "documents": result["documents"]}, ensure_ascii=False, indent=2))
