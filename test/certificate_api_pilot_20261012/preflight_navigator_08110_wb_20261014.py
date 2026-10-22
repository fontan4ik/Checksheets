"""Read-only exact-card WB preflight for Navigator 08110/24."""
from __future__ import annotations

import collections
import csv
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402
from preflight_arlight_06897_exact_20261014 import norm  # noqa: E402

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT = BASE / "navigator_08110_wb_live_preflight_20261014.json"
NUMBER = "ЕАЭС N RU Д-CN.РА11.В.08110/24"
ISSUE, EXPIRY = "2024-12-02", "2029-12-01"
FSA_TNVED = {"8539520001", "8539520003", "8539520009"}
WB_TNVED_CHAR_ID = 15000001


def save(data: dict) -> None:
    temp = OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(OUT)


def wb_post(client: Client, payload: dict) -> tuple[int, dict]:
    for attempt in range(7):
        response = client.http.post("https://content-api.wildberries.ru/content/v2/get/cards/list",
                                    json=payload, headers=client.wb_headers, timeout=(15, 120))
        try:
            body = response.json()
        except ValueError:
            body = {"non_json_response": True}
        if response.status_code == 429 or response.status_code in (500, 502, 503, 504):
            if attempt == 6:
                raise RuntimeError(f"WB card read failed after retries: HTTP {response.status_code}")
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(float(retry_after), 1.0) if retry_after else min(60, 2 ** (attempt + 1))
            except ValueError:
                delay = min(60, 2 ** (attempt + 1))
            print(f"WB read HTTP {response.status_code}; waiting {delay:g}s", flush=True)
            time.sleep(delay)
            continue
        time.sleep(1.05)
        return response.status_code, body
    raise RuntimeError("Unreachable WB retry state")


def read_assignments() -> list[dict]:
    rows = []
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if "08110/24" in str(row.get("Номер/название документа") or ""):
                rows.append(row)
    by_offer = {str(x.get("Артикул продавца") or "").strip(): x for x in rows}
    if len(rows) != 155 or len(by_offer) != 155 or "" in by_offer:
        raise RuntimeError(f"Expected 155 unique source offers, got {len(rows)}/{len(by_offer)}")
    return [by_offer[k] for k in sorted(by_offer)]


def read_exact_card(client: Client, offer: str) -> list[dict]:
    cards, cursor, seen = [], {"limit": 100}, set()
    for _ in range(100):
        status, body = wb_post(client, {"settings": {"sort": {"ascending": True}, "cursor": cursor,
                                        "filter": {"withPhoto": -1, "textSearch": offer}}})
        if status != 200 or body.get("error") or not isinstance(body.get("cards"), list):
            raise RuntimeError(f"WB exact-card read failed for {offer}: HTTP {status}")
        batch, page = body["cards"], body.get("cursor") or {}
        if page.get("total") != len(batch):
            raise RuntimeError(f"WB cursor count mismatch for {offer}")
        cards.extend(x for x in batch if str(x.get("vendorCode") or "") == offer)
        if len(batch) < 100:
            return cards
        marker = (str(page.get("updatedAt") or ""), str(page.get("nmID") or ""))
        if not all(marker) or marker in seen:
            raise RuntimeError(f"WB cursor repeated for {offer}")
        seen.add(marker)
        cursor = {"limit": 100, "updatedAt": marker[0], "nmID": int(marker[1])}
    raise RuntimeError(f"WB pagination exceeded for {offer}")


def card_summary(card: dict, offer: str) -> dict:
    raw_codes = [str(v) for ch in card.get("characteristics") or []
                 if str(ch.get("id")) == str(WB_TNVED_CHAR_ID)
                 for v in ch.get("value") or []]
    codes = sorted({v.split(" ", 1)[0].strip() for v in raw_codes if v.strip()})
    docs_obj = card.get("documents") or {}
    docs = docs_obj.get("items") or []
    match = [d for d in docs if norm(d.get("number")) == norm(NUMBER)]
    return {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "vendorCode": str(card.get("vendorCode") or ""), "brand": card.get("brand"),
            "title": card.get("title"), "tnved_values": raw_codes, "tnved_codes": codes,
            "excludeDocuments": docs_obj.get("excludeDocuments"), "exact_08110_rows": match,
            "other_document_count": len(docs), "card_raw": card}


def main() -> None:
    rows = read_assignments()
    previous = {}
    done = 0
    if OUT.exists():
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        if saved.get("complete"):
            raise RuntimeError(f"Complete WB preflight already exists: {OUT}")
        done = int(saved.get("targets_completed") or 0)
        previous = {x["offer_id"]: x for x in saved.get("targets") or []}
        if not 0 <= done < 155 or len(previous) != 155:
            raise RuntimeError("Partial WB preflight is inconsistent")
        print(f"Resuming from {done}/155", flush=True)
    client = Client()
    targets = []
    for i, source in enumerate(rows, 1):
        offer = str(source["Артикул продавца"])
        if i <= done:
            target = previous.get(offer)
            if not target or not target.get("wb_cards"):
                raise RuntimeError(f"Saved WB result missing for {offer}")
            targets.append(target)
            continue
        cards = read_exact_card(client, offer)
        target = {"offer_id": offer, "source_article_evidence": source.get("Основание сопоставления"),
                  "source_product_url": source.get("URL карточки/основания"),
                  "source_pdf_url": source.get("URL документа"), "wb_cards": [card_summary(c, offer) for c in cards]}
        targets.append(target)
        if i % 10 == 0 or i == len(rows):
            partial = {"checked_at_utc": now(), "read_only": True, "complete": False,
                       "targets_completed": i, "target_count": len(rows), "number": NUMBER,
                       "targets": targets + [{"offer_id": r["Артикул продавца"]}
                                             for r in rows[i:]]}
            save(partial)
            print(f"WB Navigator read {i}/155", flush=True)
    if len(targets) != 155:
        raise RuntimeError("WB target set is incomplete")
    statuses, brands, codes = collections.Counter(), collections.Counter(), collections.Counter()
    missing, multiple, docs, errors = 0, 0, 0, []
    for target in targets:
        cards = target.get("wb_cards") or []
        statuses["unique" if len(cards) == 1 else "missing_or_ambiguous"] += 1
        if len(cards) != 1:
            errors.append({"offer_id": target["offer_id"], "reason": f"exact_card_count_{len(cards)}"})
            continue
        card = cards[0]
        brands[str(card.get("brand") or "<missing>")] += 1
        for code in card.get("tnved_codes") or []: codes[code] += 1
        if not card.get("tnved_codes"): missing += 1
        if len(card.get("exact_08110_rows") or []): docs += 1
        if len(card.get("exact_08110_rows") or []) > 1:
            multiple += 1
        if str(card.get("vendorCode") or "") != target["offer_id"]:
            errors.append({"offer_id": target["offer_id"], "reason": "vendor_code_conflict"})
    result = {"checked_at_utc": now(), "read_only": True, "complete": True, "number": NUMBER,
              "target_count": len(targets), "card_counts": dict(statuses),
              "wb_brand_counts": dict(brands), "wb_tnved_counts": dict(codes),
              "wb_missing_tnved_cards": missing, "wb_cards_with_exact_08110_row": docs,
              "wb_duplicate_exact_08110_rows": multiple, "errors": errors,
              "marketplace_mutation_sent": False, "targets": targets}
    save(result)
    print(json.dumps({k: v for k, v in result.items() if k != "targets"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
