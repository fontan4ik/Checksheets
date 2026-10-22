#!/usr/bin/env python3
"""Attach Gauss declaration 24108/24 to exact in-scope Ozon/WB targets."""
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
PREFLIGHT = HERE / "gauss_24108_crossplatform_preflight_20261022.json"
STATE = HERE / "gauss_24108_execution_20261022.json"
WB_BEFORE = HERE / "gauss_24108_wb_before_20261022.json"
READBACK = HERE / "gauss_24108_final_crossplatform_readback_20261022.json"
JOURNAL = HERE / "gauss_24108_mutation_journal_20261022.jsonl"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/3dbd3e80a412e4a3795dca08.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА10.В.24108/24"
REGISTRY_ID = "19574422"
ISSUE_DATE = "2024-11-06"
EXPIRE_DATE = "2029-11-05"
SOURCE_SHA256 = "2b2688113b066f45d6a961f3f81fa0da7fedf68515c878856164e87c42016969"
ALLOWED_TNVED = {"8539520001", "8539520003", "8539520009"}

sys.path.insert(0, str(PILOT))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    copy_documents, doc_key, norm_number, wb_datetime, comparable_card,
)


def save(path: pathlib.Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def list_certificates(client: Client) -> list[dict]:
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        rows = result.get("certificates")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        out.extend(rows)
        if not rows or page >= int(result.get("page_count") or 0):
            return out
    raise RuntimeError("ozon_certificate_page_limit")


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(ident)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def codes(values) -> list[str]:
    return sorted({str(x).split(" - ", 1)[0].strip() for x in values if str(x).strip()})


def card_tnved(card: dict) -> list[str]:
    values = []
    for item in card.get("characteristics") or []:
        label = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" in label or "тнвед" in label:
            raw = item.get("value")
            values.extend(raw if isinstance(raw, list) else [raw])
    return codes(values)


def fresh_ozon(client: Client, targets: list[dict]) -> tuple[list[dict], list[dict]]:
    offers = [str(x["offer_id"]) for x in targets]
    products, attrs = [], []
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        products.extend(client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or [])
        attrs.extend(client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result") or [])
    pm, am = collections.defaultdict(list), collections.defaultdict(list)
    for row in products:
        pm[str(row.get("offer_id") or "")].append(row)
    for row in attrs:
        am[str(row.get("offer_id") or "")].append(row)
    safe, skipped = [], []
    for target in targets:
        offer = str(target["offer_id"])
        issues = []
        if offer.rsplit("-", 1)[0] != str(target.get("article") or ""):
            skipped.append({"offer_id": offer, "reason": "article_scope_identity_changed"})
            continue
        if len(pm[offer]) != 1 or len(am[offer]) != 1:
            skipped.append({"offer_id": offer, "reason": "ozon_identity_not_unique"})
            continue
        product, attr = pm[offer][0], am[offer][0]
        pid, sku = str(product.get("id") or product.get("product_id") or ""), str(product.get("sku") or "")
        tnved = codes(attr_values(attr, 22232))
        if pid != str(target["product_id"]) or sku != str(target["sku"]):
            issues.append("ozon_product_identity_changed")
        if product.get("is_archived") is not False:
            issues.append("ozon_archived_or_unknown")
        if attr_values(attr, 85) != ["Gauss"]:
            issues.append("ozon_brand_changed")
        if not tnved or not set(tnved) <= ALLOWED_TNVED:
            issues.append("ozon_tnved_outside_fsa_scope")
        if issues:
            skipped.append({"offer_id": offer, "reason": issues})
        else:
            safe.append({**target, "product_id": pid, "sku": sku, "live_name": product.get("name"),
                         "tnved_codes": tnved})
    return safe, skipped


def fresh_wb_card(client: Client, target: dict) -> tuple[dict | None, list[str]]:
    offer = str(target["offer_id"])
    if offer.rsplit("-", 1)[0] != str(target.get("article") or ""):
        return None, ["article_scope_identity_changed"]
    cards = client.wb_cards(offer)
    if len(cards) != 1:
        return None, ["wb_exact_card_count_" + str(len(cards))]
    card = cards[0]
    issues = []
    if str(card.get("nmID") or "") != str(target["nmID"]):
        issues.append("wb_nmID_changed")
    if str(card.get("vendorCode") or "") != offer:
        issues.append("wb_vendor_code_changed")
    if str(card.get("brand") or "").strip().casefold() != "gauss":
        issues.append("wb_brand_changed")
    tnved = card_tnved(card)
    if not tnved or not set(tnved) <= ALLOWED_TNVED:
        issues.append("wb_tnved_outside_fsa_scope")
    if issues:
        return None, issues
    return card, []


def exact_wb_doc(items: list[dict]) -> list[dict]:
    return [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)
            and int(x.get("type") or 0) == 2
            and str(x.get("startDate") or "")[:10] == ISSUE_DATE
            and str(x.get("endDate") or "")[:10] == EXPIRE_DATE
            and x.get("isEndless") is False]


def bind_ozon(client: Client, record: dict, targets: list[dict]) -> dict:
    cert_id = int(record["certificate_id"])
    existing = client.ozon_bindings(cert_id)
    target_by_pid = {str(x["product_id"]): x for x in targets}
    by_pid = collections.defaultdict(list)
    for row in existing:
        by_pid[str(row.get("product_id") or "")].append(row)
    outside = [row for row in existing if str(row.get("product_id") or "") not in target_by_pid]
    if outside:
        raise RuntimeError("existing_ozon_record_has_out_of_assignment_bindings")
    missing = []
    for target in targets:
        rows = by_pid[str(target["product_id"])]
        if len(rows) > 1:
            raise RuntimeError("ozon_duplicate_binding:" + target["offer_id"])
        if rows and str(rows[0].get("sku") or "") != str(target["sku"]):
            raise RuntimeError("ozon_existing_binding_sku_conflict:" + target["offer_id"])
        if rows and rows[0].get("product_status_code") == "declined":
            raise RuntimeError("ozon_existing_binding_declined:" + target["offer_id"])
        if not rows:
            missing.append(target)
    if missing:
        request = {"certificate_id": cert_id, "skus": [str(x["sku"]) for x in missing]}
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "phase": "prepared", "number": NUMBER, "skus": request["skus"],
                 "payload_sha256": hashlib.sha256(json.dumps(request, separators=(",", ":")).encode()).hexdigest()})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            error_type = None
        except Exception as exc:
            response, error_type = None, type(exc).__name__
        journal({"at": now(), "platform": "ozon", "endpoint": "/v1/product/certificate/bind",
                 "phase": "response" if response is not None else "uncertain", "response": response,
                 "error_type": error_type, "number": NUMBER})
    else:
        response, error_type = {"result": True, "already_bound": True}, None
    current = client.ozon_bindings(cert_id)
    by_pair = collections.defaultdict(list)
    for row in current:
        by_pair[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
    rows = []
    for target in targets:
        pair = (str(target["product_id"]), str(target["sku"]))
        matches = by_pair[pair]
        rows.append({"offer_id": target["offer_id"], "product_id": pair[0], "sku": pair[1],
                     "exact": len(matches) == 1,
                     "status": matches[0].get("product_status_code") if len(matches) == 1 else None})
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}
    return {"certificate_id": str(cert_id), "record_status": info.get("status_code"),
            "expected": len(targets), "exact_visible": sum(x["exact"] for x in rows),
            "status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in rows)),
            "bindings": rows, "bind_response": response, "bind_error_type": error_type}


