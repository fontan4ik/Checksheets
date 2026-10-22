"""Read-only full WB-catalog refresh for Arlight declaration 46569/26."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import doc_key, norm_number, wb_datetime  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.46569/26"
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"
ALLOWED = {"8539519009"}
PREFLIGHT = json.loads((HERE / "arlight_46569_preflight_live_20261021.json").read_text())
OZON = json.loads((HERE / "arlight_46569_ozon_final_readback_20261021.json").read_text())
OUT = HERE / "arlight_46569_wb_fresh_readback_20261021.json"
if OUT.exists():
    raise RuntimeError("output_exists")
targets = {str(row["offer_id"]): row for row in PREFLIGHT["wb_targets"]}
if len(targets) != 905 or not OZON.get("complete"):
    raise RuntimeError("verified_crossplatform_targets_missing")


def codes(card: dict) -> list[str]:
    found = []
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        values = raw if isinstance(raw, list) else [raw]
        found.extend(str(value or "").split(" - ", 1)[0].strip() for value in values if value)
    return sorted(set(found))


client = Client()
found: dict[str, list[dict]] = collections.defaultdict(list)
cursor = {"limit": 100}
seen = set()
pages = card_count = 0
wanted = set(targets)
while True:
    response = client.call("wb", "/content/v2/get/cards/list", {"settings": {
        "sort": {"ascending": True}, "cursor": cursor,
        "filter": {"withPhoto": -1},
    }})
    batch = response.get("cards")
    if response.get("error") or not isinstance(batch, list):
        raise RuntimeError("wb_catalog_page_invalid")
    returned = response.get("cursor") or {}
    if returned.get("total") != len(batch):
        raise RuntimeError("wb_catalog_page_count_mismatch")
    pages += 1
    card_count += len(batch)
    for card in batch:
        offer = str(card.get("vendorCode") or "")
        if offer in wanted:
            found[offer].append(card)
    if pages % 50 == 0:
        print(json.dumps({"phase": "read_only_full_catalog", "pages": pages,
                          "cards_read": card_count, "targets_found": sum(map(len, found.values()))}), flush=True)
    if len(batch) < 100:
        break
    signature = (returned.get("updatedAt"), returned.get("nmID"))
    if None in signature or signature in seen:
        raise RuntimeError("wb_catalog_cursor_missing_or_repeated")
    seen.add(signature)
    cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}

desired = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
           "endDate": wb_datetime(EXPIRY), "isEndless": False}
rows = []
status_counts = collections.Counter()
for offer, target in sorted(targets.items()):
    cards = found.get(offer, [])
    if len(cards) != 1:
        rows.append({"offer_id": offer, "verified": False, "problem": "missing_or_duplicate_exact_card",
                     "card_count": len(cards)})
        continue
    card = cards[0]
    docs = ((card.get("documents") or {}).get("items") or [])
    same = [doc for doc in docs if norm_number(doc.get("number")) == norm_number(NUMBER)]
    exact = [doc for doc in same if doc_key(doc) == doc_key(desired)
             and str(doc.get("startDate", ""))[:10] == ISSUE
             and str(doc.get("endDate", ""))[:10] == EXPIRY
             and doc.get("isEndless") is False]
    brand_ok = str(card.get("brand") or "").strip().casefold() == "arlight"
    codes_now = codes(card)
    code_ok = codes_now == sorted(ALLOWED)
    nmid_ok = str(card.get("nmID") or "") == str(target.get("nmID") or "")
    verdict = exact[0].get("verdict") if len(exact) == 1 else None
    status = ("valid" if verdict and verdict.get("verified") is True and verdict.get("reason") == "valid"
              else "invalid" if verdict and verdict.get("verified") is True
              else "pending_or_missing_verdict")
    status_counts[status] += 1
    okay = len(same) == 1 and len(exact) == 1 and brand_ok and code_ok and nmid_ok and status == "valid"
    rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""), "verified": okay,
                 "exact_document_count": len(same), "metadata_exact": len(exact) == 1,
                 "brand_exact": brand_ok, "tnved_codes": codes_now, "tnved_exact": code_ok,
                 "nmID_exact": nmid_ok, "document_status": status, "verdict": verdict})

failures = [row for row in rows if not row.get("verified")]
result = {"checked_at": now(), "read_only": True, "number": NUMBER,
          "pages": pages, "cards_read": card_count, "expected_target_cards": len(targets),
          "matched_target_cards": sum(len(found.get(offer, [])) == 1 for offer in targets),
          "verified_target_cards": len(rows) - len(failures), "status_counts": dict(status_counts),
          "complete": len(rows) == 905 and not failures, "failures": failures,
          "cards": rows, "review_left_to_wb": True}
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(OUT)
print(json.dumps({key: value for key, value in result.items() if key not in {"cards", "failures"}},
                 ensure_ascii=False, indent=2))
if failures:
    print(json.dumps({"failure_samples": failures[:25]}, ensure_ascii=False, indent=2))
    raise RuntimeError("fresh_wb_readback_incomplete")
