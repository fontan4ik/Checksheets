#!/usr/bin/env python3
"""Attach verified Arlight declarations 71655/26 and 33370/26 to safe live targets."""
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
PREFLIGHT = HERE / "arlight_71655_33370_live_preflight_20261022.json"
STATE = HERE / "arlight_71655_33370_execution_20261022.json"
BEFORE = HERE / "arlight_71655_33370_wb_before_20261022.json"
READBACK = HERE / "arlight_71655_33370_final_crossplatform_readback_20261022.json"
JOURNAL = HERE / "arlight_71655_33370_mutation_journal_20261022.jsonl"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
TNVED = "8537109800"
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
            raise RuntimeError("ozon_fresh_identity_incomplete:" + offer)
        product, attr = pmap[offer][0], amap[offer][0]
        product_id = str(product.get("id") or product.get("product_id") or "")
        sku = str(product.get("sku") or "")
        values = {str(x.get("id")): [str(v.get("value") or "").strip()
                  for v in x.get("values") or [] if str(v.get("value") or "").strip()]
                  for x in attr.get("attributes") or []}
        brand = values.get("85", [])
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in values.get("22232", [])})
        if product_id != str(target["product_id"]) or sku != str(target["sku"]):
            raise RuntimeError("ozon_product_identity_changed:" + offer)
        if product.get("is_archived") is not False or brand != ["Arlight"] or tnved != [TNVED]:
            raise RuntimeError("ozon_live_scope_changed:" + offer)
        out.append({**target, "product_id": product_id, "sku": sku,
                    "live_name": product.get("name"), "brand_values": brand, "tnved_codes": tnved})
    return out


def get_or_create_record(client: Client, doc: dict, seed_sku: str) -> tuple[dict | None, dict]:
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_document_records:" + doc["number"])
    if matches:
        record = matches[0]
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != doc["issue_date"]
                or str(record.get("expire_date") or "")[:10] != doc["expire_date"]):
            raise RuntimeError("ozon_record_metadata_conflict:" + doc["number"])
        if record.get("status_code") not in {"approved", "under_review"}:
            raise RuntimeError("ozon_record_not_usable:" + str(record.get("status_code")))
        return record, {"created": False, "record_already_present": True}

    source = ROOT / doc["source_pdf"]
    expiry = datetime.date.fromisoformat(doc["expire_date"])
    params = {
        "name": "Декларация о соответствии № " + doc["number"],
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": doc["number"],
        "issue_date": wb_datetime(doc["issue_date"]),
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku],
        "product_type": "UNKNOWN",
        "link_to_registry": f"https://pub.fsa.gov.ru/rds/declaration/view/{doc['record_id']}/common",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"),
                   "name": source.name}],
    }
    payload = {"params": params}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_create_payload_too_large")
    journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
             "document_number": doc["number"], "phase": "prepared", "seed_sku": seed_sku,
             "request_sha256": hashlib.sha256(encoded).hexdigest(), "request_bytes": len(encoded)})
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        error_type = None
    except Exception as exc:
        response, error_type = None, type(exc).__name__
    journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
             "document_number": doc["number"], "phase": "response" if response is not None else "uncertain",
             "response": response, "error_type": error_type})

    found = []
    for attempt in range(6):
        found = [x for x in list_certificates(client)
                 if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if found or attempt == 5:
            break
        time.sleep(2)
    if len(found) != 1:
        return None, {"created": bool(response and response.get("certificate_id")),
                      "outcome": "uncertain_no_record_visible_no_retry", "error_type": error_type,
                      "create_response": response}
    record = found[0]
    if (record.get("type_code") != "declaration"
            or str(record.get("issue_date") or "")[:10] != doc["issue_date"]
            or str(record.get("expire_date") or "")[:10] != doc["expire_date"]):
        raise RuntimeError("ozon_created_record_metadata_conflict:" + doc["number"])
    states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
    if response is None or response.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        return record, {"created": True, "outcome": "record_visible_but_create_response_not_fully_validated",
                        "create_response": response, "error_type": error_type}
    return record, {"created": True, "outcome": "record_created_and_validated", "create_response": response}


def bind_ozon(client: Client, doc: dict, record: dict, targets: list[dict]) -> dict:
    existing = client.ozon_bindings(int(record["certificate_id"]))
    expected = {(str(x["product_id"]), str(x["sku"])) for x in targets}
    by_product = collections.defaultdict(list)
    for row in existing:
        by_product[str(row.get("product_id") or "")].append(row)
    missing_skus = []
    for target in targets:
        rows = by_product.get(str(target["product_id"]), [])
        if len(rows) > 1:
            raise RuntimeError("ozon_duplicate_product_bindings:" + target["offer_id"])
        if not rows:
            missing_skus.append(str(target["sku"]))
            continue
        row = rows[0]
        if str(row.get("sku") or "") != str(target["sku"]):
            raise RuntimeError("ozon_binding_sku_conflict:" + target["offer_id"])
        if row.get("product_status_code") == "declined":
            raise RuntimeError("ozon_binding_declined:" + target["offer_id"])
    if missing_skus:
        request = {"certificate_id": int(record["certificate_id"]), "skus": missing_skus}
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "document_number": doc["number"], "phase": "prepared", "sku_count": len(missing_skus),
                 "request_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest()})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            error_type = None
        except Exception as exc:
            response, error_type = None, type(exc).__name__
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "document_number": doc["number"], "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": error_type})

    live = client.ozon_bindings(int(record["certificate_id"]))
    live_by_pair = collections.defaultdict(list)
    for row in live:
        pair = (str(row.get("product_id") or ""), str(row.get("sku") or ""))
        live_by_pair[pair].append(row)
    bindings = []
    for target in targets:
        pair = (str(target["product_id"]), str(target["sku"]))
        rows = live_by_pair.get(pair, [])
        bindings.append({"offer_id": target["offer_id"], "product_id": pair[0], "sku": pair[1],
                         "visible": len(rows) == 1,
                         "status": rows[0].get("product_status_code") if len(rows) == 1 else None})
    record_info = client.call("ozon", "/v1/product/certificate/info",
                              {"certificate_number": doc["number"]}).get("result") or {}
    return {"certificate_id": str(record["certificate_id"]), "record_status": record_info.get("status_code"),
            "record_info": {k: record_info.get(k) for k in ("certificate_number", "type_code", "status_code",
                                                              "issue_date", "expire_date", "products_count")},
            "expected_bindings": len(expected), "visible_exact_bindings": sum(x["visible"] for x in bindings),
            "binding_status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in bindings)),
            "missing_or_conflicting": [x for x in bindings if not x["visible"]], "bindings": bindings}


