"""Attach two already Ozon-approved IEK certificates to exact live WB cards.

Dry-run by default. A write requires fresh exact Ozon product/SKU/brand/TNVED
and approved-binding evidence plus a unique matching WB card. Existing documents
and card data are merged and checked; WB review stays with the marketplace.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

MANIFEST = HERE / "iek_missing_new_docs_manifest_20261020.json"
NUMBERS = {"ЕАЭС RU С-CN.АЯ46.В.47749/26", "ЕАЭС RU С-CN.АЯ46.В.48571/26"}
OUT = HERE / "iek_47749_48571_wb_20261022.json"
JOURNAL = HERE / "iek_47749_48571_wb_mutation_journal_20261022.jsonl"
ALLOWED = {"8536490000", "8536699008"}


def save(value: dict) -> None:
    value["updated_at"] = now()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(OUT)


def ozon_attrs(client: Client, targets: list[dict]) -> dict[str, dict]:
    offers = [x["offer_id"] for x in targets]
    result = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers),
    }).get("result")
    if not isinstance(result, list):
        raise RuntimeError("Ozon attributes response omitted result")
    by_offer = {}
    for row in result:
        offer = str(row.get("offer_id") or "")
        if not offer or offer in by_offer:
            raise RuntimeError("Ozon attributes have missing or duplicate offer identity")
        by_offer[offer] = row
    if set(by_offer) != set(offers):
        raise RuntimeError("Ozon attributes do not cover all target offers")
    return by_offer


def attr_values(row: dict, ident: str) -> set[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return {str(x.get("value")).strip() for x in (attrs.get(ident) or {}).get("values") or []
            if x.get("value") not in (None, "")}


def fetch_records(client: Client) -> dict[str, dict]:
    found = {}
    page = 1
    while page <= 100:
        data = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result") or {}
        rows = data.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("Ozon certificate list omitted records")
        for record in rows:
            cid = str(record.get("certificate_id") or "")
            if not cid or cid in found:
                raise RuntimeError("Ozon certificate list has missing/duplicate IDs")
            found[cid] = record
        if page >= int(data.get("page_count") or page):
            return found
        page += 1
    raise RuntimeError("Ozon certificate pagination exceeded limit")


def read_target_cards(client: Client, offers: set[str]) -> tuple[dict[str, list[dict]], int]:
    cursor = {"limit": 100}
    seen = set()
    matched = []
    raw_rows = 0
    page = 0
    while True:
        body = client.call("wb", "/content/v2/get/cards/list", {"settings": {
            "sort": {"ascending": True}, "cursor": cursor,
            "filter": {"withPhoto": -1},
        }})
        data = body.get("data", body)
        batch = data.get("cards") or data.get("items") or []
        returned = data.get("cursor") or body.get("cursor") or {}
        if body.get("error") or not isinstance(batch, list) or returned.get("total") != len(batch):
            raise RuntimeError("WB full-catalog page/cursor is invalid")
        page += 1
        raw_rows += len(batch)
        matched.extend(c for c in batch if str(c.get("vendorCode") or "") in offers)
        if page % 50 == 0:
            print(json.dumps({"phase": "wb_read", "pages": page, "raw_rows": raw_rows,
                              "target_rows": len(matched)}, ensure_ascii=False), flush=True)
        if len(batch) < 100:
            break
        signature = (returned.get("updatedAt"), returned.get("nmID"))
        if None in signature or signature in seen:
            raise RuntimeError("WB full-catalog cursor is missing or repeated")
        seen.add(signature)
        cursor = {"limit": 100, "updatedAt": signature[0], "nmID": signature[1]}
    unique, duplicates = runner.deduplicate_equivalent_wb_rows(matched)
    by_offer = {}
    for card in unique:
        by_offer.setdefault(str(card.get("vendorCode") or ""), []).append(card)
    return by_offer, duplicates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute and JOURNAL.exists():
        raise RuntimeError("Prior write journal exists; reconcile exact live state before retry")
    manifest = json.loads(MANIFEST.read_text())
    groups = [g for g in manifest.get("groups", []) if g.get("number") in NUMBERS]
    if {g.get("number") for g in groups} != NUMBERS:
        raise RuntimeError("Reviewed source manifest does not contain both exact documents")
    client = Client()
    records = fetch_records(client)
    all_targets = [t for g in groups for t in g["targets"]]
    ids = [str(t["product_id"]) for t in all_targets]
    details_resp = client.call("ozon", "/v3/product/info/list", {
        "product_id": [int(x) for x in ids],
    }).get("items")
    if not isinstance(details_resp, list):
        raise RuntimeError("Ozon product details omitted items")
    details = {str(x.get("product_id") or x.get("id") or ""): x for x in details_resp}
    if set(details) != set(ids) or len(details) != len(ids):
        raise RuntimeError("Ozon product identity set differs from manifest")
    attrs = ozon_attrs(client, all_targets)
    wb_by_offer, wb_duplicate_rows_removed = read_target_cards(
        client, {str(t["offer_id"]) for t in all_targets})
    planned = []
    result = {
        "checked_at": now(), "execute": args.execute, "documents": [],
        "preflight_counts": {}, "wb_review_left_pending": True,
        "local_files_deleted": False,
    }
    counts = Counter()
    for group in groups:
        err = runner.group_error(group)
        if err or group.get("source_evidence_verified") is not True:
            raise RuntimeError(f"Document source evidence/date/hash gate failed: {group.get('number')} {err}")
        matches = [x for x in records.values()
                   if str(x.get("certificate_number") or "") == group["number"]
                   and x.get("type_code") == group["type_code"]
                   and x.get("accordance_type_code") == "EAEU"]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one exact Ozon certificate record: {group['number']}")
        cert = matches[0]
        if cert.get("status_code") != "approved":
            raise RuntimeError(f"Ozon certificate is not approved: {group['number']}")
        bindings = client.ozon_bindings(cert["certificate_id"])
        binding_by_pid = {str(x.get("product_id")): x for x in bindings}
        if len(binding_by_pid) != len(bindings):
            raise RuntimeError("Duplicate Ozon product bindings")
        wanted = {"type": 1, "number": group["number"],
                  "startDate": wb_datetime(group["issue_date"]),
                  "endDate": wb_datetime(group["expire_date"]), "isEndless": False}
        doc_result = {"number": group["number"], "certificate_id": str(cert["certificate_id"]),
                      "ozon_status": cert["status_code"], "targets": []}
        for target in group["targets"]:
            offer = target["offer_id"]
            detail = details[str(target["product_id"])]
            if (str(detail.get("offer_id") or "") != offer
                    or str(detail.get("sku") or "") != str(target["sku"])
                    or detail.get("is_archived") is True):
                raise RuntimeError(f"Ozon offer/product/SKU identity changed: {offer}")
            attr = attrs[offer]
            attr_pid = str(attr.get("id") or attr.get("product_id") or "")
            if attr_pid != str(target["product_id"]):
                raise RuntimeError(f"Ozon attribute product identity changed: {offer}")
            brands = attr_values(attr, "85")
            tnved = {x.split(" - ", 1)[0].strip() for x in attr_values(attr, "22232")}
            if brands != {"IEK"} or not tnved or not tnved <= ALLOWED:
                raise RuntimeError(f"Ozon brand/TNVED outside verified scope: {offer} {brands} {tnved}")
            binding = binding_by_pid.get(str(target["product_id"]))
            if (not binding or str(binding.get("sku") or "") != str(target["sku"])
                    or binding.get("product_status_code") != "approved"):
                raise RuntimeError(f"Ozon exact binding is absent or not approved: {offer}")
            exact = wb_by_offer.get(offer, [])
            if len(exact) != 1:
                raise RuntimeError(f"WB exact card missing or duplicate: {offer}")
            card = exact[0]
            wb_error = runner.wb_scope_error(card, group, target)
            if wb_error:
                raise RuntimeError(f"WB brand/TNVED scope failed: {offer} {wb_error}")
            same = [d for d in copy_documents(card)
                    if norm_number(d.get("number")) == norm_number(group["number"])]
            if same:
                if not all(doc_key(d) == doc_key(wanted)
                           and str(d.get("startDate", ""))[:10] == wanted["startDate"][:10]
                           and str(d.get("endDate", ""))[:10] == wanted["endDate"][:10]
                           for d in same):
                    raise RuntimeError(f"WB has conflicting same-number document: {offer}")
                counts["already_exact"] += 1
                doc_result["targets"].append({"offer_id": offer, "nmID": str(card["nmID"]),
                                              "action": "already_exact"})
                continue
            payload = runner.merge_wb(card, [wanted])
            if payload is None:
                counts["already_exact"] += 1
                continue
            planned.append({"offer": offer, "group": group, "target": target,
                            "card": card, "payload": payload, "document": wanted})
            counts["planned"] += 1
            doc_result["targets"].append({"offer_id": offer, "nmID": str(card["nmID"]),
                                          "action": "planned"})
        result["documents"].append(doc_result)

    result["preflight_counts"] = dict(counts)
    result["target_edges"] = len(all_targets)
    result["wb_target_catalog_duplicates_removed"] = wb_duplicate_rows_removed
    result["planned_cards"] = len(planned)
    result["wb_review_left_pending"] = True
    result["local_files_deleted"] = False
    if not args.execute:
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "documents"}, ensure_ascii=False))
        return
    if not planned:
        result["phase"] = "no_write_needed"
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "documents"}, ensure_ascii=False))
        return
    # Re-read the exact cards from the full live catalog before mutation; the
    # WB text-search endpoint does not reliably return these seller codes.
    fresh_by_offer, fresh_duplicates = read_target_cards(
        client, {row["offer"] for row in planned})
    refreshed = []
    for row in planned:
        matches = fresh_by_offer.get(row["offer"], [])
        if len(matches) != 1 or str(matches[0].get("nmID")) != str(row["card"].get("nmID")):
            raise RuntimeError(f"WB card identity changed before write: {row['offer']}")
        if runner.wb_scope_error(matches[0], row["group"], row["target"]):
            raise RuntimeError(f"WB scope changed before write: {row['offer']}")
        payload = runner.merge_wb(matches[0], [row["document"]])
        if payload is None:
            counts["already_exact_before_write"] += 1
            continue
        refreshed.append({**row, "card": matches[0], "payload": payload})
    planned = refreshed
    result["wb_prewrite_duplicate_rows_removed"] = fresh_duplicates
    result["planned_cards"] = len(planned)
    if not planned:
        result["phase"] = "all_exact_before_write"
        save(result)
        print(json.dumps({k: v for k, v in result.items() if k != "documents"}, ensure_ascii=False))
        return
    for row in planned:
        JOURNAL.open("a", encoding="utf-8").write(json.dumps({
            "key": f"wb:{row['card']['nmID']}:{doc_key(row['document'])}",
            "phase": "prepared", "at": now(), "offer_id": row["offer"],
            "endpoint": "/content/v2/cards/update",
        }, ensure_ascii=False) + "\n")
    response = client.call("wb", "/content/v2/cards/update",
                           [x["payload"] for x in planned], mutation=True)
    result["mutation_response"] = {"error": response.get("error"),
                                   "additionalErrors": response.get("additionalErrors")}
    if response.get("error") is not False:
        result["phase"] = "response_rejected_or_uncertain"
        save(result)
        raise RuntimeError("WB did not positively accept update; reconcile before any retry")
    result["phase"] = "accepted_readback_pending"
    result["accepted_cards"] = len(planned)
    save(result)
    readbacks = []
    readback_by_offer, readback_duplicates = read_target_cards(
        client, {row["offer"] for row in planned})
    result["wb_readback_duplicate_rows_removed"] = readback_duplicates
    for row in planned:
        matches = readback_by_offer.get(row["offer"], [])
        card_after = matches[0] if len(matches) == 1 and str(matches[0].get("nmID")) == str(row["card"]["nmID"]) else None
        visible = bool(card_after and runner.merge_wb(card_after, [row["document"]]) is None)
        prior_docs = {(doc_key(d), str(d.get("startDate", ""))[:10],
                       str(d.get("endDate", ""))[:10]) for d in copy_documents(row["card"])}
        after_docs = {(doc_key(d), str(d.get("startDate", ""))[:10],
                       str(d.get("endDate", ""))[:10]) for d in copy_documents(card_after)} if card_after else set()
        preserved = bool(card_after and comparable_card(card_after) == comparable_card(row["card"])
                         and prior_docs <= after_docs)
        verdicts = []
        if card_after:
            for item in (card_after.get("documents") or {}).get("items") or []:
                if norm_number(item.get("number")) == norm_number(row["document"]["number"]):
                    verdicts.append(item.get("verdict"))
        readbacks.append({"offer_id": row["offer"], "nmID": str(row["card"]["nmID"]),
                          "document_visible": visible, "prior_documents_and_card_fields_preserved": preserved,
                          "verdicts": verdicts})
    result["readbacks"] = readbacks
    result["phase"] = "complete_visible_review_left_pending" if all(
        x["document_visible"] and x["prior_documents_and_card_fields_preserved"] for x in readbacks
    ) else "accepted_readback_incomplete_reconcile_only"
    result["wb_review_left_pending"] = True
    result["local_files_deleted"] = False
    save(result)
    print(json.dumps({k: v for k, v in result.items() if k != "documents"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
