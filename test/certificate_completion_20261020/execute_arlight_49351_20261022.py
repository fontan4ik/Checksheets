#!/usr/bin/env python3
"""Attach verified Arlight declaration 49351/25 to jointly safe Ozon/WB targets."""
from __future__ import annotations

import base64
import collections
import datetime
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = ROOT / "test/certificate_api_pilot_20261012"
PREFLIGHT = HERE / "arlight_49351_crossplatform_preflight_20261022.json"
STATE = HERE / "arlight_49351_execution_20261022.json"
WB_BEFORE = HERE / "arlight_49351_wb_before_20261022.json"
READBACK = HERE / "arlight_49351_final_crossplatform_readback_20261022.json"
JOURNAL = HERE / "arlight_49351_mutation_journal_20261022.jsonl"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
SOURCE_REL = "output_to_user/certificates/group_1/documents/arlight/79170C7457575442AC903D659848BC1A.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА10.В.49351/25"
ISSUE = "2025-11-18"
EXPIRE = "2030-11-16"
REGISTRY_ID = "20856872"
TNVED = {"8539519009"}
sys.path.insert(0, str(PILOT))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_incomplete")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def fresh_ozon(client: Client, targets: list[dict]) -> list[dict]:
    offers = [str(x["offer_id"]) for x in targets]
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    pmap = collections.defaultdict(list)
    amap = collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id") or "")].append(row)
    for row in attrs:
        amap[str(row.get("offer_id") or "")].append(row)
    out = []
    for target in targets:
        offer = str(target["offer_id"])
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("ozon_live_identity_not_unique:" + offer)
        product, attr = pmap[offer][0], amap[offer][0]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        values = {str(x.get("id")): [str(v.get("value") or "").strip()
                  for v in x.get("values") or [] if str(v.get("value") or "").strip()]
                  for x in attr.get("attributes") or []}
        brands = values.get("85", [])
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in values.get("22232", [])})
        live_name = str(product.get("name") or "").strip()
        source_name = str(target.get("source_name") or "").strip()
        if (product_id != str(target["product_id"]) or sku != str(target["sku"])
                or product.get("is_archived") is not False or brands != ["Arlight"]
                or not tnved or not set(tnved).issubset(TNVED)
                or live_name.casefold() != source_name.casefold()
                or not offer.endswith("-1") or offer[:-2] != target["article"]):
            raise RuntimeError("ozon_live_scope_or_identity_changed:" + offer)
        out.append({**target, "product_id": product_id, "sku": sku,
                    "live_name": product.get("name"), "tnved_codes": tnved})
    return out


def bind_ozon(client: Client, record: dict, targets: list[dict]) -> dict:
    cert_id = int(record["certificate_id"])
    current = client.ozon_bindings(cert_id)
    by_product = collections.defaultdict(list)
    for row in current:
        by_product[str(row.get("product_id") or "")].append(row)
    missing = []
    for target in targets:
        rows = by_product.get(str(target["product_id"]), [])
        if len(rows) > 1:
            raise RuntimeError("ozon_duplicate_bindings:" + target["offer_id"])
        if not rows:
            missing.append(target)
        elif (str(rows[0].get("sku") or "") != str(target["sku"])
              or rows[0].get("product_status_code") == "declined"):
            raise RuntimeError("ozon_existing_binding_conflict:" + target["offer_id"])
    if missing:
        skus = [str(x["sku"]) for x in missing]
        request = {"certificate_id": cert_id, "skus": skus}
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "phase": "prepared", "document_number": NUMBER, "sku_count": len(skus),
                 "request_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest()})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            error_type = None
        except Exception as exc:
            response, error_type = None, type(exc).__name__
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "phase": "response" if response is not None else "uncertain", "response": response,
                 "error_type": error_type, "document_number": NUMBER})
    live = client.ozon_bindings(cert_id)
    by_pair = collections.defaultdict(list)
    for row in live:
        by_pair[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
    bindings = []
    for target in targets:
        pair = (str(target["product_id"]), str(target["sku"]))
        rows = by_pair.get(pair, [])
        bindings.append({"offer_id": target["offer_id"], "product_id": pair[0], "sku": pair[1],
                         "exact": len(rows) == 1,
                         "status": rows[0].get("product_status_code") if len(rows) == 1 else None})
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}
    return {"certificate_id": str(cert_id), "record_status": info.get("status_code"),
            "expected": len(targets), "exact_visible": sum(x["exact"] for x in bindings),
            "status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in bindings)),
            "bindings": bindings}


