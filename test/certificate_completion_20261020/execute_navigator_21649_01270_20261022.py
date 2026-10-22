#!/usr/bin/env python3
"""Upload the two verified Navigator NI documents and bind their exact targets."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card,
    copy_documents,
    doc_key,
    norm_number,
    wb_datetime,
)

PREFLIGHT = HERE / "navigator_21649_01270_live_preflight_20261022.json"
STATE = HERE / "navigator_21649_01270_execution_20261022.json"
BEFORE = HERE / "navigator_21649_01270_wb_before_20261022.json"
READBACK = HERE / "navigator_21649_01270_final_crossplatform_readback_20261022.json"
JOURNAL = HERE / "navigator_21649_01270_mutation_journal_20261022.jsonl"

DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА07.В.21649/22",
        "type_code": "declaration",
        "wb_type": 2,
        "issue_date": "2022-10-07",
        "expire_date": "2027-10-06",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_61203_54241efe4dfe.pdf",
        "sha256": "54241efe4dfe5a2f99da7f73874bf911c9f0a4035a761621d21ad02fa8f96dbf",
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/17096314/common",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.АД47.В.01270/24",
        "type_code": "certificate_of_conformity",
        "wb_type": 1,
        "issue_date": "2024-09-05",
        "expire_date": "2029-09-04",
        "file": ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_61203_ea2971514733.pdf",
        "sha256": "ea29715147336b29e3401bd86253c7e54c3e7e32a65560ba2c8379c1aebbca45",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3491666/baseInfo",
    },
}
EXPECTED_OZON_TNVED = ["8539213009"]
EXPECTED_WB_TNVED = ["8539520009"]


def save(path: pathlib.Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def code_values(values: list[object]) -> list[str]:
    return sorted({str(value).split(" - ", 1)[0].strip() for value in values if str(value).strip()})


def attr_values(row: dict, ident: str) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip() for v in (attrs.get(ident) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return code_values(values)


def list_certificates(client: Client) -> list[dict]:
    all_rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        all_rows.extend(rows)
        if not rows or page >= int(result.get("page_count") or 0):
            return all_rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def fetch_fresh_ozon(client: Client, pre: dict) -> list[dict]:
    targets = pre["ozon_targets"]
    offers = [str(x["offer_id"]) for x in targets]
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    pmap: dict[str, list[dict]] = collections.defaultdict(list)
    amap: dict[str, list[dict]] = collections.defaultdict(list)
    for row in products:
        pmap[str(row.get("offer_id"))].append(row)
    for row in attrs:
        amap[str(row.get("offer_id"))].append(row)
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("fresh_ozon_target_set_incomplete")
    fresh = []
    for target in targets:
        offer = str(target["offer_id"])
        if len(pmap[offer]) != 1 or len(amap[offer]) != 1:
            raise RuntimeError("fresh_ozon_identity_not_unique:" + offer)
        product, attr = pmap[offer][0], amap[offer][0]
        product_id, sku = str(product.get("product_id") or product.get("id")), str(product.get("sku"))
        brand = attr_values(attr, "85")
        tnved = code_values(attr_values(attr, "22232"))
        if (product.get("is_archived") is not False
                or product_id != str(target["product_id"])
                or sku != str(target["sku"])
                or brand != ["Navigator"]
                or target["offer_id"].split("-", 1)[0] not in "".join(ch for ch in str(product.get("name") or "") if ch.isalnum())
                or tnved != EXPECTED_OZON_TNVED):
            raise RuntimeError("fresh_ozon_identity_or_classification_changed:" + offer)
        fresh.append({"offer_id": offer, "product_id": product_id, "sku": sku,
                      "name": product.get("name"), "brand_values": brand, "tnved": tnved})
    return fresh


def ensure_ozon_record(client: Client, doc: dict, seed_sku: str) -> tuple[dict | None, dict]:
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
    if len(matches) > 1:
        raise RuntimeError("ozon_duplicate_document_records:" + doc["number"])
    if matches:
        record = matches[0]
        if (record.get("type_code") != doc["type_code"]
                or str(record.get("issue_date") or "")[:10] != doc["issue_date"]
                or str(record.get("expire_date") or "")[:10] != doc["expire_date"]):
            raise RuntimeError("ozon_existing_record_metadata_conflict:" + doc["number"])
        return record, {"created": False, "already_present": True}

    year, month, day = map(int, doc["expire_date"].split("-"))
    params = {
        "name": "Документ " + doc["number"],
        "certificate_type": doc["type_code"].upper(),
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": doc["number"],
        "issue_date": wb_datetime(doc["issue_date"]),
        "expired_date": {"date": {"day": day, "month": month, "year": year}},
        "skus": [str(seed_sku)],
        "product_type": "UNKNOWN",
        "link_to_registry": doc["registry_url"],
        "files": [{"file_content": base64.b64encode(doc["file"].read_bytes()).decode("ascii"),
                   "name": doc["file"].name}],
    }
    payload = {"params": params}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_create_payload_too_large")
    journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
             "number": doc["number"], "phase": "prepared",
             "source_sha256": doc["sha256"], "payload_sha256": hashlib.sha256(encoded).hexdigest(),
             "payload_bytes": len(encoded), "seed_sku": str(seed_sku)})
    state = json.loads(STATE.read_text())
    state["phase"] = "ozon_create_in_progress"
    state["current_document"] = doc["number"]
    save(STATE, state)
    response = None
    error_type = None
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        error_type = type(exc).__name__
    journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
             "number": doc["number"], "phase": "response" if response is not None else "uncertain",
             "response": response, "error_type": error_type})
    for attempt in range(6):
        matches = [x for x in list_certificates(client)
                   if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if matches:
            break
        if attempt < 5:
            time.sleep(2)
    if len(matches) != 1:
        return None, {"created": bool(response and response.get("certificate_id")),
                      "outcome": "record_not_visible_no_retry", "error_type": error_type,
                      "create_response": response}
    record = matches[0]
    if (record.get("type_code") != doc["type_code"]
            or str(record.get("issue_date") or "")[:10] != doc["issue_date"]
            or str(record.get("expire_date") or "")[:10] != doc["expire_date"]):
        raise RuntimeError("ozon_created_record_metadata_conflict:" + doc["number"])
    states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
    fully_validated = response is not None and response.get("status") == "COMPLETED" and states and set(states) == {"VALID"}
    outcome = "record_visible" if fully_validated else "record_visible_create_not_fully_validated"
    return record, {"created": True, "outcome": outcome, "create_response": response}


def bind_ozon(client: Client, doc: dict, record: dict, targets: list[dict]) -> dict:
    record_status = str(record.get("status_code") or "")
    if record_status in {"declined", "rejected", "cancelled", "invalid"}:
        return {"certificate_id": record.get("certificate_id"), "record_status": record_status,
                "expected_bindings": len(targets), "visible_bindings": 0,
                "binding_status_counts": {}, "phase": "record_rejected_no_bind"}
    existing = client.ozon_bindings(int(record["certificate_id"]))
    expected = {(str(t["product_id"]), str(t["sku"])) for t in targets}
    by_product = {}
    for row in existing:
        product_id = str(row.get("product_id") or "")
        if not product_id or product_id in by_product:
            raise RuntimeError("ozon_binding_identity_duplicate:" + doc["number"])
        by_product[product_id] = row
    outside = [x for x in existing if (str(x.get("product_id")), str(x.get("sku"))) not in expected]
    if outside:
        raise RuntimeError("ozon_record_has_unexpected_bindings:" + doc["number"])
    missing = []
    for target in targets:
        prior = by_product.get(str(target["product_id"]))
        if prior and str(prior.get("sku")) != str(target["sku"]):
            raise RuntimeError("ozon_binding_sku_conflict:" + target["offer_id"])
        if prior and prior.get("product_status_code") == "declined":
            raise RuntimeError("ozon_binding_declined_before_write:" + target["offer_id"])
        if prior is None:
            missing.append(target)
    if missing:
        request = {"certificate_id": int(record["certificate_id"]),
                   "skus": sorted(str(x["sku"]) for x in missing)}
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "number": doc["number"], "phase": "prepared", "sku_count": len(missing),
                 "payload_sha256": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()})
        state = json.loads(STATE.read_text())
        state["phase"] = "ozon_bind_in_progress"
        state["current_document"] = doc["number"]
        save(STATE, state)
        response = None
        error_type = None
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
        except Exception as exc:
            error_type = type(exc).__name__
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "number": doc["number"], "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": error_type, "sku_count": len(missing)})

    live = client.ozon_bindings(int(record["certificate_id"]))
    pair_map: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for row in live:
        pair_map[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
    rows = []
    for target in targets:
        found = pair_map[(str(target["product_id"]), str(target["sku"]))]
        rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"], "sku": target["sku"],
                     "exact_binding_count": len(found),
                     "status": found[0].get("product_status_code") if len(found) == 1 else None})
    counts = collections.Counter(str(x["status"] or "unknown") for x in rows if x["exact_binding_count"] == 1)
    return {"certificate_id": int(record["certificate_id"]), "record_status": record.get("status_code"),
            "expected_bindings": len(targets), "visible_exact_bindings": sum(x["exact_binding_count"] == 1 for x in rows),
            "binding_status_counts": dict(counts), "unexpected_bindings": len([x for x in live if
                (str(x.get("product_id")), str(x.get("sku"))) not in expected]), "rows": rows}


def update_wb(client: Client, targets: list[dict]) -> dict:
    desired_docs = [{"type": doc["wb_type"], "number": doc["number"],
                     "startDate": wb_datetime(doc["issue_date"]),
                     "endDate": wb_datetime(doc["expire_date"]), "isEndless": False}
                    for doc in DOCS.values()]
    prepared, before = [], {}
    for target in targets:
        offer = str(target["offer_id"])
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("wb_card_count_changed:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(target["nmID"])
                or str(card.get("brand") or "").strip().casefold() != "navigator"
                or offer.split("-", 1)[0] not in "".join(ch for ch in str(card.get("title") or "") if ch.isalnum())
                or card_tnved(card) != EXPECTED_WB_TNVED):
            raise RuntimeError("wb_card_identity_or_classification_changed:" + offer)
        documents = copy_documents(card)
        signatures = [(doc_key(x), str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10],
                       bool(x.get("isEndless"))) for x in documents]
        additions = []
        for wanted in desired_docs:
            same = [x for x in documents if norm_number(x.get("number")) == norm_number(wanted["number"])]
            exact = [x for x in same if doc_key(x) == doc_key(wanted)
                     and str(x.get("startDate") or "")[:10] == wanted["startDate"][:10]
                     and str(x.get("endDate") or "")[:10] == wanted["endDate"][:10]
                     and x.get("isEndless") is False]
            if same and (len(same) != 1 or len(exact) != 1):
                raise RuntimeError("wb_document_metadata_conflict:" + offer + ":" + wanted["number"])
            if not exact:
                additions.append(wanted)
        payload = runner.merge_wb(card, additions) if additions else None
        before[offer] = {"card": card, "prior_signatures": signatures, "nmID": str(card["nmID"])}
        if payload is not None:
            prepared.append({"offer_id": offer, "nmID": str(card["nmID"]), "payload": payload})
    save(BEFORE, {"checked_at_utc": now(), "read_only": True, "target_cards": len(targets),
                  "update_count": len(prepared), "cards": before})
    update_response = None
    update_error = None
    if prepared:
        payloads = [x["payload"] for x in prepared]
        byte_count = len(json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode())
        if byte_count > 9_500_000:
            raise RuntimeError("wb_update_payload_too_large")
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "prepared", "target_cards": len(prepared), "payload_bytes": byte_count,
                 "payload_sha256": hashlib.sha256(json.dumps(payloads, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                 "offers": [x["offer_id"] for x in prepared]})
        state = json.loads(STATE.read_text())
        state["phase"] = "wb_update_in_progress"
        save(STATE, state)
        try:
            update_response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            update_error = type(exc).__name__
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "response" if update_response is not None else "uncertain",
                 "response": update_response, "error_type": update_error})
    rows, verdict_counts, failures = [], collections.Counter(), []
    for target in targets:
        offer = str(target["offer_id"])
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            failures.append({"offer_id": offer, "reason": "readback_card_count", "count": len(cards)})
            continue
        card = cards[0]
        documents = copy_documents(card)
        exact_docs = []
        for wanted in desired_docs:
            exact = [x for x in documents if norm_number(x.get("number")) == norm_number(wanted["number"])
                     and doc_key(x) == doc_key(wanted)
                     and str(x.get("startDate") or "")[:10] == wanted["startDate"][:10]
                     and str(x.get("endDate") or "")[:10] == wanted["endDate"][:10]
                     and x.get("isEndless") is False]
            if len(exact) != 1:
                failures.append({"offer_id": offer, "reason": "exact_document_missing_or_duplicate",
                                 "number": wanted["number"], "count": len(exact)})
            else:
                exact_docs.extend(exact)
                verdict = exact[0].get("verdict")
                label = "valid" if isinstance(verdict, dict) and verdict.get("verified") is True and verdict.get("reason") == "valid" else "pending_or_unverified"
                verdict_counts[label] += 1
        old = before[offer]
        current_signatures = [(doc_key(x), str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10],
                               bool(x.get("isEndless"))) for x in documents]
        prior_preserved = all(x in current_signatures for x in old["prior_signatures"])
        unrelated_preserved = comparable_card(card) == comparable_card(old["card"])
        if not prior_preserved or not unrelated_preserved:
            failures.append({"offer_id": offer, "reason": "existing_document_or_card_fields_changed"})
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "exact_documents": len(exact_docs), "prior_documents_preserved": prior_preserved,
                     "unrelated_card_fields_preserved": unrelated_preserved,
                     "verdicts": [x.get("verdict") for x in exact_docs]})
    result = {"checked_at_utc": now(), "target_cards": len(targets), "updated_cards": len(prepared),
              "cards_with_both_exact_documents": sum(x["exact_documents"] == 2 for x in rows),
              "wb_document_verdict_counts": dict(verdict_counts), "update_response": update_response,
              "update_error_type": update_error, "failures": failures, "cards": rows,
              "wb_left_for_marketplace_review": True}
    save(READBACK, result)
    return result


def main() -> None:
    for path in (STATE, BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_before_retry:" + path.name)
    pre = json.loads(PREFLIGHT.read_text())
    if (pre.get("read_only") is not True or pre.get("target_count") != 24
            or pre.get("ozon_target_summary", {}).get("eligible") != 24
            or pre.get("wb_target_summary", {}).get("eligible") != 24
            or pre.get("ozon_target_summary", {}).get("already_current_approved_baseline") != 0
            or pre.get("post_snapshot_write_overlap")
            or pre.get("ozon_target_summary", {}).get("tnved_mismatch_count") != 24
            or pre.get("wb_target_summary", {}).get("tnved_mismatch_count") != 24):
        raise RuntimeError("fresh_preflight_incomplete_or_conflicting")
    for doc in DOCS.values():
        if not doc["file"].is_file() or hashlib.sha256(doc["file"].read_bytes()).hexdigest() != doc["sha256"]:
            raise RuntimeError("source_pdf_hash_mismatch:" + doc["number"])
    ozon_targets = sorted(pre["ozon_targets"], key=lambda x: x["offer_id"])
    wb_targets = sorted(pre["wb_targets"], key=lambda x: x["offer_id"])
    if len(ozon_targets) != 24 or len(wb_targets) != 24:
        raise RuntimeError("target_set_incomplete")

    state = {"started_at_utc": now(), "phase": "prewrite_refresh",
             "target_count": 24, "documents": {},
             "ozon_marketplace_tnved": EXPECTED_OZON_TNVED,
             "wb_marketplace_tnved": EXPECTED_WB_TNVED,
             "fsa_tnved_codes": ["8539229000", "8539221000"],
             "marketplace_tnved_mismatch_acknowledged": True,
             "basis_for_proceeding": "Exact Navigator model/article match in the official provider table and exact FSA product scope; the marketplace TN VED values are recorded as a classification discrepancy and will be left to platform validation.",
             "wb_left_for_marketplace_review": True, "local_source_files_deleted": False}
    save(STATE, state)
    client = Client()

    fresh_ozon = fetch_fresh_ozon(client, pre)
    # Reconfirm exact cards and marketplace classification before any write.
    fresh_wb_targets = []
    for expected in wb_targets:
        offer = str(expected["offer_id"])
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_count_changed:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(expected["nmID"])
                or str(card.get("brand") or "").strip().casefold() != "navigator"
                or offer.split("-", 1)[0] not in "".join(ch for ch in str(card.get("title") or "") if ch.isalnum())
                or card_tnved(card) != EXPECTED_WB_TNVED):
            raise RuntimeError("fresh_wb_identity_or_classification_changed:" + offer)
        fresh_wb_targets.append(expected)
    state.update({"phase": "fresh_targets_verified", "ozon_fresh_targets": len(fresh_ozon),
                  "wb_fresh_cards": len(fresh_wb_targets), "ozon_products": [
                      {k: x[k] for k in ("offer_id", "product_id", "sku", "tnved")} for x in fresh_ozon],
                  "tnved_mismatch_values": {"ozon": EXPECTED_OZON_TNVED, "wb": EXPECTED_WB_TNVED}})
    save(STATE, state)

    for key, doc in DOCS.items():
        try:
            record, create = ensure_ozon_record(client, doc, fresh_ozon[0]["sku"])
            if record is None:
                state["documents"][key] = {"phase": "record_not_visible_no_retry", "create": create}
                save(STATE, state)
                continue
            if create.get("outcome") == "record_visible_create_not_fully_validated":
                state["documents"][key] = {"phase": "create_visible_not_validated_no_bind", "record": record, "create": create}
                save(STATE, state)
                continue
            binding = bind_ozon(client, doc, record, fresh_ozon)
            state["documents"][key] = {"phase": "ozon_bindings_read_back", "record": {
                k: record.get(k) for k in ("certificate_id", "certificate_number", "type_code", "status_code", "issue_date", "expire_date")},
                "create": create, "binding": {k: v for k, v in binding.items() if k != "rows"},
                "binding_rows": binding.get("rows"), "source_sha256": doc["sha256"]}
            save(STATE, state)
            print(json.dumps({"document": doc["number"], "record_status": binding.get("record_status"),
                              "visible_exact_bindings": binding.get("visible_exact_bindings"),
                              "binding_status_counts": binding.get("binding_status_counts")}, ensure_ascii=False), flush=True)
        except Exception as exc:
            state["documents"][key] = {"phase": "ozon_document_processing_error", "error_type": type(exc).__name__,
                                       "detail": str(exc)[:400]}
            save(STATE, state)

    state["phase"] = "ozon_complete_wb_starting"
    save(STATE, state)
    wb_result = update_wb(client, fresh_wb_targets)
    state["wb_readback"] = {k: v for k, v in wb_result.items() if k != "cards"}

    # Consolidated readback after both platform writes.
    final_docs = {}
    for key, doc in DOCS.items():
        matches = [x for x in list_certificates(client)
                   if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) != 1:
            final_docs[key] = {"record_count": len(matches), "exact_bindings": 0, "binding_status_counts": {}}
            continue
        record = matches[0]
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        expected_pairs = {(x["product_id"], x["sku"]) for x in fresh_ozon}
        actual_by_pair: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for row in bindings:
            actual_by_pair[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
        rows = []
        for target in fresh_ozon:
            found = actual_by_pair[(target["product_id"], target["sku"])]
            rows.append({"offer_id": target["offer_id"], "exact_count": len(found),
                         "status": found[0].get("product_status_code") if len(found) == 1 else None})
        final_docs[key] = {"certificate_id": record.get("certificate_id"), "record_status": record.get("status_code"),
                           "expected_bindings": len(fresh_ozon),
                           "exact_bindings": sum(x["exact_count"] == 1 for x in rows),
                           "binding_status_counts": dict(collections.Counter(str(x["status"] or "unknown") for x in rows if x["exact_count"] == 1)),
                           "unexpected_bindings": sum(1 for x in bindings if
                               (str(x.get("product_id")), str(x.get("sku"))) not in expected_pairs),
                           "rows": rows}
    complete_ozon = all(x.get("exact_bindings") == 24 and x.get("record_status") == "approved"
                        and x.get("binding_status_counts") == {"approved": 24}
                        for x in final_docs.values())
    complete_wb = wb_result.get("cards_with_both_exact_documents") == 24 and not wb_result.get("failures")
    result = {"checked_at_utc": now(), "read_only": True, "brand": "Navigator",
              "target_products": 24, "documents": final_docs, "ozon_all_documents_approved_exactly": complete_ozon,
              "wb": wb_result, "wb_exact_metadata_on_all_cards": complete_wb,
              "wb_left_for_marketplace_review": True,
              "ozon_marketplace_tnved": EXPECTED_OZON_TNVED,
              "wb_marketplace_tnved": EXPECTED_WB_TNVED,
              "fsa_tnved_codes": ["8539229000", "8539221000"],
              "classification_mismatch_documented": True, "local_source_files_deleted": False}
    save(READBACK, result)
    state.update({"phase": "cross_platform_readback_complete" if complete_ozon and complete_wb else "cross_platform_readback_incomplete",
                  "final_readback": {k: v for k, v in result.items() if k not in ("documents", "wb")},
                  "finished_at_utc": now(), "local_source_files_deleted": False})
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "ozon": {
        key: {k: v for k, v in value.items() if k != "rows"} for key, value in final_docs.items()},
        "wb": {k: v for k, v in wb_result.items() if k not in ("cards", "update_response")},
        "local_source_files_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
