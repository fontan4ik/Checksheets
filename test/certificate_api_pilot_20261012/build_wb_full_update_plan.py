"""Build a safe WB update from complete, fresh card objects after the failed batch."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from group4_wb import norm

BASE = Path(__file__).resolve().parent
UPDATE_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
                 "characteristics", "sizes", "kizMarked")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def key(doc: dict) -> tuple[int, str]:
    raw_type = doc.get("type", 0)
    if isinstance(raw_type, str) and not raw_type.isdigit():
        raw_type = {"certificate_of_conformity": 1, "declaration": 2}.get(raw_type, 0)
    return int(raw_type), norm(doc.get("number", ""))


def datepart(value) -> str:
    return str(value or "")[:10]


def main() -> None:
    target_audit = json.loads((BASE / "wb_target_full_before.json").read_text())
    source_plan = json.loads((BASE / "wb_ozon_reconciliation_plan.json").read_text())
    error_audit = json.loads((BASE / "wb_cards_error_list_first_page.json").read_text())
    if not target_audit.get("complete") or not target_audit.get("cards_by_offer"):
        raise RuntimeError("Complete fresh WB full-card target export required")
    if target_audit.get("targets_found") != len(source_plan.get("updates") or []):
        raise RuntimeError("WB target full-card export does not cover all source candidates")

    error_items = ((error_audit.get("response") or {}).get("data") or {}).get("items") or []
    failed = [x for x in error_items if x.get("updatedAt") == "2026-10-12T03:45:49Z"
              and x.get("batchUUID") == "e8e71803-1bf2-4f03-8572-b06f67b28718"]
    if len(failed) != 1 or len(failed[0].get("errors") or {}) != len(source_plan.get("updates") or []):
        raise RuntimeError("Previous failed WB batch not fully accounted for; do not continue")
    failed_reasons = {message for messages in failed[0]["errors"].values() for message in messages}
    if failed_reasons != {"Карточка товара должна иметь минимум 1 размер"}:
        raise RuntimeError(f"Unexpected errors in previous WB batch: {failed_reasons}")

    updates, already_present, blocked = [], [], []
    cards_by_offer = target_audit["cards_by_offer"]
    for source in source_plan["updates"]:
        offer = source["offer_id"]
        card = cards_by_offer.get(offer)
        if not card or str(card.get("nmID")) != str(source["nmID"]) or card.get("vendorCode") != offer:
            raise RuntimeError(f"Fresh exact WB full card identity mismatch for {offer}")
        if not card.get("sizes"):
            raise RuntimeError(f"Fresh full WB card has no sizes: {offer}")
        # WB omits optional empty characteristics/kizMarked on some otherwise complete cards.
        # Preserve every field returned by the full-card endpoint; require the core card fields
        # and non-empty sizes that were missing from the failed partial-list payload.
        required = ("brand", "title", "description", "dimensions", "sizes")
        missing_fields = [f for f in required if f not in card]
        if missing_fields:
            raise RuntimeError(f"Full WB card omitted updateable fields for {offer}: {missing_fields}")

        existing_docs = [
            {field: item[field] for field in DOC_FIELDS if field in item}
            for item in ((card.get("documents") or {}).get("items") or [])
        ]
        by_number = {}
        for item in existing_docs:
            by_number.setdefault(norm(item.get("number", "")), []).append(item)
        additions, conflicts = [], []
        for desired in source["additions"]:
            same_number = by_number.get(norm(desired.get("number", "")), [])
            if same_number:
                same_type = [x for x in same_number if int(x.get("type", 0)) == int(desired["type"])]
                if not same_type:
                    conflicts.append({"number": desired["number"], "reason": "same_number_different_type",
                                      "existing": same_number})
                elif any((datepart(x.get("startDate")), datepart(x.get("endDate"))) !=
                         (datepart(desired.get("startDate")), datepart(desired.get("endDate")))
                         for x in same_type):
                    conflicts.append({"number": desired["number"], "reason": "live_date_conflict",
                                      "existing": same_type})
                else:
                    already_present.append({"offer_id": offer, "nmID": card["nmID"],
                                            "number": desired["number"], "documents": same_type})
                continue
            additions.append({field: desired[field] for field in ("type", "number", "startDate", "endDate", "isEndless")})
        if conflicts:
            blocked.append({"offer_id": offer, "nmID": card["nmID"], "conflicts": conflicts})
            continue
        if not additions:
            continue

        payload = {field: card[field] for field in UPDATE_FIELDS if field in card}
        if "kizMarked" not in payload and "kizMarked" in card:
            raise RuntimeError(f"Could not preserve kizMarked for {offer}")
        payload["documents"] = {
            "items": existing_docs + additions,
            "excludeDocuments": False,
        }
        proofs = []
        add_keys = {key(x) for x in additions}
        for proof in source.get("ozon_proof", []):
            if key({"type": proof["certificate_type"], "number": proof["number"]}) in add_keys:
                proofs.append(proof)
        if not proofs:
            raise RuntimeError(f"No exact approved Ozon proof for WB update {offer}")
        if any(p.get("ozon_status") != "approved" or p.get("binding_status") != "approved"
               or p.get("accordance_type") != "EAEU"
               or str(p.get("sku")) != str(source["sku"])
               or str(p.get("product_id")) != str(source["product_id"]) for p in proofs):
            raise RuntimeError(f"Ozon proof does not match exact product/SKU for {offer}")
        updates.append({
            "offer_id": offer, "nmID": card["nmID"], "sku": source["sku"],
            "product_id": source["product_id"], "additions": additions,
            "set_exclude_documents_false": (card.get("documents") or {}).get("excludeDocuments") is True,
            "ozon_proof": proofs, "before": card, "payload": payload,
        })

    total_bytes = len(json.dumps([x["payload"] for x in updates], ensure_ascii=False,
                                 separators=(",", ":")).encode())
    if len(updates) > 3000 or total_bytes > 10_000_000:
        raise RuntimeError(f"WB update over API limits: cards={len(updates)}, bytes={total_bytes}")
    if blocked:
        raise RuntimeError(f"Unexpected live-card conflicts after original preflight: {len(blocked)}")

    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_live_audit": {"checked_at": target_audit.get("checked_at"),
                              "catalog_cards": target_audit.get("full_catalog_cards"),
                              "targets_found": target_audit.get("targets_found")},
        "previous_failed_batch": {"batchUUID": failed[0].get("batchUUID"),
                                  "updatedAt": failed[0].get("updatedAt"),
                                  "vendor_count": len(failed[0].get("vendorCodes") or []),
                                  "error_count": len(failed[0].get("errors") or {}),
                                  "reason_counts": {reason: sum(reason in messages for messages in failed[0]["errors"].values())
                                                    for reason in failed_reasons}},
        "counts": {"source_candidate_cards": len(source_plan["updates"]),
                   "already_visible_from_safe_pilots": len(already_present),
                   "cards_to_update": len(updates),
                   "documents_to_add": sum(len(x["additions"]) for x in updates),
                   "cards_to_unexclude_documents": sum(x["set_exclude_documents_false"] for x in updates),
                   "payload_bytes": total_bytes},
        "already_present": already_present, "blocked_conflicts": blocked, "updates": updates,
    }
    out = BASE / "wb_fullcard_reconciliation_plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(json.dumps({"counts": plan["counts"], "previous_errors": plan["previous_failed_batch"]["reason_counts"],
                      "plan": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
