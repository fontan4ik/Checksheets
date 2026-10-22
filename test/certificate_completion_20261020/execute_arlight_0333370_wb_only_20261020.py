"""Safely bind verified Arlight document 90090 to exact Wildberries cards.

Ozon rejects the official number format, so this script does not mutate Ozon.
It reads a complete WB catalog before updates, writes exact-scope cards in
batches, reads the complete catalog again, and never deletes the local PDF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, digest, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

MANIFEST = HERE / "arlight_0333370_exact_scope_manifest_20261020.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/B93165BC4283E449AF1E139B53863098.pdf"
STATE = HERE / "arlight_0333370_wb_execution_state_20261020.json"
DRY = HERE / "arlight_0333370_wb_dry_run_20261020.json"
JOURNAL = HERE / "arlight_0333370_wb_mutation_journal_20261020.jsonl"
NUMBER = "РОСС RU.32001.04ИБФ1.ОСП32.90090"
ISSUE = "2025-12-01"
EXPIRY = "2028-11-30"
ALLOWED = {"9405110033", "9405110039", "9405420039", "9405420012", "9405420022", "9405420032"}


def save(value: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(STATE)


def log(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        name = str(item.get("name") or "").casefold().replace("ё", "е")
        if "тнвэд" in name or "тнвед" in name:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if x})


def card_signature(card: dict) -> str:
    return json.dumps(card, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def wanted_doc() -> dict:
    return {"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
            "endDate": wb_datetime(EXPIRY), "isEndless": False}


def read_catalog(client: Client, phase: str) -> list[dict]:
    cards = []
    cursor = {"limit": 100}
    seen_cursors = set()
    page = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor, "filter": {"withPhoto": -1}}})
        data = body.get("data", body)
        batch = data.get("cards") or data.get("items") or []
        returned = data.get("cursor") or body.get("cursor") or {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError(f"Invalid WB catalog page in {phase}")
        page += 1
        cards.extend(batch)
        if page % 40 == 0:
            print(f"{phase}: {page} pages, {len(cards)} rows", flush=True)
        if len(batch) < 100:
            break
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen_cursors:
            raise RuntimeError(f"WB {phase} cursor missing or repeated")
        seen_cursors.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
        time.sleep(0.65)
    return cards


def unique_target_cards(cards: list[dict], targets: list[dict]) -> tuple[dict, dict]:
    wanted_offers = {str(x["offer_id"]) for x in targets}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        offer = str(card.get("vendorCode") or "")
        if offer in wanted_offers:
            grouped[offer].append(card)
    selected = {}
    problems = {}
    for target in targets:
        offer = str(target["offer_id"])
        rows = grouped.get(offer, [])
        exact = [r for r in rows if str(r.get("nmID")) == str(target["wb_nmID"])]
        if len(exact) == 1:
            selected[offer] = exact[0]
        elif len(exact) > 1 and len({card_signature(r) for r in exact}) == 1:
            selected[offer] = exact[0]
        else:
            problems[offer] = "missing_or_ambiguous_card"
    return selected, problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute and (STATE.exists() or JOURNAL.exists()):
        raise RuntimeError("A prior WB execution journal exists; reconcile before retrying")
    manifest = json.loads(MANIFEST.read_text())
    targets = manifest.get("targets") or []
    source = manifest.get("source_document") or {}
    if source.get("official_number") != NUMBER or len(targets) != 591:
        raise RuntimeError("Manifest is not the reviewed 591-card scope")
    if not SOURCE.is_file() or digest(SOURCE) != source.get("sha256"):
        raise RuntimeError("Official PDF hash does not match the reviewed manifest")

    client = Client()
    plan = {"checked_at": now(), "execute": args.execute, "platform": "wildberries",
            "number": NUMBER, "wb_type": 1, "issue_date": ISSUE, "expire_date": EXPIRY,
            "manifest_target_count": len(targets), "source_sha256": digest(SOURCE),
            "ozon_blocker": "official number rejected by Ozon format validator; exact-number read returned 404",
            "local_files_deleted": False, "wb_batches": [], "skips": [], "confirmed": []}
    if not args.execute:
        cards = read_catalog(client, "dry-run WB snapshot")
        selected, problems = unique_target_cards(cards, targets)
        plan.update({"phase": "dry_run_only", "snapshot_rows": len(cards),
                     "selected_target_cards": len(selected), "target_card_problems": problems})
        tmp = DRY.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
        tmp.replace(DRY)
        print(json.dumps({k: plan[k] for k in ("phase", "manifest_target_count", "snapshot_rows", "selected_target_cards", "target_card_problems", "local_files_deleted")}, ensure_ascii=False, indent=2))
        return

    before_rows = read_catalog(client, "WB preflight snapshot")
    before, identity_problems = unique_target_cards(before_rows, targets)
    candidates = []
    already = []
    skips = Counter()
    wanted = wanted_doc()
    for target in targets:
        offer = str(target["offer_id"])
        card = before.get(offer)
        if card is None:
            skips[identity_problems.get(offer, "missing_card")] += 1
            plan["skips"].append({"offer_id": offer, "reason": identity_problems.get(offer, "missing_card")})
            continue
        codes = card_tnved(card)
        if str(card.get("nmID")) != str(target["wb_nmID"]):
            skips["nmID_changed"] += 1
            plan["skips"].append({"offer_id": offer, "reason": "nmID_changed"})
            continue
        if card.get("brand") != "Arlight" or not codes or not set(codes) <= ALLOWED:
            skips["brand_or_tnved_changed"] += 1
            plan["skips"].append({"offer_id": offer, "reason": "brand_or_tnved_changed", "tnved": codes})
            continue
        same = [d for d in copy_documents(card) if norm_number(d.get("number")) == norm_number(NUMBER)]
        if same:
            if all(doc_key(d) == doc_key(wanted) and str(d.get("startDate", ""))[:10] == ISSUE
                   and str(d.get("endDate", ""))[:10] == EXPIRY for d in same):
                already.append(target)
                continue
            skips["existing_type_or_date_conflict"] += 1
            plan["skips"].append({"offer_id": offer, "reason": "existing_type_or_date_conflict"})
            continue
        try:
            payload = runner.merge_wb(card, [wanted])
        except Exception:
            skips["merge_conflict"] += 1
            plan["skips"].append({"offer_id": offer, "reason": "merge_conflict"})
            continue
        if payload is None:
            already.append(target)
        else:
            candidates.append({"target": target, "before": card, "payload": payload,
                               "key": "wb:" + str(card["nmID"]) + ":" + str(doc_key(wanted))})

    plan.update({"phase": "wb_preflight_complete", "preflight_snapshot_rows": len(before_rows),
                 "preflight_unique_targets": len(before), "preflight_counts": {
                     "prepared": len(candidates), "already_exact": len(already), "skipped": dict(skips)},
                 "target_card_problems": identity_problems, "updated_at": now()})
    save(plan)

    for offset in range(0, len(candidates), 100):
        batch = candidates[offset:offset + 100]
        marker = hashlib.sha256(json.dumps([x["payload"] for x in batch], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        for item in batch:
            log({"key": item["key"], "phase": "prepared", "at": now(),
                 "endpoint": "/content/v2/cards/update", "batch_marker": marker})
        plan.update({"phase": "wb_batch_sent", "current_batch": offset // 100 + 1,
                     "sent_cards": len(batch), "updated_at": now()})
        save(plan)
        try:
            response = client.call("wb", "/content/v2/cards/update", [x["payload"] for x in batch], mutation=True)
        except Exception as exc:
            plan.update({"phase": "wb_batch_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
            save(plan)
            raise RuntimeError("WB update outcome is uncertain; do not retry before live reconciliation") from None
        if response.get("error") is not False:
            plan.update({"phase": "wb_batch_rejected", "response": response, "updated_at": now()})
            save(plan)
            raise RuntimeError("WB rejected the batch; reconcile live state before retrying")
        plan["wb_batches"].append({"batch": offset // 100 + 1, "sent_cards": len(batch), "accepted": True,
                                   "marker": marker, "response": response})
        plan.update({"phase": "wb_batch_accepted", "updated_at": now()})
        save(plan)
        print(f"WB batch {offset // 100 + 1}: accepted {len(batch)} cards", flush=True)

    after_rows = read_catalog(client, "WB readback snapshot")
    after, readback_problems = unique_target_cards(after_rows, targets)
    confirmed = []
    readback_counts = Counter()
    for target in targets:
        offer = str(target["offer_id"])
        card = after.get(offer)
        before_card = before.get(offer)
        if card is None or before_card is None or str(card.get("nmID")) != str(target["wb_nmID"]):
            readback_counts["missing_or_ambiguous"] += 1
            continue
        visible = any(doc_key(d) == doc_key(wanted) and str(d.get("startDate", ""))[:10] == ISSUE
                      and str(d.get("endDate", ""))[:10] == EXPIRY for d in copy_documents(card))
        preserved = comparable_card(card) == comparable_card(before_card)
        if visible and preserved:
            confirmed.append({"offer_id": offer, "nmID": target["wb_nmID"], "document_visible": True,
                              "unrelated_card_fields_preserved": True})
            readback_counts["visible_and_preserved"] += 1
        elif visible:
            readback_counts["visible_but_other_fields_changed"] += 1
        else:
            readback_counts["document_missing"] += 1

    plan.update({"phase": "complete_with_wb_readback", "finished_at": now(),
                 "readback_snapshot_rows": len(after_rows), "readback_counts": dict(readback_counts),
                 "readback_target_card_problems": readback_problems, "confirmed": confirmed,
                 "confirmed_count": len(confirmed), "new_write_count": len(candidates),
                 "preexisting_exact_count": len(already), "skip_counts": dict(skips),
                 "wb_review_verdict": "left unchanged for marketplace review; exact document visibility confirmed",
                 "local_files_deleted": False, "ozon_linked_count": 0,
                 "ozon_blocker": "official certificate number rejected by Ozon number-format validation; no exact Ozon record exists"})
    save(plan)
    print(json.dumps({k: plan[k] for k in ("phase", "number", "manifest_target_count", "new_write_count",
                 "preexisting_exact_count", "confirmed_count", "skip_counts", "readback_counts",
                 "wb_review_verdict", "local_files_deleted", "ozon_linked_count", "ozon_blocker")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
