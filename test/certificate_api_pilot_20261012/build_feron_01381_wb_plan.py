"""Build a conservative full-card WB metadata plan for FERON certificate 01381/22."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from api_client import now, save
from pilot_upload import FIELDS, norm

BASE = Path(__file__).resolve().parent
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")
NUMBER = "ЕАЭС RU C-CN.HB85.B.01381/22"
ISSUE = "2022-09-08"
EXPIRY = "2027-09-07"
FILE_SHA256 = "0022cee06f811dfc5f32f69ecc042b00a10f7c7eb8e64930bcd66ce725ee60ce"


def datepart(value: object) -> str:
    return str(value or "")[:10]


def doc_type(value: object) -> int:
    if isinstance(value, str) and not value.isdigit():
        return {"certificate_of_conformity": 1, "declaration": 2}.get(value.lower(), 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def chunks(updates: list[dict]) -> list[dict]:
    out = []
    current = []
    for update in updates:
        candidate = current + [update]
        size = len(json.dumps([item["payload"] for item in candidate], ensure_ascii=False,
                              separators=(",", ":")).encode())
        if current and (len(candidate) > 250 or size > 9_000_000):
            payloads = [item["payload"] for item in current]
            start = sum(item["cards"] for item in out)
            out.append({"update_indexes": list(range(start, start + len(current))),
                        "cards": len(current), "request_bytes": len(json.dumps(payloads, ensure_ascii=False,
                                                                                 separators=(",", ":")).encode()),
                        "nmIDs": [str(item["nmID"]) for item in current]})
            current = [update]
        else:
            current = candidate
    if current:
        payloads = [item["payload"] for item in current]
        start = sum(item["cards"] for item in out)
        out.append({"update_indexes": list(range(start, start + len(current))), "cards": len(current),
                    "request_bytes": len(json.dumps(payloads, ensure_ascii=False,
                                                    separators=(",", ":")).encode()),
                    "nmIDs": [str(item["nmID"]) for item in current]})
    return out


def main() -> None:
    doc_path = BASE / "feron_01381_wb_cards_live.json"
    plan = json.loads((BASE / "feron_01381_plan.json").read_text(encoding="utf-8"))
    wb = json.loads(doc_path.read_text(encoding="utf-8"))
    if not wb.get("complete_catalog_read"):
        raise RuntimeError("A complete, fresh WB catalog read is required")
    targets = plan["target_offer_to_sku"]
    cards = wb.get("cards") or []
    if len({str(card.get("nmID")) for card in cards}) != len(cards):
        raise RuntimeError("Duplicate WB nmID in target-card snapshot")
    if any(str(card.get("vendorCode", "")) not in targets for card in cards):
        raise RuntimeError("Snapshot contains an offer outside the exact FERON target set")

    updates, already, blocked = [], [], []
    docs_with_correct = set()
    seen_pairs = set()
    for card in cards:
        offer = str(card.get("vendorCode", ""))
        nm_id = str(card.get("nmID", ""))
        pair = (offer, nm_id)
        if not offer or not nm_id or pair in seen_pairs or offer not in targets:
            raise RuntimeError(f"WB live identity error: {pair}")
        seen_pairs.add(pair)
        sizes = card.get("sizes")
        required_fields = ("brand", "title", "description", "dimensions", "sizes")
        missing = [field for field in required_fields if field not in card]
        if not sizes or missing:
            blocked.append({"offer": offer, "nmID": nm_id, "reason": "missing_full_card_fields",
                            "missing_fields": missing, "has_sizes": bool(sizes)})
            continue
        doc_state = card.get("documents") or {}
        old_items_raw = doc_state.get("items") or []
        old_items = [{key: item[key] for key in DOC_FIELDS if key in item} for item in old_items_raw]
        same_number = [item for item in old_items if norm(item.get("number", "")) == norm(NUMBER)]
        conflicts = []
        same_type = [item for item in same_number if doc_type(item.get("type")) == 1]
        if same_number and not same_type:
            conflicts.append("same_number_different_document_type")
        if same_type and any((datepart(item.get("startDate")), datepart(item.get("endDate"))) !=
                             (ISSUE, EXPIRY) for item in same_type):
            conflicts.append("matching_certificate_number_with_conflicting_dates")
        if conflicts:
            blocked.append({"offer": offer, "nmID": nm_id, "reason": conflicts,
                            "existing_documents": same_number})
            continue
        if same_type:
            docs_with_correct.add(offer)
            already.append({"offer": offer, "nmID": nm_id, "sku": targets[offer],
                            "existing": same_type,
                            "verdicts": [item.get("verdict") for item in old_items_raw
                                         if norm(item.get("number", "")) == norm(NUMBER)]})
            missing_target_doc = False
        else:
            missing_target_doc = True
        exclude = bool(doc_state.get("excludeDocuments"))
        if not missing_target_doc and not exclude:
            continue
        payload = {field: card[field] for field in FIELDS if field in card}
        if str(payload.get("nmID")) != nm_id or payload.get("vendorCode") != offer:
            raise RuntimeError(f"WB update identity field mismatch for {offer}")
        if payload.get("sizes") != sizes:
            raise RuntimeError(f"WB sizes not preserved for {offer}")
        additions = []
        if missing_target_doc:
            additions.append({"type": 1, "number": NUMBER,
                              "startDate": ISSUE + "T00:00:00Z", "endDate": EXPIRY + "T00:00:00Z",
                              "isEndless": False})
        payload["documents"] = {"items": old_items + additions, "excludeDocuments": False}
        if any(old not in payload["documents"]["items"] for old in old_items):
            raise RuntimeError(f"Existing WB document rows were not preserved for {offer}")
        updates.append({"offer": offer, "nmID": nm_id, "sku": targets[offer],
                        "additions": additions, "unexclude_documents": exclude,
                        "before": card, "payload": payload})

    grouped: dict[str, int] = {}
    for row in updates:
        grouped["metadata_addition" if row["additions"] else "unexclude_only"] = grouped.get(
            "metadata_addition" if row["additions"] else "unexclude_only", 0) + 1
    result = {
        "planned_at": now(),
        "number": NUMBER,
        "type": "certificate_of_conformity",
        "issue_date": ISSUE,
        "expire_date": EXPIRY,
        "file_sha256": FILE_SHA256,
        "registry_url": plan["registry_url"],
        "source_workbook_sha256": plan["workbook_sha256"],
        "wb_catalog_checked_at": wb["checked_at"],
        "wb_catalog_pages": wb["pages"],
        "wb_catalog_cards_read": wb["catalog_cards_read"],
        "target_offer_count": len(targets),
        "wb_offers_without_cards": wb["offers_without_wb_card"],
        "wb_multiple_card_offers": wb["offers_with_multiple_wb_cards"],
        "matched_wb_card_count": len(cards),
        "offers_with_existing_correct_document": sorted(docs_with_correct),
        "already_present_rows": already,
        "updates": updates,
        "blocked": blocked,
        "update_kinds": grouped,
    }
    result["batches"] = chunks(updates)
    result["counts"] = {
        "cards_to_update": len(updates),
        "document_additions": sum(len(row["additions"]) for row in updates),
        "cards_to_unexclude": sum(row["unexclude_documents"] for row in updates),
        "already_present_card_rows": len(already),
        "blocked_cards": len(blocked),
        "offers_with_correct_document": len(docs_with_correct),
        "offers_without_wb_card": len(wb["offers_without_wb_card"]),
        "wb_card_count": len(cards),
        "batch_count": len(result["batches"]),
        "max_batch_bytes": max((batch["request_bytes"] for batch in result["batches"]), default=0),
    }
    save("feron_01381_wb_plan.json", result)
    print(json.dumps({"counts": result["counts"], "update_kinds": grouped,
                      "multiple_card_offers": len(wb["offers_with_multiple_wb_cards"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
