"""Build a full-card, no-duplicate WB patch from the fresh approved-Ozon plan."""
from __future__ import annotations

import datetime as dt
import argparse
import hashlib
import json
from pathlib import Path

from group4_wb import norm

BASE = Path(__file__).resolve().parent
PLAN_IN = BASE / "wb_ozon_reconciliation_plan.json"
BEFORE = BASE / "wb_target_full_before.json"
PLAN_OUT = BASE / "wb_ozon_reconciliation_fullcard_plan_20261012.json"
UPDATE_FIELDS = ("nmID", "vendorCode", "brand", "title", "description", "dimensions",
                 "characteristics", "sizes", "kizMarked")
DOC_FIELDS = ("id", "type", "number", "productNumber", "tradeName", "applicant",
              "startDate", "endDate", "isEndless")


def datepart(value) -> str:
    return str(value or "")[:10]


def signature(doc: dict) -> tuple:
    return (int(doc.get("type", 0)), norm(doc.get("number", "")), datepart(doc.get("startDate")),
            datepart(doc.get("endDate")), bool(doc.get("isEndless", False)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-plan', default=PLAN_IN.name)
    parser.add_argument('--before-snapshot', default=BEFORE.name)
    parser.add_argument('--plan-out', default=PLAN_OUT.name)
    args = parser.parse_args()
    source_path = BASE / args.source_plan
    before_path = BASE / args.before_snapshot
    plan_out = BASE / args.plan_out
    source = json.loads(source_path.read_text())
    full = json.loads(before_path.read_text())
    products = json.loads((BASE / "ozon_products_live.json").read_text())
    if not source.get("updates") or not full.get("complete") or not products.get("complete"):
        raise RuntimeError("Fresh approved-Ozon plan and complete current catalogs are required")
    if int(full.get("targets_found", -1)) != len(source["updates"]):
        raise RuntimeError("Full-card WB readback does not exactly cover the current target plan")
    for snapshot in (source.get("snapshot_checked_at") or {}).values():
        checked = dt.datetime.fromisoformat(str(snapshot).replace("Z", "+00:00"))
        if (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 7200:
            raise RuntimeError("A marketplace preflight snapshot is older than two hours")

    cards = full.get("cards_by_offer") or {}
    product_by_offer = {str(x["offer_id"]): x for x in products.get("products") or []}
    if len(cards) != len(source["updates"]):
        raise RuntimeError("Duplicate or missing WB full-card target in readback")

    updates, already_present, blocked = [], [], []
    for planned in source["updates"]:
        offer = str(planned["offer_id"])
        card = cards.get(offer)
        product = product_by_offer.get(offer)
        if (not card or not product or str(card.get("nmID")) != str(planned["nmID"])
                or card.get("vendorCode") != offer
                or str(product.get("product_id")) != str(planned["product_id"])
                or str(product.get("sku")) != str(planned["sku"])):
            raise RuntimeError(f"Live Ozon/WB identity changed for {offer}")
        if not all(field in card for field in ("brand", "title", "description", "dimensions", "sizes")):
            raise RuntimeError(f"Incomplete live WB full-card fields for {offer}")
        if not card.get("sizes"):
            raise RuntimeError(f"WB full card has no size row; refusing full-card update: {offer}")

        old_items = (card.get("documents") or {}).get("items") or []
        additions, conflicts = [], []
        for desired in planned.get("additions") or []:
            wanted_sig = signature(desired)
            same_number = [item for item in old_items if norm(item.get("number", "")) == norm(desired["number"])]
            if same_number:
                exact = [item for item in same_number if signature(item) == wanted_sig]
                if exact:
                    already_present.append({"offer_id": offer, "number": desired["number"]})
                    continue
                conflicts.append({"number": desired["number"], "existing": same_number,
                                  "desired": desired, "reason": "same_number_type_or_date_conflict"})
                continue
            additions.append({field: desired[field] for field in
                              ("type", "number", "startDate", "endDate", "isEndless")})
        if conflicts:
            blocked.append({"offer_id": offer, "nmID": card["nmID"], "conflicts": conflicts})
            continue
        if not additions:
            continue
        proof_by_key = {(int({"certificate_of_conformity": 1, "declaration": 2}.get(
            x.get("certificate_type"), 0)), norm(x.get("number", "")), datepart(x.get("issue_date")),
            datepart(x.get("expire_date"))) for x in planned.get("ozon_proof") or []
            if x.get("ozon_status") == "approved" and x.get("binding_status") == "approved"
            and x.get("accordance_type") == "EAEU"
            and str(x.get("sku")) == str(planned["sku"])
            and str(x.get("product_id")) == str(planned["product_id"])}
        for item in additions:
            expected = (int(item["type"]), norm(item["number"]), datepart(item["startDate"]), datepart(item["endDate"]))
            if expected not in proof_by_key:
                raise RuntimeError(f"Exact approved Ozon proof missing for {offer}: {item['number']}")

        payload = {field: card[field] for field in UPDATE_FIELDS if field in card}
        payload["documents"] = {
            "items": [{field: item[field] for field in DOC_FIELDS if field in item} for item in old_items] + additions,
            "excludeDocuments": False,
        }
        if payload.get("sizes") != card.get("sizes"):
            raise RuntimeError(f"WB size rows changed while constructing payload for {offer}")
        updates.append({"offer_id": offer, "nmID": card["nmID"], "sku": planned["sku"],
                        "product_id": planned["product_id"], "additions": additions,
                        "before": card, "payload": payload,
                        "set_exclude_documents_false": (card.get("documents") or {}).get("excludeDocuments") is not False,
                        "ozon_proof": planned.get("ozon_proof") or []})

    payload_bytes = len(json.dumps([x["payload"] for x in updates], ensure_ascii=False,
                                   separators=(",", ":")).encode())
    if blocked:
        raise RuntimeError(f"Unexpected WB full-card conflicts: {len(blocked)}")
    if not updates:
        raise RuntimeError("No safe WB updates remain after fresh full-card comparison")
    if len(updates) > 3000 or payload_bytes > 10_000_000:
        raise RuntimeError("WB update exceeds the documented card or request-size limit")

    state = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_plan_checked_at": source.get("planned_at"),
        "ozon_products_checked_at": products.get("checked_at"),
        "wb_full_cards_checked_at": full.get("checked_at"),
        "counts": {"source_candidates": len(source["updates"]), "cards_to_update": len(updates),
                   "documents_to_add": sum(len(x["additions"]) for x in updates),
                   "already_present_during_full_read": len(already_present),
                   "cards_to_enable_documents": sum(x["set_exclude_documents_false"] for x in updates),
                   "request_bytes": payload_bytes,
                   "request_sha256": hashlib.sha256(json.dumps([x["payload"] for x in updates],
                       ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()},
        "blocked_conflicts": blocked,
        "already_present": already_present,
        "updates": updates,
    }
    tmp = plan_out.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(plan_out)
    print(json.dumps({"counts": state["counts"], "plan": str(plan_out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