def attach_wb(client: Client, pre: dict, selected_docs: list[dict]) -> dict:
    offer_doc = {}
    for doc in selected_docs:
        for target in doc["wb_targets"]:
            if not target["eligible"]:
                continue
            if target["offer_id"] in offer_doc:
                raise RuntimeError("overlapping_wb_targets:" + target["offer_id"])
            offer_doc[target["offer_id"]] = doc
    before_rows = []
    updates = []
    for index, (offer, doc) in enumerate(sorted(offer_doc.items()), 1):
        prior = next(x for x in doc["wb_targets"] if x["offer_id"] == offer)
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            raise RuntimeError("wb_live_card_count_changed:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(prior["nmID"])
                or str(card.get("vendorCode") or "") != offer
                or str(card.get("brand") or "").casefold() != "arlight"):
            raise RuntimeError("wb_live_identity_changed:" + offer)
        docs = copy_documents(card)
        tnved = []
        for char in card.get("characteristics") or []:
            label = "".join(str(char.get("name") or "").casefold().split()).replace("ё", "е")
            if "тнвэд" in label or "тнвед" in label:
                raw = char.get("value")
                tnved.extend(raw if isinstance(raw, list) else [raw])
        tnved = sorted({str(x).split(" - ", 1)[0].strip() for x in tnved if str(x).strip()})
        if tnved != [TNVED]:
            raise RuntimeError("wb_tnved_changed_since_preflight:" + offer)
        if (card.get("documents") or {}).get("excludeDocuments") is True:
            raise RuntimeError("wb_documents_excluded_since_preflight:" + offer)
        wanted = {"type": 2, "number": doc["number"],
                  "startDate": wb_datetime(doc["issue_date"]),
                  "endDate": wb_datetime(doc["expire_date"]), "isEndless": False}
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(wanted["number"])]
        exact = [x for x in same if int(x.get("type") or 0) == 2
                 and str(x.get("startDate") or "")[:10] == doc["issue_date"]
                 and str(x.get("endDate") or "")[:10] == doc["expire_date"]]
        if same and len(exact) != 1:
            raise RuntimeError("wb_number_conflicts_since_preflight:" + offer)
        payload = runner.merge_wb(card, [wanted])
        before_rows.append({"offer_id": offer, "nmID": str(card["nmID"]), "document_number": doc["number"],
                            "card": card, "prior_documents": docs, "already_exact": payload is None})
        if payload is not None:
            updates.append({"offer_id": offer, "nmID": str(card["nmID"]),
                            "document_number": doc["number"], "payload": payload,
                            "before": card, "prior_documents": docs})
        if index % 15 == 0 or index == len(offer_doc):
            print(json.dumps({"wb_fresh_preflight_cards": index, "total": len(offer_doc)}, ensure_ascii=False), flush=True)
    save(BEFORE, {"checked_at_utc": now(), "complete": True, "target_cards": len(before_rows),
                  "updates": len(updates), "already_exact": len(before_rows) - len(updates),
                  "cards": before_rows})
    if updates:
        payloads = [x["payload"] for x in updates]
        marker = hashlib.sha256(json.dumps(payloads, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "prepared", "cards": len(updates), "offers": [x["offer_id"] for x in updates],
                 "request_sha256": marker})
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
            error_type = None
        except Exception as exc:
            response, error_type = None, type(exc).__name__
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": error_type})
    else:
        response, error_type = None, None

    before_by_offer = {x["offer_id"]: x for x in before_rows}
    readbacks = []
    failures = []
    for index, (offer, doc) in enumerate(sorted(offer_doc.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            failures.append({"offer_id": offer, "problem": "readback_card_count", "count": len(cards)})
            continue
        card = cards[0]
        items = ((card.get("documents") or {}).get("items") or [])
        matches = [x for x in items if norm_number(x.get("number")) == norm_number(doc["number"])
                   and int(x.get("type") or 0) == 2
                   and str(x.get("startDate") or "")[:10] == doc["issue_date"]
                   and str(x.get("endDate") or "")[:10] == doc["expire_date"]
                   and x.get("isEndless") is False]
        before = before_by_offer[offer]
        old_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10],
                           str(x.get("endDate") or "")[:10], x.get("isEndless"))
                          for x in before["prior_documents"]]
        after_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10],
                             str(x.get("endDate") or "")[:10], x.get("isEndless")) for x in items]
        old_docs_preserved = all(signature in after_signatures for signature in old_signatures)
        other_fields_preserved = comparable_card(card) == comparable_card(before["card"])
        verdict = matches[0].get("verdict") if len(matches) == 1 else None
        valid = (isinstance(verdict, dict) and verdict.get("verified") is True
                 and verdict.get("status") == 1 and verdict.get("reason") == "valid")
        row = {"offer_id": offer, "nmID": str(card.get("nmID") or ""),
               "document_number": doc["number"], "exact_metadata_count": len(matches),
               "prior_documents_preserved": old_docs_preserved,
               "unrelated_card_fields_preserved": other_fields_preserved,
               "verdict": verdict, "marketplace_valid": valid,
               "left_for_marketplace_review": not valid}
        readbacks.append(row)
        if len(matches) != 1 or not old_docs_preserved or not other_fields_preserved:
            failures.append({"offer_id": offer, "problem": "document_or_preservation_readback_failed",
                             "exact_metadata_count": len(matches),
                             "prior_documents_preserved": old_docs_preserved,
                             "unrelated_card_fields_preserved": other_fields_preserved})
        if index % 15 == 0 or index == len(offer_doc):
            print(json.dumps({"wb_readbacks": index, "total": len(offer_doc)}, ensure_ascii=False), flush=True)
    return {"target_cards": len(offer_doc), "updates_sent": len(updates),
            "response": response, "error_type": error_type,
            "exact_metadata_cards": sum(x["exact_metadata_count"] == 1 for x in readbacks),
            "valid_verdict_cards": sum(x["marketplace_valid"] for x in readbacks),
            "pending_or_unverified_cards": sum(x["exact_metadata_count"] == 1 and not x["marketplace_valid"] for x in readbacks),
            "readback_count": len(readbacks), "failures": failures, "cards": readbacks,
            "review_state_changed_by_agent": False, "left_for_marketplace_review": True}


