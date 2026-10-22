"""Safely attach three previously uploaded, live-approved certificates to WB cards.

Runs a full live Ozon and WB preflight. Without --execute it only writes a plan.
Mutations are journaled before sending and are never automatically retried.
Local source files are intentionally preserved while any Ozon target link is pending.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    UPDATE_CARD_FIELDS, OZON_TO_WB_TYPE, copy_documents, doc_key, norm_number,
)

ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
OUT_PLAN = HERE / "older_pending_certificates_wb_plan_20261020.json"
OUT_READBACK = HERE / "older_pending_certificates_wb_readback_20261020.json"
JOURNAL = HERE / "older_pending_certificates_wb_mutations_20261020.jsonl"
OZON_IDS = {
    "ЕАЭС RU С-CN.СП28.В.04871/26": 5448220,
    "ЕАЭС RU С-CN.НА75.В.02046/22": 5448281,
    "ЕАЭС RU С-CN.НА75.В.02041/22": 5448284,
}


def atomic(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def read_ozon_certificate_list(client: Client) -> list[dict]:
    result, seen = [], set()
    page, page_count = 1, 1
    while page <= page_count:
        body = client.call("ozon", "/v1/product/certificate/list",
                           {"page": page, "page_size": 100})
        data = body.get("result") or {}
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Ozon certificate list did not return a certificates array")
        for item in batch:
            cid = int(item.get("certificate_id") or 0)
            if not cid or cid in seen:
                raise RuntimeError("Ozon certificate list has missing or duplicate IDs")
            seen.add(cid)
        result.extend(batch)
        page_count = int(data.get("page_count") or page)
        page += 1
    return result


def read_ozon_products(client: Client, product_ids: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for start in range(0, len(product_ids), 500):
        batch = product_ids[start:start + 500]
        body = client.call("ozon", "/v3/product/info/list",
                           {"product_id": [int(x) for x in batch]})
        items = body.get("items")
        if not isinstance(items, list):
            raise RuntimeError("Ozon product detail response omitted items")
        for item in items:
            pid = str(item.get("product_id") or item.get("id") or "")
            if not pid or pid not in batch or pid in result:
                raise RuntimeError("Ozon product details have missing, repeated, or unexpected IDs")
            result[pid] = item
    if set(result) != set(product_ids):
        raise RuntimeError("Ozon product detail readback is incomplete")
    return result


def read_wb_catalog(client: Client) -> tuple[list[dict], dict]:
    cards, page, cursor, seen = [], 0, {"limit": 100}, set()
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        batch = body.get("cards")
        returned = body.get("cursor") or {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("WB catalog returned an invalid page or cursor")
        page += 1
        cards.extend(batch)
        if len(batch) < 100:
            break
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB catalog cursor is missing or repeated")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
    nmids = [str(c.get("nmID") or "") for c in cards]
    if any(not n for n in nmids) or len(nmids) != len(set(nmids)):
        raise RuntimeError("WB catalog contains missing or duplicate nmID values")
    metadata = {"complete": True, "checked_at": now(), "pages": page,
                "raw_rows": len(cards), "unique_nmids": len(set(nmids))}
    return cards, metadata


def norm_brand(value: object) -> str:
    return "".join(str(value or "").casefold().split())


def read_assignments() -> dict[str, list[dict]]:
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected: dict[str, list[dict]] = {}
    for number in OZON_IDS:
        key = norm_number(number)
        selected[number] = [r for r in rows if norm_number(r.get("Номер/название документа")) == key]
        if not selected[number]:
            raise RuntimeError(f"No assignment rows found for {number}")
    return selected


def make_payload(card: dict, desired: dict) -> dict | None:
    items = copy_documents(card)
    same_number = [x for x in items if norm_number(x.get("number")) == norm_number(desired["number"])]
    if same_number:
        if any(doc_key(x) != doc_key(desired)
               or str(x.get("startDate") or "")[:10] != desired["startDate"][:10]
               or str(x.get("endDate") or "")[:10] != desired["endDate"][:10]
               for x in same_number):
            raise ValueError("existing_document_type_or_date_conflict")
        return None
    payload = {field: card[field] for field in UPDATE_CARD_FIELDS if field in card}
    if not payload.get("nmID") or not payload.get("vendorCode"):
        raise ValueError("writable_card_identity_fields_missing")
    payload["documents"] = {"items": items + [desired], "excludeDocuments": False}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="send verified WB card updates")
    args = parser.parse_args()
    assignment_rows = read_assignments()
    records = read_ozon_certificate_list(Client())
    by_id = {int(r["certificate_id"]): r for r in records}
    if len(by_id) != len(records):
        raise RuntimeError("Ozon certificate list contains duplicate certificate IDs")

    rows_by_number, bindings_by_number, product_ids = {}, {}, set()
    for number, cid in OZON_IDS.items():
        rows = assignment_rows[number]
        if len({r["Артикул продавца"] for r in rows}) != len(rows):
            raise RuntimeError(f"Duplicate assigned offer for {number}")
        source_paths = {r["Локальный файл"] for r in rows}
        source_hashes = {r["SHA256 фактический"] for r in rows}
        if len(source_paths) != 1 or len(source_hashes) != 1:
            raise RuntimeError(f"Source file/hash is not unique for {number}")
        source_path = ROOT / next(iter(source_paths))
        source_hash = next(iter(source_hashes))
        if not source_path.is_file() or digest(source_path) != source_hash:
            raise RuntimeError(f"Source file is absent or hash mismatched for {number}")
        record = by_id.get(cid)
        if not record or norm_number(record.get("certificate_number")) != norm_number(number):
            raise RuntimeError(f"Ozon live certificate ID/number mismatch for {number}")
        if record.get("status_code") != "approved" or record.get("type_code") != "certificate_of_conformity" or record.get("accordance_type_code") != "EAEU":
            raise RuntimeError(f"Ozon certificate is not currently approved EAEU certificate for {number}")
        bindings = Client().ozon_bindings(cid)
        if len(bindings) != len(rows) or len({str(b.get("product_id")) for b in bindings}) != len(bindings):
            raise RuntimeError(f"Ozon live binding count is not exact for {number}")
        issue, expiry = str(record.get("issue_date") or ""), str(record.get("expire_date") or "")
        if not issue[:10] or not expiry[:10] or issue[:10] > dt.datetime.now(dt.timezone.utc).date().isoformat() or expiry[:10] < dt.datetime.now(dt.timezone.utc).date().isoformat():
            raise RuntimeError(f"Ozon certificate dates are not currently valid for {number}")
        if any(str(r.get("Тип документа") or "").casefold() not in {"сертификат соответствия", "сертификат 004"} for r in rows):
            raise RuntimeError(f"Assignment rows contain unexpected document type for {number}")
        rows_by_number[number] = rows
        bindings_by_number[number] = bindings
        product_ids.update(str(b["product_id"]) for b in bindings)

    client = Client()
    products = read_ozon_products(client, sorted(product_ids))
    groups = []
    for number, cid in OZON_IDS.items():
        rows = rows_by_number[number]
        offers_from_rows = {r["Артикул продавца"] for r in rows}
        binding_offers = set()
        product_identity_problems = []
        binding_status_counts = Counter()
        for binding in bindings_by_number[number]:
            pid = str(binding["product_id"])
            item = products[pid]
            offer = str(item.get("offer_id") or "")
            binding_offers.add(offer)
            binding_status_counts[str(binding.get("product_status_code") or "MISSING")] += 1
            if not offer or offer not in offers_from_rows:
                product_identity_problems.append({"product_id": pid, "offer_id": offer, "reason": "offer_not_in_source_assignment"})
            source_row = next((r for r in rows if r["Артикул продавца"] == offer), None)
            live_brand = item.get("brand")
            if source_row and live_brand and norm_brand(live_brand) != norm_brand(source_row["Бренд подтвержденный"]):
                product_identity_problems.append({"product_id": pid, "offer_id": offer, "reason": "brand_mismatch"})
        if binding_offers != offers_from_rows or product_identity_problems:
            raise RuntimeError(f"Ozon live target identities do not exactly match source rows for {number}")
        record = by_id[cid]
        end_date = str(record["expire_date"])[:10]
        desired = {"type": OZON_TO_WB_TYPE[record["type_code"]],
                   "number": record["certificate_number"],
                   "startDate": f"{str(record['issue_date'])[:10]}T00:00:00Z",
                   "endDate": f"{end_date}T00:00:00Z", "isEndless": False}
        groups.append({"number": number, "certificate_id": cid,
                       "ozon_document_status": record.get("status_code"),
                       "ozon_binding_status_counts": dict(binding_status_counts),
                       "source_row_count": len(rows), "live_target_count": len(binding_offers),
                       "source_path": rows[0]["Локальный файл"],
                       "source_sha256": rows[0]["SHA256 фактический"],
                       "brand": rows[0]["Бренд подтвержденный"], "desired_wb_document": desired,
                       "target_offers": sorted(offers_from_rows)})

    wb_cards, wb_meta = read_wb_catalog(client)
    by_offer: dict[str, list[dict]] = defaultdict(list)
    for card in wb_cards:
        by_offer[str(card.get("vendorCode") or "")].append(card)
    all_updates, summaries = [], []
    for group in groups:
        missing, exact, no_card, ambiguous, blocked = [], [], [], [], []
        for offer in group["target_offers"]:
            cards = by_offer.get(offer, [])
            if not cards:
                no_card.append(offer)
                continue
            if len(cards) != 1:
                ambiguous.append({"offer": offer, "nmIDs": [c.get("nmID") for c in cards]})
                continue
            card = cards[0]
            try:
                payload = make_payload(card, group["desired_wb_document"])
            except ValueError as exc:
                blocked.append({"offer": offer, "nmID": card.get("nmID"), "reason": str(exc)})
                continue
            if payload is None:
                # Exact document readback is stronger than a missing/different display-brand
                # field; retain the card without rewriting its unrelated product fields.
                exact.append({"offer": offer, "nmID": card.get("nmID"), "brand": card.get("brand"),
                              "brand_identity_warning": norm_brand(card.get("brand")) != norm_brand(group["brand"])})
            else:
                if norm_brand(card.get("brand")) != norm_brand(group["brand"]):
                    blocked.append({"offer": offer, "nmID": card.get("nmID"), "reason": "wb_brand_mismatch", "brand": card.get("brand")})
                    continue
                missing.append({"offer": offer, "nmID": card.get("nmID")})
                all_updates.append((group["number"], payload))
        summaries.append({"number": group["number"], "ozon_binding_status_counts": group["ozon_binding_status_counts"],
                          "target_offers": len(group["target_offers"]), "wb_exact_already_present": exact,
                          "wb_missing_exact_document": missing, "wb_no_card": no_card,
                          "wb_ambiguous": ambiguous, "wb_conflicts": blocked})

    plan = {"checked_at": now(), "execute_requested": args.execute,
            "source_assignment": str(ASSIGNMENTS), "wb_catalog": wb_meta,
            "groups": groups, "wb_summary": summaries,
            "update_count": len(all_updates),
            "payload_sha256": hashlib.sha256(json.dumps([p for _, p in all_updates], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "cleanup": "source files retained: each Ozon record still has awaiting_verification target bindings"}
    atomic(OUT_PLAN, plan)

    if not args.execute:
        print(json.dumps({"phase": "preflight_complete", "plan": str(OUT_PLAN), "wb_cards": len(wb_cards),
                          "groups": [{"number": x["number"], "missing": len(x["wb_missing_exact_document"]),
                                      "already_exact": len(x["wb_exact_already_present"]), "no_card": len(x["wb_no_card"]),
                                      "blocked": len(x["wb_conflicts"]) + len(x["wb_ambiguous"])} for x in summaries]}, ensure_ascii=False), flush=True)
        return

    if JOURNAL.exists() and JOURNAL.stat().st_size:
        raise RuntimeError("Mutation journal already exists; reconcile its live state before another execution")
    last_write = None
    grouped_payloads: dict[str, list[dict]] = defaultdict(list)
    for number, payload in all_updates:
        grouped_payloads[number].append(payload)
    if any(x["wb_conflicts"] or x["wb_ambiguous"] for x in summaries):
        raise RuntimeError("Conflicts or ambiguous WB offers found; refusing all mutations")
    for group in groups:
        number = group["number"]
        payload = grouped_payloads.get(number, [])
        if not payload:
            continue
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(payload) > 3000 or len(encoded) > 10_000_000:
            raise RuntimeError(f"WB update batch limit exceeded for {number}")
        key = hashlib.sha256(encoded).hexdigest()
        with JOURNAL.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps({"phase": "PREPARED", "at": now(), "number": number,
                                      "count": len(payload), "request_sha256": key}, ensure_ascii=False) + "\n")
            journal.flush(); os.fsync(journal.fileno())
        if last_write is not None:
            time.sleep(max(0, 6.0 - (time.monotonic() - last_write)))
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        last_write = time.monotonic()
        with JOURNAL.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps({"phase": "RESPONSE", "at": now(), "number": number,
                                      "request_sha256": key, "response": response}, ensure_ascii=False) + "\n")
            journal.flush(); os.fsync(journal.fileno())
    # Independent post-write full read verifies each offer/nmID and exact document metadata.
    readback_cards, readback_meta = read_wb_catalog(client)
    rb_by_offer: dict[str, list[dict]] = defaultdict(list)
    for card in readback_cards:
        rb_by_offer[str(card.get("vendorCode") or "")].append(card)
    verification = []
    for group in groups:
        desired = group["desired_wb_document"]
        for offer in group["target_offers"]:
            cards = rb_by_offer.get(offer, [])
            if len(cards) != 1:
                verification.append({"number": group["number"], "offer": offer, "verified": False,
                                     "reason": "missing_or_ambiguous_wb_card", "card_count": len(cards)})
                continue
            docs = ((cards[0].get("documents") or {}).get("items") or [])
            matching = [x for x in docs if norm_number(x.get("number")) == norm_number(desired["number"])]
            valid = (len(matching) == 1 and doc_key(matching[0]) == doc_key(desired)
                     and str(matching[0].get("startDate") or "")[:10] == desired["startDate"][:10]
                     and str(matching[0].get("endDate") or "")[:10] == desired["endDate"][:10])
            verification.append({"number": group["number"], "offer": offer,
                                 "nmID": cards[0].get("nmID"), "verified": valid,
                                 "document_match_count": len(matching),
                                 "verdict": matching[0].get("verdict") if matching else None})
    rb = {"checked_at": now(), "wb_catalog": readback_meta, "expected_target_edges": sum(len(g["target_offers"]) for g in groups),
          "verified_edges": sum(bool(x["verified"]) for x in verification),
          "failed_edges": [x for x in verification if not x["verified"]], "edges": verification,
          "local_files_deleted": 0,
          "local_cleanup_hold": "Ozon still has awaiting_verification links in all three certificates"}
    atomic(OUT_READBACK, rb)
    print(json.dumps({"phase": "readback_complete", "readback": str(OUT_READBACK),
                      "verified_edges": rb["verified_edges"], "expected_edges": rb["expected_target_edges"],
                      "failed_edges": len(rb["failed_edges"]), "local_files_deleted": 0}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