def attach_wb(client: Client, targets: list[dict]) -> dict:
    wanted = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE_DATE),
              "endDate": wb_datetime(EXPIRE_DATE), "isEndless": False}
    before, updates, skipped = [], [], []
    for i, target in enumerate(targets, 1):
        card, issues = fresh_wb_card(client, target)
        if card is None:
            skipped.append({"offer_id": target["offer_id"], "reason": issues})
            continue
        docs = copy_documents(card)
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = exact_wb_doc(docs)
        if same and (len(same) != 1 or len(exact) != 1):
            skipped.append({"offer_id": target["offer_id"], "reason": ["wb_same_number_metadata_conflict"]})
            continue
        payload = runner.merge_wb(card, [wanted])
        before.append({"offer_id": target["offer_id"], "nmID": str(card["nmID"]), "card": card,
                       "prior_documents": docs, "already_exact": payload is None})
        if payload is not None:
            updates.append({"offer_id": target["offer_id"], "nmID": str(card["nmID"]),
                            "payload": payload, "before": card, "prior_documents": docs})
        if i % 20 == 0 or i == len(targets):
            print(json.dumps({"wb_prewrite_cards": i, "total": len(targets)}, ensure_ascii=False), flush=True)
    save(WB_BEFORE, {"checked_at_utc": now(), "complete": True, "expected": len(targets),
                     "safe_cards": len(before), "updates": len(updates), "skipped": skipped, "cards": before})
    response, error_type = None, None
    if updates:
        payloads = [x["payload"] for x in updates]
        digest = hashlib.sha256(json.dumps(payloads, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "prepared", "number": NUMBER, "cards": len(updates),
                 "offers": [x["offer_id"] for x in updates], "payload_sha256": digest})
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
        except Exception as exc:
            error_type = type(exc).__name__
        journal({"at": now(), "platform": "wb", "endpoint": "/content/v2/cards/update",
                 "phase": "response" if response is not None else "uncertain", "number": NUMBER,
                 "response": response, "error_type": error_type})
    before_map = {x["offer_id"]: x for x in before}
    readbacks, failures = [], []
    for i, target in enumerate(targets, 1):
        card, issues = fresh_wb_card(client, target)
        if card is None:
            readbacks.append({"offer_id": target["offer_id"], "exact_metadata": False,
                              "failure": issues, "verdict": None})
            failures.append({"offer_id": target["offer_id"], "issue": issues})
            continue
        docs = copy_documents(card)
        found = exact_wb_doc(docs)
        prior = before_map.get(target["offer_id"])
        prior_signatures = {(doc_key(x), str(x.get("startDate") or "")[:10],
                             str(x.get("endDate") or "")[:10], x.get("isEndless"))
                            for x in (prior["prior_documents"] if prior else [])}
        live_signatures = {(doc_key(x), str(x.get("startDate") or "")[:10],
                            str(x.get("endDate") or "")[:10], x.get("isEndless")) for x in docs}
        old_preserved = prior is None or prior_signatures <= live_signatures
        ordinary_preserved = prior is None or comparable_card(card) == comparable_card(prior["card"])
        verdict = found[0].get("verdict") if len(found) == 1 else None
        row = {"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
               "exact_metadata": len(found) == 1, "prior_documents_preserved": old_preserved,
               "unrelated_card_fields_preserved": ordinary_preserved, "verdict": verdict}
        readbacks.append(row)
        if len(found) != 1 or not old_preserved or not ordinary_preserved:
            failures.append({"offer_id": target["offer_id"], "issue": "wb_readback_or_preservation_failed"})
        if i % 20 == 0 or i == len(targets):
            print(json.dumps({"wb_readbacks": i, "total": len(targets)}, ensure_ascii=False), flush=True)
    return {"expected": len(targets), "safe_cards": len(before), "updates_sent": len(updates),
            "skipped": skipped, "response": response, "error_type": error_type,
            "exact_metadata_cards": sum(x.get("exact_metadata") is True for x in readbacks),
            "valid_verdict_cards": sum(isinstance(x.get("verdict"), dict)
                and x["verdict"].get("verified") is True and x["verdict"].get("status") == 1
                and x["verdict"].get("reason") == "valid" for x in readbacks),
            "pending_or_unverified_cards": sum(x.get("exact_metadata") is True and not (
                isinstance(x.get("verdict"), dict) and x["verdict"].get("verified") is True
                and x["verdict"].get("status") == 1 and x["verdict"].get("reason") == "valid")
                for x in readbacks), "readback_count": len(readbacks), "failures": failures,
            "cards": readbacks, "review_state_changed_by_agent": False,
            "left_for_marketplace_review": True}