def main() -> None:
    for path in (STATE, BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or len(pre.get("documents") or []) != 2:
        raise RuntimeError("preflight_missing_or_not_read_only")
    docs = pre["documents"]
    if {x["number"] for x in docs} != {"ЕАЭС N RU Д-CN.РА01.В.71655/26", "ЕАЭС N RU Д-CN.РА03.В.33370/26"}:
        raise RuntimeError("preflight_document_set_changed")
    for doc in docs:
        # The read-only preflight stores the FSA identifier under this explicit key.
        # Normalize it for the execution helpers below before constructing registry URLs.
        doc["record_id"] = str(doc["official_registry_id"])
        path = ROOT / doc["source_pdf"]
        if (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != doc["source_sha256"]):
            raise RuntimeError("source_pdf_missing_or_changed:" + doc["number"])
    ozon_targets = {doc["number"]: [x for x in doc["ozon_targets"] if x.get("eligible") is True] for doc in docs}
    wb_targets = {doc["number"]: [x for x in doc["wb_targets"] if x.get("eligible") is True] for doc in docs}
    if sum(map(len, ozon_targets.values())) != int(pre["summary"]["ozon_eligible_pairs"]):
        raise RuntimeError("preflight_ozon_eligible_count_conflict")
    if sum(map(len, wb_targets.values())) != int(pre["summary"]["wb_eligible_pairs"]):
        raise RuntimeError("preflight_wb_eligible_count_conflict")
    seen_wb = [x["offer_id"] for rows in wb_targets.values() for x in rows]
    if len(seen_wb) != len(set(seen_wb)):
        raise RuntimeError("overlapping_document_targets_on_wb")

    client = Client()
    state = {"started_at_utc": now(), "phase": "fresh_preflight", "documents": {},
             "ozon_target_pairs": sum(map(len, ozon_targets.values())),
             "wb_target_pairs": sum(map(len, wb_targets.values())),
             "source_hashes_verified": True, "wb_review_state_changed_by_agent": False,
             "wb_left_for_marketplace_review": True, "local_source_files_deleted": False}
    save(STATE, state)

    # Freshly recheck every safe Ozon target immediately before document creation/binding.
    for doc in docs:
        targets = ozon_targets[doc["number"]]
        if not targets:
            state["documents"][doc["number"]] = {"phase": "no_safe_ozon_targets"}
            save(STATE, state)
            continue
        fresh = fresh_ozon(client, targets)
        try:
            record, creation = get_or_create_record(client, doc, fresh[0]["sku"])
            if record is None:
                state["documents"][doc["number"]] = {"phase": "uncertain_no_record_no_retry", "creation": creation}
                save(STATE, state)
                continue
            if creation.get("outcome") == "record_visible_but_create_response_not_fully_validated":
                state["documents"][doc["number"]] = {"phase": "create_response_unvalidated_no_binding",
                                                       "record": record, "creation": creation}
                save(STATE, state)
                continue
            binding = bind_ozon(client, doc, record, fresh)
            state["documents"][doc["number"]] = {"phase": "ozon_binding_readback_complete",
                                                   "record": record, "creation": creation,
                                                   "binding": binding, "fresh_targets": fresh}
            save(STATE, state)
            print(json.dumps({"ozon_document": doc["number"],
                              "certificate_id": binding["certificate_id"],
                              "visible": binding["visible_exact_bindings"],
                              "expected": binding["expected_bindings"],
                              "statuses": binding["binding_status_counts"]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            state["documents"][doc["number"]] = {"phase": "ozon_processing_error",
                                                   "error_type": type(exc).__name__, "detail": str(exc)[:400]}
            save(STATE, state)

    # WB is updated only on the fresh safe-card subset; existing document rows and card fields are preserved.
    wb_result = attach_wb(client, pre, docs)
    state["wb_initial_readback"] = {k: v for k, v in wb_result.items() if k != "cards"}
    state["phase"] = "marketplace_writes_sent"
    save(STATE, state)

    # Give Ozon background checks a short period to settle, then reconcile exact pairs again.
    time.sleep(60)
    delayed_ozon = {}
    for doc in docs:
        dstate = state["documents"].get(doc["number"], {})
        record = dstate.get("record")
        targets = ozon_targets[doc["number"]]
        if not record or not targets:
            delayed_ozon[doc["number"]] = {"readback_complete": False, "reason": dstate.get("phase")}
            continue
        live = client.ozon_bindings(int(record["certificate_id"]))
        pairs = collections.defaultdict(list)
        for row in live:
            pairs[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
        target_rows = []
        for target in targets:
            rows = pairs.get((str(target["product_id"]), str(target["sku"])), [])
            target_rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                                "sku": target["sku"], "visible_exact": len(rows) == 1,
                                "status": rows[0].get("product_status_code") if len(rows) == 1 else None})
        info = client.call("ozon", "/v1/product/certificate/info",
                           {"certificate_number": doc["number"]}).get("result") or {}
        delayed_ozon[doc["number"]] = {"certificate_id": str(record["certificate_id"]),
                                        "record_status": info.get("status_code"),
                                        "expected_bindings": len(target_rows),
                                        "visible_exact_bindings": sum(x["visible_exact"] for x in target_rows),
                                        "binding_status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in target_rows)),
                                        "bindings": target_rows}
    wb_final = attach_wb(client, pre, docs) if False else wb_result
    # The first call already did an exact full readback; avoid another write. Do a read-only delayed WB check.
    delayed_wb = []
    wb_offer_doc = {x["offer_id"]: doc for doc in docs for x in doc["wb_targets"] if x.get("eligible") is True}
    for index, (offer, doc) in enumerate(sorted(wb_offer_doc.items()), 1):
        cards = client.wb_cards(offer)
        if len(cards) != 1:
            delayed_wb.append({"offer_id": offer, "nmID": None, "exact_metadata": False,
                               "verdict": None, "error": "readback_card_count"})
            continue
        card = cards[0]
        rows = [x for x in ((card.get("documents") or {}).get("items") or [])
                if norm_number(x.get("number")) == norm_number(doc["number"])
                and int(x.get("type") or 0) == 2
                and str(x.get("startDate") or "")[:10] == doc["issue_date"]
                and str(x.get("endDate") or "")[:10] == doc["expire_date"]
                and x.get("isEndless") is False]
        delayed_wb.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                           "exact_metadata": len(rows) == 1,
                           "verdict": rows[0].get("verdict") if len(rows) == 1 else None})
        if index % 15 == 0 or index == len(wb_offer_doc):
            print(json.dumps({"wb_delayed_readbacks": index, "total": len(wb_offer_doc)}, ensure_ascii=False), flush=True)

    crossplatform = {"checked_at_utc": now(), "read_only_delayed_reconciliation": True,
                     "documents": [], "wb_review_state_changed_by_agent": False,
                     "wb_left_for_marketplace_review": True, "local_source_files_deleted": False}
    for doc in docs:
        o = delayed_ozon.get(doc["number"], {})
        w = [x for x in delayed_wb if wb_offer_doc.get(x["offer_id"], {}).get("number") == doc["number"]]
        expected_o = len(ozon_targets[doc["number"]])
        expected_w = len(wb_targets[doc["number"]])
        ozon_statuses = o.get("binding_status_counts") or {}
        row = {"brand": "Arlight", "document_number": doc["number"], "type": "declaration",
               "fsa_record_id": doc["record_id"], "fsa_status": "active",
               "issue_date": doc["issue_date"], "expire_date": doc["expire_date"],
               "source_sha256": doc["source_sha256"], "ozon_certificate_id": o.get("certificate_id"),
               "ozon_record_status": o.get("record_status"), "ozon_expected_bindings": expected_o,
               "ozon_exact_bindings": o.get("visible_exact_bindings", 0),
               "ozon_binding_status_counts": ozon_statuses,
               "wb_expected_cards": expected_w,
               "wb_exact_cards": sum(x.get("exact_metadata") is True for x in w),
               "wb_valid_cards": sum(isinstance(x.get("verdict"), dict)
                                     and x["verdict"].get("verified") is True
                                     and x["verdict"].get("status") == 1
                                     and x["verdict"].get("reason") == "valid" for x in w),
               "wb_pending_or_unverified_cards": sum(x.get("exact_metadata") is True and not (
                   isinstance(x.get("verdict"), dict) and x["verdict"].get("verified") is True
                   and x["verdict"].get("status") == 1 and x["verdict"].get("reason") == "valid") for x in w),
               "wb_review_left_pending": True, "local_source_file_deleted": False,
               "verification_artifacts": [PREFLIGHT.name, STATE.name, READBACK.name]}
        crossplatform["documents"].append(row)
    crossplatform["totals"] = {
        "ozon_expected_bindings": sum(len(v) for v in ozon_targets.values()),
        "ozon_exact_bindings": sum(x.get("ozon_exact_bindings", 0) for x in crossplatform["documents"]),
        "ozon_approved_bindings": sum(sum(1 for target in delayed_ozon.get(x["number"], {}).get("bindings", [])
                                          if target.get("status") == "approved") for x in docs),
        "wb_expected_cards": sum(len(v) for v in wb_targets.values()),
        "wb_exact_cards": sum(x.get("wb_exact_cards", 0) for x in crossplatform["documents"]),
        "wb_valid_cards": sum(x.get("wb_valid_cards", 0) for x in crossplatform["documents"]),
        "wb_pending_or_unverified_cards": sum(x.get("wb_pending_or_unverified_cards", 0) for x in crossplatform["documents"]),
    }
    crossplatform["ozon_bindings"] = delayed_ozon
    crossplatform["wb_cards"] = delayed_wb
    save(READBACK, crossplatform)
    state["ozon_delayed_readback"] = {number: {k: v for k, v in value.items() if k != "bindings"}
                                       for number, value in delayed_ozon.items()}
    state["wb_delayed_readback"] = {"cards": len(delayed_wb),
                                    "exact_metadata_cards": sum(x.get("exact_metadata") is True for x in delayed_wb),
                                    "valid_cards": crossplatform["totals"]["wb_valid_cards"],
                                    "pending_or_unverified_cards": crossplatform["totals"]["wb_pending_or_unverified_cards"]}
    state["phase"] = "delayed_readback_complete"
    state["finished_at_utc"] = now()
    save(STATE, state)

    # Persist incremental evidence without pretending the marketplace-wide audit is complete.
    addendum = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    existing_numbers = {norm_number(x.get("document_number")) for x in addendum.get("post_snapshot_writes", [])}
    for row in crossplatform["documents"]:
        if norm_number(row["document_number"]) in existing_numbers:
            raise RuntimeError("addendum_already_contains_document:" + row["document_number"])
        entry = {"brand": row["brand"], "document_number": row["document_number"], "type": "declaration",
                 "ozon_certificate_id": row["ozon_certificate_id"], "ozon_record_status": row["ozon_record_status"],
                 "ozon_exact_bindings": row["ozon_exact_bindings"],
                 "ozon_binding_status_counts": row["ozon_binding_status_counts"],
                 "wb_exact_cards": row["wb_exact_cards"], "wb_valid_cards": row["wb_valid_cards"],
                 "wb_pending_or_unverified_cards": row["wb_pending_or_unverified_cards"],
                 "wb_review_state_changed_by_agent": False, "wb_left_for_marketplace_review": True,
                 "local_source_pdf_deleted": False,
                 "fsa_record_id": row["fsa_record_id"], "fsa_status": row["fsa_status"],
                 "verification_artifacts": [PREFLIGHT.name, STATE.name, READBACK.name]}
        addendum.setdefault("post_snapshot_writes", []).append(entry)
        verification_artifacts = addendum.setdefault("verification_artifacts", {})
        if isinstance(verification_artifacts, dict):
            key = "arlight_" + norm_number(row["document_number"]).replace(" ", "_") + "_readback"
            verification_artifacts[key] = str(READBACK)
        elif isinstance(verification_artifacts, list):
            verification_artifacts.append(str(READBACK))
        else:
            raise RuntimeError("unsupported_addendum_verification_artifacts_format")
    addendum["checked_at_utc"] = now()
    addendum["complete"] = False
    addendum["local_source_pdfs_deleted"] = False
    save(ADDENDUM, addendum)
    print(json.dumps({"execution": str(STATE), "readback": str(READBACK),
                      "phase": state["phase"], "totals": crossplatform["totals"],
                      "documents": crossplatform["documents"],
                      "local_source_files_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