def attach_wb(client: Client, targets: list[dict]) -> dict:
    before_rows, updates = [], []
    for index, target in enumerate(targets, 1):
        offer = target["offer_id"]
        cards = []
        for attempt in range(3):
            cards = client.wb_cards(offer)
            if len(cards) == 1 or attempt == 2:
                break
            time.sleep(2)
        if len(cards) != 1:
            raise RuntimeError("wb_live_card_count_changed:" + offer)
        card = cards[0]
        card_tnved = []
        for item in card.get("characteristics") or []:
            label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
            if "тнвэд" in label or "тнвед" in label:
                raw = item.get("value")
                card_tnved.extend(raw if isinstance(raw, list) else [raw])
        card_tnved = sorted({str(x).split(" - ", 1)[0].strip() for x in card_tnved if str(x).strip()})
        if (str(card.get("nmID") or "") != str(target["nmID"])
                or str(card.get("vendorCode") or "") != offer
                or str(card.get("brand") or "").casefold() != "arlight"
                or not card_tnved or not set(card_tnved).issubset(TNVED)):
            raise RuntimeError("wb_live_scope_or_identity_changed:" + offer)
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if int(x.get("type") or 0) == 2
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRE]
        if same and len(exact) != 1:
            raise RuntimeError("wb_same_number_conflict:" + offer)
        wanted = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
                  "endDate": wb_datetime(EXPIRE), "isEndless": False}
        payload = runner.merge_wb(card, [wanted])
        before_rows.append({"offer_id": offer, "nmID": str(card["nmID"]), "card": card,
                            "prior_documents": docs, "already_exact": payload is None})
        if payload is not None:
            updates.append({"offer_id": offer, "nmID": str(card["nmID"]), "payload": payload,
                            "before": card, "prior_documents": docs})
        if index % 15 == 0 or index == len(targets):
            print(json.dumps({"wb_live_preflight_cards": index, "total": len(targets)}, ensure_ascii=False), flush=True)
    save(WB_BEFORE, {"checked_at_utc": now(), "complete": True, "target_cards": len(before_rows),
                     "updates": len(updates), "already_exact": len(before_rows) - len(updates),
                     "cards": before_rows})
    response, error_type = None, None
    if updates:
        payloads = [x["payload"] for x in updates]
        marker = hashlib.sha256(json.dumps(payloads, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "prepared", "document_number": NUMBER, "cards": len(updates),
                 "offers": [x["offer_id"] for x in updates], "request_sha256": marker})
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            error_type = type(exc).__name__
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "response" if response is not None else "uncertain", "response": response,
                 "error_type": error_type, "document_number": NUMBER})

    readbacks, failures = [], []
    before = {x["offer_id"]: x for x in before_rows}
    for index, target in enumerate(targets, 1):
        offer = target["offer_id"]
        cards = []
        for attempt in range(3):
            cards = client.wb_cards(offer)
            if len(cards) == 1 or attempt == 2:
                break
            time.sleep(2)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count", "count": len(cards)})
            continue
        card = cards[0]
        docs = (card.get("documents") or {}).get("items") or []
        matches = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)
                   and int(x.get("type") or 0) == 2
                   and str(x.get("startDate") or "")[:10] == ISSUE
                   and str(x.get("endDate") or "")[:10] == EXPIRE
                   and x.get("isEndless") is False]
        prior = before[offer]
        old_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10],
                           str(x.get("endDate") or "")[:10], x.get("isEndless"))
                          for x in prior["prior_documents"]]
        after_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10],
                             str(x.get("endDate") or "")[:10], x.get("isEndless")) for x in docs]
        old_preserved = all(x in after_signatures for x in old_signatures)
        fields_preserved = comparable_card(card) == comparable_card(prior["card"])
        verdict = matches[0].get("verdict") if len(matches) == 1 else None
        valid = (isinstance(verdict, dict) and verdict.get("verified") is True
                 and verdict.get("status") == 1 and verdict.get("reason") == "valid")
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "exact_metadata": len(matches) == 1, "prior_documents_preserved": old_preserved,
               "unrelated_card_fields_preserved": fields_preserved,
               "verdict": verdict, "marketplace_valid": valid}
        readbacks.append(row)
        if len(matches) != 1 or not old_preserved or not fields_preserved:
            failures.append({"offer_id": offer, "problem": "document_or_preservation_readback_failed",
                             "exact_metadata_count": len(matches), "prior_documents_preserved": old_preserved,
                             "unrelated_card_fields_preserved": fields_preserved})
        if index % 15 == 0 or index == len(targets):
            print(json.dumps({"wb_readbacks": index, "total": len(targets)}, ensure_ascii=False), flush=True)
    return {"target_cards": len(targets), "updates_sent": len(updates), "response": response,
            "error_type": error_type, "exact_metadata_cards": sum(x["exact_metadata"] for x in readbacks),
            "valid_verdict_cards": sum(x["marketplace_valid"] for x in readbacks),
            "pending_or_unverified_cards": sum(x["exact_metadata"] and not x["marketplace_valid"] for x in readbacks),
            "readback_count": len(readbacks), "failures": failures, "cards": readbacks,
            "review_state_changed_by_agent": False, "left_for_marketplace_review": True}