def main() -> None:
    for path in (STATE, WB_BEFORE, READBACK, JOURNAL):
        if path.exists():
            raise RuntimeError("execution_artifact_exists_reconcile_first:" + path.name)
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("document_number") != NUMBER:
        raise RuntimeError("preflight_missing_or_mismatched")
    if pre.get("confirmed_assignment_offers") != 63 or pre.get("fsa_article_count") != 24:
        raise RuntimeError("preflight_scope_count_changed")
    add_before = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    if any(x.get("document_number") == NUMBER for x in add_before.get("post_snapshot_writes", [])):
        raise RuntimeError("addendum_already_contains_document")
    if not SOURCE.is_file() or hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("source_pdf_hash_mismatch")
    ozon_targets = [x for x in pre["ozon_targets"] if x.get("eligible") is True]
    wb_targets = [x for x in pre["wb_targets"] if x.get("eligible") is True]
    state = {"started_at_utc": now(), "phase": "fresh_prewrite", "brand": "Gauss",
             "document_number": NUMBER, "fsa_registry_id": REGISTRY_ID,
             "confirmed_source_targets": pre.get("confirmed_assignment_offers"),
             "ozon_preflight_targets": len(ozon_targets), "wb_preflight_targets": len(wb_targets),
             "wb_review_state_changed_by_agent": False, "wb_left_for_marketplace_review": True,
             "local_source_pdf_deleted": False}
    save(STATE, state)
    client = Client()
    fresh, ozon_skipped = fresh_ozon(client, ozon_targets)

    # Recheck all WB cards before any marketplace write; only exact live matches remain targets.
    wb_fresh = []
    wb_skipped = []
    for target in wb_targets:
        card, issues = fresh_wb_card(client, target)
        if card is None:
            wb_skipped.append({"offer_id": target["offer_id"], "reason": issues})
        else:
            wb_fresh.append({**target, "nmID": str(card["nmID"])})
    records = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(records) > 1:
        raise RuntimeError("duplicate_ozon_records_for_document")
    record = records[0] if records else None
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE_DATE
                   or str(record.get("expire_date") or "")[:10] != EXPIRE_DATE
                   or record.get("status_code") not in {"approved", "under_review"}):
        raise RuntimeError("existing_ozon_record_metadata_or_status_conflict")

    creation = {"created": False, "record_reused": bool(record)}
    ozon_result = {"expected": len(fresh), "exact_visible": 0, "bindings": [], "status_counts": {},
                   "certificate_id": str(record["certificate_id"]) if record else None,
                   "record_status": record.get("status_code") if record else None}
    if fresh and record is None:
        if ozon_skipped:
            state["ozon_skipped_prewrite"] = ozon_skipped
        expiry = datetime.date.fromisoformat(EXPIRE_DATE)
        params = {"name": "Декларация о соответствии № " + NUMBER,
                  "certificate_type": "DECLARATION", "certificate_country": "RU",
                  "accordance_type": "EAEU", "number": NUMBER,
                  "issue_date": wb_datetime(ISSUE_DATE),
                  "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
                  "skus": [str(fresh[0]["sku"])], "product_type": "UNKNOWN",
                  "link_to_registry": f"https://pub.fsa.gov.ru/rds/declaration/view/{REGISTRY_ID}/common",
                  "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                             "name": SOURCE.name}]}
        body = {"params": params}
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) >= 15_000_000:
            raise RuntimeError("ozon_create_payload_too_large")
        journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
                 "phase": "prepared", "number": NUMBER, "seed_sku": fresh[0]["sku"],
                 "payload_bytes": len(encoded), "payload_sha256": hashlib.sha256(encoded).hexdigest()})
        try:
            response = client.call("ozon", "/v2/product/certificate/create", body, mutation=True)
            error_type = None
        except Exception as exc:
            response, error_type = None, type(exc).__name__
        journal({"at": now(), "platform": "ozon", "endpoint": "/v2/product/certificate/create",
                 "phase": "response" if response is not None else "uncertain",
                 "response": response, "error_type": error_type, "number": NUMBER})
        visible = []
        for attempt in range(7):
            visible = [x for x in list_certificates(client)
                       if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
            if visible or attempt == 6:
                break
            time.sleep(2)
        if len(visible) != 1:
            state.update({"phase": "ozon_create_uncertain_no_record_no_retry", "ozon_error_type": error_type})
            record = None
            creation = {"created": bool(response and response.get("certificate_id")),
                        "outcome": "uncertain_no_record_visible_no_retry", "error_type": error_type}
        else:
            record = visible[0]
            valid_params = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
            exact_metadata = (record.get("type_code") == "declaration"
                and str(record.get("issue_date") or "")[:10] == ISSUE_DATE
                and str(record.get("expire_date") or "")[:10] == EXPIRE_DATE)
            if not exact_metadata:
                raise RuntimeError("created_ozon_record_metadata_conflict")
            if response is None or response.get("status") != "COMPLETED" or not valid_params or set(valid_params) != {"VALID"}:
                creation = {"created": True, "outcome": "record_visible_but_create_response_not_validated",
                            "response": response, "error_type": error_type}
                record = None
            else:
                creation = {"created": True, "outcome": "created_and_validated", "response": response}

    if record is not None and fresh:
        ozon_result = bind_ozon(client, record, fresh)
        state["ozon_bindings_initial"] = {k: v for k, v in ozon_result.items() if k != "bindings"}
    state["ozon_creation"] = creation
    state["ozon_skipped_prewrite"] = ozon_skipped
    state["wb_skipped_prewrite"] = wb_skipped
    state["phase"] = "ozon_checked_wb_pending"
    save(STATE, state)

    wb_result = attach_wb(client, wb_fresh) if wb_fresh else {
        "expected": 0, "safe_cards": 0, "updates_sent": 0, "exact_metadata_cards": 0,
        "valid_verdict_cards": 0, "pending_or_unverified_cards": 0, "failures": [], "cards": [],
        "skipped": [], "review_state_changed_by_agent": False, "left_for_marketplace_review": True}
    wb_result["prewrite_skipped"] = wb_skipped
    state["wb_initial_readback"] = {k: v for k, v in wb_result.items() if k != "cards"}
    state["phase"] = "marketplace_writes_sent"
    save(STATE, state)

    time.sleep(60)
    delayed_ozon = {"expected": len(fresh), "exact_visible": 0, "bindings": [], "status_counts": {},
                    "certificate_id": None, "record_status": None}
    if record is not None and fresh:
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        by_pair = collections.defaultdict(list)
        for row in bindings:
            by_pair[(str(row.get("product_id") or ""), str(row.get("sku") or ""))].append(row)
        rows = []
        for target in fresh:
            found = by_pair[(str(target["product_id"]), str(target["sku"]))]
            rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                         "sku": target["sku"], "exact": len(found) == 1,
                         "status": found[0].get("product_status_code") if len(found) == 1 else None})
        info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result") or {}
        delayed_ozon = {"expected": len(rows), "exact_visible": sum(x["exact"] for x in rows),
                        "status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in rows)),
                        "bindings": rows, "certificate_id": str(record["certificate_id"]),
                        "record_status": info.get("status_code")}

    delayed_wb = []
    for i, target in enumerate(wb_fresh, 1):
        card, issues = fresh_wb_card(client, target)
        if card is None:
            delayed_wb.append({"offer_id": target["offer_id"], "exact_metadata": False,
                               "verdict": None, "error": issues})
            continue
        found = exact_wb_doc((card.get("documents") or {}).get("items") or [])
        delayed_wb.append({"offer_id": target["offer_id"], "nmID": str(card.get("nmID") or ""),
                           "exact_metadata": len(found) == 1,
                           "verdict": found[0].get("verdict") if len(found) == 1 else None})
        if i % 20 == 0 or i == len(wb_fresh):
            print(json.dumps({"wb_delayed_readbacks": i, "total": len(wb_fresh)}, ensure_ascii=False), flush=True)
    wb_valid = sum(isinstance(x.get("verdict"), dict) and x["verdict"].get("verified") is True
                   and x["verdict"].get("status") == 1 and x["verdict"].get("reason") == "valid"
                   for x in delayed_wb)
    wb_exact = sum(x.get("exact_metadata") is True for x in delayed_wb)
    cross = {"checked_at_utc": now(), "read_only_delayed_reconciliation": True,
             "brand": "Gauss", "document_number": NUMBER, "type": "declaration",
             "fsa_registry_id": REGISTRY_ID, "fsa_status": "active", "issue_date": ISSUE_DATE,
             "expire_date": EXPIRE_DATE, "source_sha256": SOURCE_SHA256,
             "ozon_certificate_id": delayed_ozon.get("certificate_id"),
             "ozon_record_status": delayed_ozon.get("record_status"),
             "ozon_expected_bindings": len(fresh), "ozon_exact_bindings": delayed_ozon.get("exact_visible", 0),
             "ozon_binding_status_counts": delayed_ozon.get("status_counts", {}),
             "ozon_skipped_out_of_scope": len(ozon_skipped),
             "wb_expected_cards": len(wb_fresh), "wb_exact_cards": wb_exact,
             "wb_valid_cards": wb_valid, "wb_pending_or_unverified_cards": wb_exact - wb_valid,
             "wb_skipped": wb_skipped, "wb_review_state_changed_by_agent": False,
             "wb_left_for_marketplace_review": True, "local_source_pdf_deleted": False,
             "verification_artifacts": [PREFLIGHT.name, STATE.name, READBACK.name],
             "ozon_bindings": delayed_ozon, "wb_cards": delayed_wb}
    save(READBACK, cross)
    state.update({"phase": "delayed_readback_complete", "finished_at_utc": now(),
                  "ozon_delayed_readback": {k: v for k, v in delayed_ozon.items() if k != "bindings"},
                  "wb_delayed_readback": {"expected": len(wb_fresh), "exact_metadata_cards": wb_exact,
                                          "valid_cards": wb_valid, "pending_or_unverified_cards": wb_exact-wb_valid}})
    save(STATE, state)

    add = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    entries = add.get("post_snapshot_writes", [])
    if any(x.get("document_number") == NUMBER for x in entries):
        raise RuntimeError("addendum_already_contains_document")
    entries.append({"brand": "Gauss", "document_number": NUMBER, "type": "declaration",
        "fsa_record_id": REGISTRY_ID, "fsa_status": "active", "source_sha256": SOURCE_SHA256,
        "ozon_certificate_id": delayed_ozon.get("certificate_id"),
        "ozon_record_status": delayed_ozon.get("record_status"),
        "ozon_expected_bindings": len(fresh), "ozon_exact_bindings": delayed_ozon.get("exact_visible", 0),
        "ozon_binding_status_counts": delayed_ozon.get("status_counts", {}),
        "ozon_out_of_scope_or_identity_skipped": len(ozon_skipped),
        "wb_expected_cards": len(wb_fresh), "wb_exact_cards": wb_exact,
        "wb_valid_cards": wb_valid, "wb_pending_or_unverified_cards": wb_exact-wb_valid,
        "wb_skipped": wb_skipped, "wb_review_state_changed_by_agent": False,
        "wb_left_for_marketplace_review": True, "local_source_pdf_deleted": False,
        "limitation": "48 of 63 source offers had Ozon TN VED outside the FSA declaration scope; 3 WB cards were unavailable or had out-of-scope TN VED.",
        "verification_artifacts": [PREFLIGHT.name, STATE.name, READBACK.name]})
    artifacts = add.setdefault("verification_artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["gauss_24108_readback"] = str(READBACK)
    elif isinstance(artifacts, list):
        artifacts.append(str(READBACK))
    else:
        raise RuntimeError("unsupported_addendum_artifacts_format")
    add["post_snapshot_writes"] = entries
    add["checked_at_utc"] = now()
    add["complete"] = False
    add["local_source_pdfs_deleted"] = False
    save(ADDENDUM, add)
    print(json.dumps({"execution": str(STATE), "readback": str(READBACK),
                      "phase": state["phase"], "ozon": {k: delayed_ozon.get(k) for k in
                       ("certificate_id", "record_status", "expected", "exact_visible", "status_counts")},
                      "wb": {"expected": len(wb_fresh), "exact": wb_exact, "valid": wb_valid,
                             "pending_or_unverified": wb_exact-wb_valid},
                      "skipped": {"ozon": len(ozon_skipped), "wb": len(wb_skipped)},
                      "local_source_pdf_deleted": False}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
