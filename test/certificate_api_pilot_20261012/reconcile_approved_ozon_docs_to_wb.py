"""Project already-approved, SKU-bound Ozon EAEU docs onto exact WB cards.

The default run only makes a plan. --execute sends one update batch, then
independently exports the complete WB card catalog for readback. A run marker
blocks accidental repeated writes; uncertain writes must be reconciled first.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

from api_client import Client, now, save

BASE_DIR = Path(__file__).resolve().parent
ROOT = BASE_DIR.parents[1]
ALLOWED_DOC_CHARACTERISTIC_IDS = {15001136, 15001137, 15001138}
UPDATE_CARD_FIELDS = (
    "nmID", "vendorCode", "brand", "title", "description", "dimensions",
    "characteristics", "sizes", "kizMarked",
)
DOC_FIELDS = (
    "id", "type", "number", "productNumber", "tradeName", "applicant",
    "startDate", "endDate", "isEndless",
)
OZON_TO_WB_TYPE = {"certificate_of_conformity": 1, "declaration": 2}
TODAY = dt.datetime.now(dt.timezone.utc).date().isoformat()


def read_json(name: str) -> dict:
    return json.loads((BASE_DIR / name).read_text())


def save_json(name: str, value) -> None:
    path = BASE_DIR / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def norm_number(value: str) -> str:
    import re
    text = re.sub(r"^(?:ЕАЭС|EAEU|EAEC|EAC)\s*", "", str(value or "").strip().upper())
    text = re.sub(r"^(?:N|№)\s*", "", text)
    table = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "H",
                           "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                           "У": "Y", "Х": "X", "Ё": "E", "Э": "E", "Д": "D",
                           "П": "P"})
    return "".join(ch for ch in text.translate(table) if ch.isalnum())


def doc_key(doc: dict) -> tuple[int, str]:
    return int(doc.get("type", 0)), norm_number(doc.get("number", ""))


def exact_approved_ozon_docs(products_doc: dict, ozon_doc: dict) -> tuple[dict, dict]:
    products = products_doc.get("products") or []
    by_sku = {}
    duplicate_skus = set()
    for p in products:
        sku = str(p.get("sku") or "")
        if not sku:
            continue
        if sku in by_sku:
            duplicate_skus.add(sku)
        by_sku[sku] = p
    if duplicate_skus:
        raise RuntimeError(f"Duplicate current Ozon SKUs; refusing to infer offer mapping: {len(duplicate_skus)}")

    docs_by_offer: dict[str, dict[tuple[int, str], dict]] = {}
    excluded = {"unknown_type": 0, "non_eaeu": 0, "not_current_or_approved": 0,
                "invalid_dates_or_number": 0, "stale_sku_or_product_id": 0}
    for cert in ozon_doc.get("certificates") or []:
        wb_type = OZON_TO_WB_TYPE.get(cert.get("type_code"))
        if wb_type is None:
            excluded["unknown_type"] += 1
            continue
        if cert.get("accordance_type_code") != "EAEU":
            excluded["non_eaeu"] += 1
            continue
        issue = str(cert.get("issue_date") or "")
        expiry = str(cert.get("expire_date") or "")
        number = str(cert.get("certificate_number") or "").strip()
        if (not number or len(issue) < 10 or len(expiry) < 10 or
                expiry[:10] < TODAY or issue[:10] > TODAY):
            excluded["invalid_dates_or_number"] += 1
            continue
        if cert.get("status_code") != "approved":
            excluded["not_current_or_approved"] += 1
            continue
        for binding in cert.get("live_bindings") or []:
            if binding.get("product_status_code") != "approved":
                excluded["not_current_or_approved"] += 1
                continue
            sku = str(binding.get("sku") or "")
            product = by_sku.get(sku)
            if (not product or str(product.get("product_id")) != str(binding.get("product_id"))):
                excluded["stale_sku_or_product_id"] += 1
                continue
            offer = str(product.get("offer_id") or "")
            if not offer:
                excluded["stale_sku_or_product_id"] += 1
                continue
            entry = {
                "type": wb_type, "number": number, "startDate": issue,
                "endDate": expiry, "isEndless": False,
            }
            key = doc_key(entry)
            docs_by_offer.setdefault(offer, {})
            prior = docs_by_offer[offer].get(key)
            if prior and (prior["startDate"][:10], prior["endDate"][:10]) != (issue[:10], expiry[:10]):
                raise RuntimeError(f"Conflicting Ozon dates for exact offer {offer}, {number}")
            proof = {
                "certificate_id": cert.get("certificate_id"),
                "ozon_status": cert.get("status_code"),
                "binding_status": binding.get("product_status_code"),
                "product_id": product.get("product_id"), "sku": product.get("sku"),
                "certificate_type": cert.get("type_code"),
                "accordance_type": cert.get("accordance_type_code"),
                "number": number, "issue_date": issue, "expire_date": expiry,
            }
            if prior:
                prior.setdefault("proofs", []).append(proof)
            else:
                docs_by_offer[offer][key] = {**entry, "proofs": [proof]}
    return docs_by_offer, excluded


def copy_documents(card: dict) -> list[dict]:
    return [{k: item[k] for k in DOC_FIELDS if k in item}
            for item in ((card.get("documents") or {}).get("items") or [])]


def plan_updates() -> dict:
    products_doc = read_json("ozon_products_live.json")
    ozon_doc = read_json("ozon_live.json")
    wb_doc = read_json("wb_live.json")
    if not (products_doc.get("complete") and ozon_doc.get("complete") and wb_doc.get("complete")):
        raise RuntimeError("Complete live Ozon products, Ozon certificate/bindings, and WB cards snapshots required")

    ozon_checked = dt.datetime.fromisoformat(products_doc["checked_at"].replace("Z", "+00:00"))
    wb_checked = dt.datetime.fromisoformat(wb_doc["checked_at"].replace("Z", "+00:00"))
    if (dt.datetime.now(dt.timezone.utc) - ozon_checked).total_seconds() > 7200:
        raise RuntimeError("Ozon product snapshot is older than two hours; refresh before planning")
    if (dt.datetime.now(dt.timezone.utc) - wb_checked).total_seconds() > 7200:
        raise RuntimeError("WB catalog snapshot is older than two hours; refresh before planning")

    wb_by_offer = {}
    duplicate_offers = set()
    for card in wb_doc.get("cards") or []:
        offer = card.get("vendorCode")
        if not offer:
            continue
        if offer in wb_by_offer:
            duplicate_offers.add(offer)
        wb_by_offer[offer] = card
    if duplicate_offers:
        raise RuntimeError(f"Duplicate exact WB vendorCode values in snapshot: {len(duplicate_offers)}")

    docs_by_offer, excluded = exact_approved_ozon_docs(products_doc, ozon_doc)
    plan_rows = []
    missing_wb_card = []
    blocked = []
    counts = {
        "current_ozon_products": len(products_doc.get("products") or []),
        "current_wb_cards": len(wb_doc.get("cards") or []),
        "ozon_offers_with_approved_current_eaeu_docs": len(docs_by_offer),
        "ozon_approved_doc_edges": sum(len(x) for x in docs_by_offer.values()),
        "exact_wb_cards_missing_docs": 0, "doc_edges_to_add": 0,
        "cards_with_exclude_documents_set": 0, "same_doc_already_attached": 0,
    }

    products_by_offer = {str(p.get("offer_id") or ""): p for p in products_doc.get("products") or []}
    for offer, desired_map in docs_by_offer.items():
        product = products_by_offer.get(offer)
        card = wb_by_offer.get(offer)
        if not card:
            missing_wb_card.append({"offer_id": offer, "sku": (product or {}).get("sku"),
                                   "product_id": (product or {}).get("product_id"),
                                   "approved_docs": list(desired_map.values())})
            continue
        existing_items = copy_documents(card)
        by_number = {}
        for item in existing_items:
            n = norm_number(item.get("number", ""))
            if n:
                by_number.setdefault(n, []).append(item)
        additions = []
        conflicts = []
        for key, desired in desired_map.items():
            number_key = key[1]
            existing = by_number.get(number_key, [])
            if existing:
                # Never duplicate an item already present, even if WB is still reviewing it.
                matched_type = [x for x in existing if int(x.get("type", 0)) == key[0]]
                if not matched_type:
                    conflicts.append({"number": desired["number"], "reason": "same_number_different_wb_type",
                                      "existing": existing})
                    continue
                if any((str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10]) !=
                       (desired["startDate"][:10], desired["endDate"][:10]) for x in matched_type):
                    conflicts.append({"number": desired["number"], "reason": "date_conflict",
                                      "existing": matched_type, "desired": {k: desired[k] for k in ("startDate", "endDate")}})
                    continue
                counts["same_doc_already_attached"] += 1
                continue
            additions.append({k: desired[k] for k in ("type", "number", "startDate", "endDate", "isEndless")})
        if conflicts:
            blocked.append({"offer_id": offer, "nmID": card.get("nmID"), "conflicts": conflicts})
            continue
        if not additions:
            continue
        docs_obj = card.get("documents") or {}
        set_exclude_false = docs_obj.get("excludeDocuments") is True
        merged_docs = existing_items + additions
        payload = {key: card[key] for key in UPDATE_CARD_FIELDS if key in card}
        payload["documents"] = {"items": merged_docs, "excludeDocuments": False}
        if set_exclude_false:
            counts["cards_with_exclude_documents_set"] += 1
        plan_rows.append({
            "offer_id": offer, "product_id": (product or {}).get("product_id"),
            "sku": (product or {}).get("sku"), "nmID": card.get("nmID"),
            "additions": additions, "set_exclude_documents_false": set_exclude_false,
            "ozon_proof": [proof for desired in desired_map.values() for proof in desired["proofs"]
                           if doc_key(desired) in {doc_key(x) for x in additions}],
            "before": card, "payload": payload,
        })

    counts["exact_wb_cards_missing_docs"] = len(plan_rows)
    counts["doc_edges_to_add"] = sum(len(x["additions"]) for x in plan_rows)
    return {
        "planned_at": now(), "snapshot_checked_at": {
            "ozon_products": products_doc.get("checked_at"), "ozon_certificates": ozon_doc.get("checked_at"),
            "wb_cards": wb_doc.get("checked_at"),
        },
        "counts": counts, "excluded_ozon_record_or_binding_counts": excluded,
        "missing_exact_wb_cards": missing_wb_card, "blocked_conflicts": blocked,
        "updates": plan_rows,
    }


def comparable_card(card: dict) -> dict:
    result = {k: v for k, v in card.items() if k not in {"documents", "updatedAt", "characteristics"}}
    chars = []
    for item in card.get("characteristics") or []:
        if item.get("id") not in ALLOWED_DOC_CHARACTERISTIC_IDS:
            chars.append(item)
    result["characteristics"] = sorted(chars, key=lambda x: x.get("id", 0))
    return result


def chunks_by_size(rows: list[dict], max_bytes: int = 9_000_000, max_cards: int = 3000) -> list[list[dict]]:
    chunks, current = [], []
    for row in rows:
        candidate = current + [row["payload"]]
        size = len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode())
        if current and (size > max_bytes or len(candidate) > max_cards):
            chunks.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        chunks.append(current)
    for chunk in chunks:
        size = len(json.dumps([x["payload"] for x in chunk], ensure_ascii=False,
                              separators=(",", ":")).encode())
        if size > 10_000_000 or len(chunk) > 3000:
            raise RuntimeError("WB update chunk exceeds official request size/card limits")
    return chunks


def execute(plan: dict) -> dict:
    run_path = BASE_DIR / "wb_ozon_reconciliation_execution.json"
    if run_path.exists():
        raise RuntimeError("Execution marker already exists; reconcile its live status before any further write")
    chunks = chunks_by_size(plan["updates"])
    run = {"started_at": now(), "state": "prepared", "planned_cards": len(plan["updates"]),
           "planned_documents": plan["counts"]["doc_edges_to_add"], "chunks": []}
    save_json(run_path.name, run)
    client = Client()
    last_mutation = None
    for i, chunk in enumerate(chunks, 1):
        if last_mutation is not None:
            wait = 6.2 - (time.monotonic() - last_mutation)
            if wait > 0:
                time.sleep(wait)
        payload = [row["payload"] for row in chunk]
        chunk_entry = {"index": i, "cards": len(chunk),
                       "documents": sum(len(row["additions"]) for row in chunk),
                       "request_bytes": len(json.dumps(payload, ensure_ascii=False,
                                                       separators=(",", ":")).encode()),
                       "state": "prepared"}
        run["chunks"].append(chunk_entry)
        run["state"] = "submitting"
        save_json(run_path.name, run)
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        last_mutation = time.monotonic()
        chunk_entry["response"] = response
        chunk_entry["state"] = "accepted" if response.get("error") is False else "response_error"
        save_json(run_path.name, run)
        if response.get("error") is not False:
            run["state"] = "response_error_reconcile_before_retry"
            save_json(run_path.name, run)
            raise RuntimeError("WB update response not accepted; live reconciliation required before retry")

    run["state"] = "updates_accepted_readback_pending"
    save_json(run_path.name, run)
    return run


def full_readback(plan: dict, run: dict) -> dict:
    # WB documents a complete list export as the independent server-side readback.
    proc = subprocess.run([sys.executable, str(BASE_DIR / "audit_wb_live.py")],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        run["state"] = "updates_accepted_readback_failed"
        run["readback_error"] = (proc.stderr or proc.stdout)[-4000:]
        save_json("wb_ozon_reconciliation_execution.json", run)
        raise RuntimeError("WB update accepted but full readback failed; do not resubmit")
    current = read_json("wb_live.json")
    if not current.get("complete"):
        raise RuntimeError("WB full readback snapshot incomplete; do not resubmit")
    save_json("wb_live_reconciliation_readback.json", current)
    after_by_offer = {card.get("vendorCode"): card for card in current.get("cards") or []}
    results = {}
    for row in plan["updates"]:
        after = after_by_offer.get(row["offer_id"])
        before = row["before"]
        wanted = {doc_key(doc): doc for doc in row["additions"]}
        found = {}
        if after:
            for doc in ((after.get("documents") or {}).get("items") or []):
                expected = wanted.get(doc_key(doc))
                if (expected and str(doc.get("startDate") or "")[:10] == expected["startDate"][:10]
                        and str(doc.get("endDate") or "")[:10] == expected["endDate"][:10]):
                    found[doc_key(doc)] = doc
        expected_visible = len(found) == len(wanted)
        fields_preserved = bool(after) and comparable_card(before) == comparable_card(after)
        expected_old = {doc_key(doc): doc for doc in copy_documents(before)}
        actual_docs = {doc_key(doc): doc for doc in copy_documents(after or {})}
        old_docs_preserved = all(
            key in actual_docs
            and str(actual_docs[key].get("startDate") or "")[:10] == str(doc.get("startDate") or "")[:10]
            and str(actual_docs[key].get("endDate") or "")[:10] == str(doc.get("endDate") or "")[:10]
            for key, doc in expected_old.items()
        )
        results[row["offer_id"]] = {
            "nmID": row["nmID"], "expected_documents": len(wanted),
            "visible_documents": len(found), "documents_visible": expected_visible,
            "unrelated_fields_preserved": fields_preserved,
            "preexisting_documents_preserved": old_docs_preserved,
            "exclude_documents_before": ((before.get("documents") or {}).get("excludeDocuments")),
            "exclude_documents_after": (((after or {}).get("documents") or {}).get("excludeDocuments")),
            "documents": list(found.values()),
            "verdicts": {doc.get("number"): doc.get("verdict") for doc in found.values()},
            "outcome": ("visible_fields_preserved_waiting_or_reviewing" if expected_visible and fields_preserved
                        else "readback_needs_review"),
        }
    summary = {
        "checked_at": current.get("checked_at"), "complete": current.get("complete"),
        "cards_checked": len(results),
        "all_documents_visible": all(x["documents_visible"] for x in results.values()),
        "all_unrelated_fields_preserved": all(x["unrelated_fields_preserved"] for x in results.values()),
        "all_preexisting_documents_preserved": all(x["preexisting_documents_preserved"] for x in results.values()),
        "documents_visible_count": sum(x["documents_visible"] for x in results.values()),
        "fields_preserved_count": sum(x["unrelated_fields_preserved"] for x in results.values()),
        "pending_or_returned_verdicts": sum(1 for x in results.values() for v in x["verdicts"].values()
                                                if not (isinstance(v, dict) and v.get("verified") is True
                                                        and v.get("status") == 1 and v.get("reason") == "valid")),
        "results": results,
    }
    save_json("wb_ozon_reconciliation_readback.json", summary)
    run["readback"] = {k: v for k, v in summary.items() if k != "results"}
    run["state"] = ("readback_complete" if summary["all_documents_visible"]
                     and summary["all_unrelated_fields_preserved"]
                     and summary["all_preexisting_documents_preserved"] else "readback_needs_review")
    run["finished_at"] = now()
    save_json("wb_ozon_reconciliation_execution.json", run)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Submit the planned WB card updates")
    args = parser.parse_args()
    plan = plan_updates()
    save_json("wb_ozon_reconciliation_plan.json", plan)
    print(json.dumps({"counts": plan["counts"], "excluded": plan["excluded_ozon_record_or_binding_counts"],
                      "missing_wb_cards": len(plan["missing_exact_wb_cards"]),
                      "blocked_conflicts": len(plan["blocked_conflicts"]),
                      "bytes": sum(len(json.dumps(x["payload"], ensure_ascii=False,
                                                    separators=(",", ":")).encode()) for x in plan["updates"]),
                      "execute": args.execute}, ensure_ascii=False), flush=True)
    if not args.execute:
        return
    if not plan["updates"]:
        print("No WB changes required")
        return
    run = execute(plan)
    readback = full_readback(plan, run)
    print(json.dumps({k: v for k, v in readback.items() if k != "results"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