def main() -> None:
    for path in (STATE, WB_BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("number") != NUMBER:
        raise RuntimeError("preflight_missing_or_mismatched")
    source = ROOT / pre["source_file"]
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != pre["source_sha256"]:
        raise RuntimeError("source_file_hash_mismatch")
    ozon_eligible = {x["offer_id"]: x for x in pre["ozon_targets"] if x.get("eligible") is True}
    wb_eligible = {x["offer_id"]: x for x in pre["wb_targets"] if x.get("eligible") is True}
    joint_offers = sorted(set(ozon_eligible) & set(wb_eligible))
    if len(joint_offers) != 29:
        raise RuntimeError("joint_eligibility_count_changed:" + str(len(joint_offers)))
    ozon_targets = [ozon_eligible[x] for x in joint_offers]
    wb_targets = [wb_eligible[x] for x in joint_offers]
    state = {"started_at_utc": now(), "phase": "fresh_preflight", "document_number": NUMBER,
             "fsa_record_id": REGISTRY_ID, "source_sha256_verified": True,
             "joint_target_pairs": len(joint_offers), "ozon_target_pairs": len(ozon_targets),
             "wb_target_cards": len(wb_targets), "wb_review_state_changed_by_agent": False,
             "wb_left_for_marketplace_review": True, "local_source_file_deleted": False}
    save(STATE, state)
    client = Client()

    # Fresh Ozon identity check and exact registry-record reconciliation before writes.
    fresh = fresh_ozon(client, ozon_targets)
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_records_for_document")
    record = matches[0] if matches else None
    creation = {"created": False, "record_reused": bool(record)}
    if record:
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRE
                or record.get("status_code") not in {"approved", "under_review"}):
            raise RuntimeError("existing_ozon_record_metadata_or_status_conflict")
    else:
        expires = datetime.date.fromisoformat(EXPIRE)
        params = {"name": "Декларация о соответствии № " + NUMBER,
                  "certificate_type": "DECLARATION", "certificate_country": "RU",
                  "accordance_type": "EAEU", "number": NUMBER,
                  "issue_date": wb_datetime(ISSUE),
                  "expired_date": {"date": {"day": expires.day, "month": expires.month, "year": expires.year}},
                  "skus": [fresh[0]["sku"]], "product_type": "UNKNOWN",
                  "link_to_registry": f"https://pub.fsa.gov.ru/rds/declaration/view/{REGISTRY_ID}/common",
                  "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"),
                             "name": source.name}]}
        payload = {"params": params}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
                 "phase": "prepared", "document_number": NUMBER, "seed_sku": fresh[0]["sku"],
                 "request_bytes": len(encoded), "request_sha256": hashlib.sha256(encoded).hexdigest()})
        try:
            response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            error_type = None
        except Exception as exc:
            response, error_type = None, type(exc).__name__
        journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
                 "phase": "response" if response is not None else "uncertain", "response": response,
                 "error_type": error_type, "document_number": NUMBER})
        found = []
        for attempt in range(7):
            found = [x for x in list_certificates(client)
                     if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
            if found or attempt == 6:
                break
            time.sleep(2)
        if len(found) != 1:
            state["phase"] = "ozon_create_uncertain_no_retry"
            state["ozon_create_error_type"] = error_type
            state["ozon_create_response"] = response
            save(STATE, state)
            record = None
            creation = {"created": bool(response and response.get("certificate_id")),
                        "outcome": "uncertain_no_record_visible_no_retry", "error_type": error_type}
        else:
            record = found[0]
            states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
            if (record.get("type_code") != "declaration"
                    or str(record.get("issue_date") or "")[:10] != ISSUE
                    or str(record.get("expire_date") or "")[:10] != EXPIRE):
                raise RuntimeError("created_ozon_record_metadata_conflict")
            if response is None or response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
                state["phase"] = "ozon_create_response_unvalidated_no_binding"
                state["ozon_record"] = record
                state["ozon_create_response"] = response
                save(STATE, state)
                creation = {"created": True, "outcome": "record_visible_but_create_response_not_validated"}
                record = None
            else:
                creation = {"created": True, "outcome": "record_created_and_validated",
                            "ozon_create_response": response}

    if record is not None:
        ozon_result = bind_ozon(client, record, fresh)
        state["ozon"] = {"creation": creation, "record": record,
                         "readback_summary": {k: v for k, v in ozon_result.items() if k != "bindings"}}
        state["ozon_bindings"] = ozon_result["bindings"]
        state["phase"] = "ozon_bound_wb_pending"
        save(STATE, state)
        print(json.dumps({"ozon_document": NUMBER, "exact": ozon_result["exact_visible"],
                          "expected": ozon_result["expected"], "statuses": ozon_result["status_counts"]},
                         ensure_ascii=False), flush=True)
    else:
        ozon_result = {"expected": len(fresh), "exact_visible": 0, "status_counts": {},
                       "bindings": [], "record_status": None, "certificate_id": None}
        state["ozon"] = {"creation": creation, "readback_summary": ozon_result}
        save(STATE, state)

    wb_result = attach_wb(client, wb_targets)
    state["wb_initial_readback"] = {k: v for k, v in wb_result.items() if k != "cards"}
    state["phase"] = "marketplace_writes_sent"
    save(STATE, state)

    time.sleep(60)
    delayed_ozon = {}
    if record is not None:
        live = client.ozon_bindings(int(record["certificate_id"]))
        by_pair = collections.defaultdict(list)
        for row in live:
            by_pair[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
        binds = []
        for target in fresh:
            matches = by_pair.get((str(target["product_id"]), str(target["sku"])), [])
            binds.append({"offer_id": target["offer_id"], "exact": len(matches) == 1,
                          "status": matches[0].get("product_status_code") if len(matches) == 1 else None})
        info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}
        delayed_ozon = {"certificate_id": str(record["certificate_id"]),
                        "record_status": info.get("status_code"), "expected": len(binds),
                        "exact_visible": sum(x["exact"] for x in binds),
                        "status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in binds)),
                        "bindings": binds}
    else:
        delayed_ozon = {"expected": len(ozon_targets), "exact_visible": 0,
                        "status_counts": {}, "bindings": [], "record_status": None}

    delayed_wb = []
    for index, target in enumerate(wb_targets, 1):
        offer = target["offer_id"]
        cards = []
        for attempt in range(3):
            cards = client.wb_cards(offer)
            if len(cards) == 1 or attempt == 2:
                break
            time.sleep(2)
        if len(cards) != 1:
            delayed_wb.append({"offer_id": offer, "exact_metadata": False, "verdict": None,
                               "error": "readback_card_count"})
            continue
        card = cards[0]
        items = (card.get("documents") or {}).get("items") or []
        matches = [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)
                   and int(x.get("type") or 0) == 2
                   and str(x.get("startDate") or "")[:10] == ISSUE
                   and str(x.get("endDate") or "")[:10] == EXPIRE
                   and x.get("isEndless") is False]
        delayed_wb.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                           "exact_metadata": len(matches) == 1,
                           "verdict": matches[0].get("verdict") if len(matches) == 1 else None})
        if index % 15 == 0 or index == len(wb_targets):
            print(json.dumps({"wb_delayed_readbacks": index, "total": len(wb_targets)}, ensure_ascii=False), flush=True)

    wb_valid = sum(isinstance(x.get("verdict"), dict) and x["verdict"].get("verified") is True
                   and x["verdict"].get("status") == 1 and x["verdict"].get("reason") == "valid"
                   for x in delayed_wb)
    wb_exact = sum(x.get("exact_metadata") is True for x in delayed_wb)
    cross = {"checked_at_utc": now(), "read_only_delayed_reconciliation": True,
             "brand": "Arlight", "document_number": NUMBER, "type": "declaration",
             "fsa_registry_id": REGISTRY_ID, "fsa_status": "active",
             "issue_date": ISSUE, "expire_date": EXPIRE, "source_sha256": pre["source_sha256"],
             "ozon_certificate_id": delayed_ozon.get("certificate_id"),
             "ozon_record_status": delayed_ozon.get("record_status"),
             "ozon_expected_bindings": len(ozon_targets),
             "ozon_exact_bindings": delayed_ozon.get("exact_visible", 0),
             "ozon_binding_status_counts": delayed_ozon.get("status_counts", {}),
             "wb_expected_cards": len(wb_targets), "wb_exact_cards": wb_exact,
             "wb_valid_cards": wb_valid, "wb_pending_or_unverified_cards": wb_exact - wb_valid,
             "wb_review_state_changed_by_agent": False, "wb_left_for_marketplace_review": True,
             "local_source_file_deleted": False,
             "verification_artifacts": [PREFLIGHT.name, STATE.name, READBACK.name],
             "ozon_bindings": delayed_ozon, "wb_cards": delayed_wb}
    save(READBACK, cross)
    state["phase"] = "delayed_readback_complete"
    state["finished_at_utc"] = now()
    state["ozon_delayed_readback"] = {k: v for k, v in delayed_ozon.items() if k != "bindings"}
    state["wb_delayed_readback"] = {"target_cards": len(wb_targets), "exact_metadata_cards": wb_exact,
                                    "valid_cards": wb_valid, "pending_or_unverified_cards": wb_exact-wb_valid}
    save(STATE, state)

    add = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    numbers = {x.get("document_number") for x in add.get("post_snapshot_writes", [])}
    if NUMBER in numbers:
        raise RuntimeError("addendum_already_contains_document")
    entry = {"brand": "Arlight", "document_number": NUMBER, "type": "declaration",
             "fsa_record_id": REGISTRY_ID, "fsa_status": "active", "source_sha256": pre["source_sha256"],
             "ozon_certificate_id": delayed_ozon.get("certificate_id"),
             "ozon_record_status": delayed_ozon.get("record_status"),
             "ozon_exact_bindings": delayed_ozon.get("exact_visible", 0),
             "ozon_binding_status_counts": delayed_ozon.get("status_counts", {}),
             "wb_exact_cards": wb_exact, "wb_valid_cards": wb_valid,
             "wb_pending_or_unverified_cards": wb_exact-wb_valid,
             "wb_review_state_changed_by_agent": False, "wb_left_for_marketplace_review": True,
             "local_source_pdf_deleted": False,
             "limitation": "All 29 source-matched offers passed fresh scope checks on both platforms.",
             "verification_artifacts": [PREFLIGHT.name, STATE.name, READBACK.name]}
    add.setdefault("post_snapshot_writes", []).append(entry)
    artifacts = add.setdefault("verification_artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["arlight_49351_readback"] = str(READBACK)
    elif isinstance(artifacts, list):
        artifacts.append(str(READBACK))
    else:
        raise RuntimeError("unsupported_addendum_verification_artifacts_format")
    add["checked_at_utc"] = now()
    add["complete"] = False
    add["local_source_pdfs_deleted"] = False
    save(ADDENDUM, add)
    print(json.dumps({"execution": str(STATE), "readback": str(READBACK),
                      "phase": state["phase"], "readback": {
                          "ozon": {k: delayed_ozon.get(k) for k in ("certificate_id", "record_status", "expected", "exact_visible", "status_counts")},
                          "wb": {"expected": len(wb_targets), "exact": wb_exact, "valid": wb_valid,
                                 "pending_or_unverified": wb_exact-wb_valid}},
                      "local_source_file_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
