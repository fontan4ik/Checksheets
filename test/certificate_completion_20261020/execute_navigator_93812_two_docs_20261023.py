#!/usr/bin/env python3
"""Apply and reconcile two exact Navigator 93812 documents on Ozon and WB."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, norm_number, wb_datetime,
)
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

PREFLIGHT = HERE / "navigator_93812_two_docs_live_preflight_20261023.json"
OUT = HERE / "navigator_93812_two_docs_execution_20261023.json"
JOURNAL = HERE / "navigator_93812_two_docs_mutation_journal_20261023.jsonl"
OFFERS = {"93812-5", "93812-10"}
DOCS = {
    "declaration": {
        "number": "ЕАЭС N RU Д-CN.РА11.В.08110/24", "type_code": "declaration", "wb_type": 2,
        "issue_date": "2024-12-02", "expire_date": "2029-12-01",
        "source_pdf": ROOT / "output_to_user/certificates/additional_search/brand_research/navigator/followup_2026_10_02/documents/originals/NAV_93812_declaration_2024_original.pdf",
        "source_sha256": "6281784d69c80c6fb396c095d4fafef82fad9771694f8b74510a7fafc2846fd2",
        "registry_url": "https://pub.fsa.gov.ru/rds/declaration/view/19670009/common",
    },
    "certificate": {
        "number": "ЕАЭС RU С-CN.НВ93.В.03629/23", "type_code": "certificate_of_conformity", "wb_type": 1,
        "issue_date": "2023-07-18", "expire_date": "2028-07-17",
        "source_pdf": ROOT / "output_to_user/certificates/additional_search/brand_research/navigator/followup_2026_10_02/documents/originals/NAV_93812_certificate_2023_original.pdf",
        "source_sha256": "3ff6e60fdd4ddac47a52ea19142c61f29f99d041510fb79c519ff70b2390add1",
        "registry_url": "https://pub.fsa.gov.ru/rss/certificate/view/3284481/baseInfo",
    },
}


def save(state: dict) -> None:
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(OUT)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now(), **row}, ensure_ascii=False) + "\n")
        stream.flush()


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def exact_record(rows: list[dict], doc: dict) -> dict | None:
    matches = [x for x in rows if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_records:" + doc["number"])
    if not matches:
        return None
    row = matches[0]
    if (row.get("type_code") != doc["type_code"]
            or row.get("accordance_type_code") != "EAEU"
            or str(row.get("issue_date") or "")[:10] != doc["issue_date"]
            or str(row.get("expire_date") or "")[:10] != doc["expire_date"]):
        raise RuntimeError("ozon_record_metadata_conflict:" + doc["number"])
    return row


def code_values(values: list[object]) -> set[str]:
    return {str(v or "").split(" - ", 1)[0].strip() for v in values
            if str(v or "").split(" - ", 1)[0].strip()}


def refresh_targets(client: Client, expected: list[dict]) -> list[dict]:
    refreshed = []
    for target in expected:
        offer = target["offer_id"]
        products = client.call("ozon", "/v3/product/info/list", {"offer_id": [offer]}).get("items") or []
        attrs = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": [offer]}, "limit": 1}).get("result") or []
        if len(products) != 1 or len(attrs) != 1:
            raise RuntimeError("ozon_identity_missing_or_ambiguous:" + offer)
        product = products[0]
        values = {str(x.get("id")): x for x in attrs[0].get("attributes") or []}
        brand = [str(x.get("value") or "").strip()
                 for x in (values.get("85") or {}).get("values") or []
                 if str(x.get("value") or "").strip()]
        tnved = code_values([x.get("value") for x in (values.get("22232") or {}).get("values") or []])
        current = {"offer_id": offer,
                   "product_id": str(product.get("product_id") or product.get("id") or ""),
                   "sku": str(product.get("sku") or ""), "brand": brand,
                   "tnved": sorted(tnved), "name": product.get("name")}
        if (product.get("is_archived") is not False or current["product_id"] != target["product_id"]
                or current["sku"] != target["sku"] or brand != ["Navigator"]
                or tnved != {"8539520009"}
                or "NLL-GX53-11-230-3K" not in str(product.get("name") or "")):
            raise RuntimeError("ozon_identity_or_scope_changed:" + offer)
        refreshed.append(current)
    return refreshed


def bind_exact_targets(client: Client, doc: dict, record: dict, targets: list[dict]) -> dict:
    certificate_id = int(record["certificate_id"])
    bindings = client.ozon_bindings(certificate_id)
    by_pid: dict[str, dict] = {}
    for row in bindings:
        pid = str(row.get("product_id") or "")
        if not pid or pid in by_pid:
            raise RuntimeError("ozon_binding_missing_or_duplicate_product_id:" + doc["number"])
        by_pid[pid] = row
    missing = []
    for target in targets:
        prior = by_pid.get(target["product_id"])
        if prior and str(prior.get("sku")) != target["sku"]:
            raise RuntimeError("ozon_binding_identity_conflict:" + target["offer_id"])
        if prior and prior.get("product_status_code") in {"declined", "rejected", "invalid"}:
            raise RuntimeError("ozon_binding_rejected:" + target["offer_id"])
        if not prior:
            missing.append(target)
    if missing:
        request = {"certificate_id": certificate_id, "skus": sorted(x["sku"] for x in missing)}
        marker = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal({"platform": "ozon", "phase": "prepared", "endpoint": "/v1/product/certificate/bind",
                 "number": doc["number"], "certificate_id": certificate_id,
                 "sku_count": len(missing), "payload_sha256": marker})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            journal({"platform": "ozon", "phase": "response", "endpoint": "/v1/product/certificate/bind",
                     "number": doc["number"], "certificate_id": certificate_id, "response": response})
        except Exception as exc:
            journal({"platform": "ozon", "phase": "uncertain", "endpoint": "/v1/product/certificate/bind",
                     "number": doc["number"], "certificate_id": certificate_id,
                     "error_type": type(exc).__name__})
            raise RuntimeError("ozon_bind_outcome_uncertain; reconcile before any retry") from None
    live = client.ozon_bindings(certificate_id)
    live_by_pid = {str(x.get("product_id")): x for x in live}
    rows = []
    for target in targets:
        item = live_by_pid.get(target["product_id"])
        rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                     "sku": target["sku"], "present": bool(item),
                     "sku_matches": bool(item and str(item.get("sku")) == target["sku"]),
                     "status": item.get("product_status_code") if item else None})
    if any(not x["present"] or not x["sku_matches"] for x in rows):
        raise RuntimeError("ozon_target_bindings_not_fully_visible:" + doc["number"])
    return {"certificate_id": certificate_id, "record_status": record.get("status_code"),
            "current_binding_count": len(live), "target_count": len(targets), "target_readback": rows,
            "target_status_counts": dict(collections.Counter(str(x["status"] or "unknown") for x in rows))}


def create_certificate_record(client: Client, doc: dict, targets: list[dict]) -> tuple[dict, dict]:
    current = exact_record(list_certificates(client), doc)
    if current:
        return current, {"created": False, "existing_record": True}
    expiry = dt.date.fromisoformat(doc["expire_date"])
    params = {
        "name": "Сертификат соответствия № " + doc["number"],
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU", "accordance_type": "EAEU", "number": doc["number"],
        "issue_date": wb_datetime(doc["issue_date"]),
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": sorted(x["sku"] for x in targets), "product_type": "UNKNOWN",
        "link_to_registry": doc["registry_url"],
        "files": [{"file_content": base64.b64encode(doc["source_pdf"].read_bytes()).decode("ascii"),
                   "name": doc["source_pdf"].name}],
    }
    payload = {"params": params}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) >= 15_000_000:
        raise RuntimeError("ozon_certificate_payload_too_large")
    journal({"platform": "ozon", "phase": "prepared", "endpoint": "/v2/product/certificate/create",
             "number": doc["number"], "source_sha256": doc["source_sha256"],
             "payload_sha256": hashlib.sha256(encoded).hexdigest(), "payload_bytes": len(encoded),
             "sku_count": len(targets)})
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        journal({"platform": "ozon", "phase": "response", "endpoint": "/v2/product/certificate/create",
                 "number": doc["number"], "response": response})
    except Exception as exc:
        journal({"platform": "ozon", "phase": "uncertain", "endpoint": "/v2/product/certificate/create",
                 "number": doc["number"], "error_type": type(exc).__name__})
        # No create retry. Reconcile once against the live certificate list.
        matches = [x for x in list_certificates(client)
                   if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if len(matches) != 1:
            raise RuntimeError("ozon_create_outcome_uncertain; no retry sent") from None
        record = exact_record(matches, doc)
        return record, {"created": True, "outcome": "record_reconciled_after_uncertain_response",
                        "response": None, "error_type": type(exc).__name__}
    for attempt in range(6):
        matches = [x for x in list_certificates(client)
                   if norm_number(x.get("certificate_number")) == norm_number(doc["number"])]
        if matches:
            break
        if attempt < 5:
            time.sleep(2)
    if len(matches) != 1:
        raise RuntimeError("ozon_created_record_not_visible; no create retry sent")
    record = exact_record(matches, doc)
    states = [x.get("state") for x in (response or {}).get("params", []) if isinstance(x, dict)]
    validated = response.get("status") == "COMPLETED" and bool(states) and set(states) == {"VALID"}
    return record, {"created": True, "outcome": "validated" if validated else "created_response_needs_review",
                    "response": response, "fully_validated": validated}


def main() -> None:
    pre = json.loads(PREFLIGHT.read_text())
    checked = dt.datetime.fromisoformat(str(pre["checked_at_utc"]).replace("Z", "+00:00"))
    if (pre.get("read_only") is not True or pre.get("target_count") != 2
            or (dt.datetime.now(dt.timezone.utc) - checked).total_seconds() > 1800):
        raise RuntimeError("preflight_not_current_or_complete")
    targets = pre["targets"]
    if {x["offer_id"] for x in targets} != OFFERS or len(targets) != 2:
        raise RuntimeError("preflight_target_identity_changed")
    for doc_name, doc in DOCS.items():
        if hashlib.sha256(doc["source_pdf"].read_bytes()).hexdigest() != doc["source_sha256"]:
            raise RuntimeError("source_hash_changed:" + doc_name)
        if pre["fsa_registry_checks"][doc_name].get("status") != "Действует":
            raise RuntimeError("fsa_not_active:" + doc_name)
    if any(x.get("brand") != ["Navigator"] or x.get("tnved") != ["8539520009"] for x in targets):
        raise RuntimeError("preflight_ozon_scope_invalid")
    for offer, result in pre["wb"].items():
        if result.get("brand") != "Navigator" or result.get("tnved") != ["8539520009"]:
            raise RuntimeError("preflight_wb_scope_invalid:" + offer)

    state = {"started_at_utc": now(), "phase": "preflight_passed", "target_count": 2,
             "documents": {}, "wb": {"cards": [], "mutation_batches": [], "delayed_readback": []},
             "wb_left_for_marketplace_review": True, "local_source_files_deleted": False}
    save(state)
    client = Client()
    refreshed_targets = refresh_targets(client, targets)
    state["fresh_target_identity"] = refreshed_targets
    save(state)
    current_records = list_certificates(client)

    # Existing, already-approved declaration record: only add the two missing SKU edges.
    declaration = DOCS["declaration"]
    decl_record = exact_record(current_records, declaration)
    if not decl_record or decl_record.get("status_code") != "approved":
        raise RuntimeError("ozon_existing_declaration_not_current_approved")
    state["phase"] = "ozon_declaration_bind_in_progress"
    state["documents"]["declaration"] = {"record_id": decl_record["certificate_id"],
                                           "record_status": decl_record.get("status_code")}
    save(state)
    decl_read = bind_exact_targets(client, declaration, decl_record, targets)
    state["documents"]["declaration"].update(decl_read)
    save(state)

    # The exact certificate had no Ozon record in preflight. Recheck just before create.
    cert_doc = DOCS["certificate"]
    existing = exact_record(list_certificates(client), cert_doc)
    if existing is None:
        state["phase"] = "ozon_certificate_create_in_progress"
        save(state)
        cert_record, create_result = create_certificate_record(client, cert_doc, targets)
    else:
        cert_record, create_result = existing, {"created": False, "existing_record": True}
    if not cert_record:
        raise RuntimeError("ozon_certificate_record_unreconciled")
    if cert_record.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}:
        raise RuntimeError("ozon_certificate_record_rejected")
    state["documents"]["certificate"] = {"record_id": cert_record["certificate_id"],
                                           "record_status": cert_record.get("status_code"),
                                           "create": create_result}
    save(state)
    cert_read = bind_exact_targets(client, cert_doc, cert_record, targets)
    state["documents"]["certificate"].update(cert_read)
    save(state)

    # Read both current WB cards again immediately before preparing one full-card update.
    desired = [{"type": doc["wb_type"], "number": doc["number"],
                "startDate": doc["issue_date"] + "T00:00:00Z",
                "endDate": doc["expire_date"] + "T00:00:00Z", "isEndless": False}
               for doc in DOCS.values()]
    updates = []
    before_by_offer = {}
    for offer in sorted(OFFERS):
        rows = client.wb_cards(offer)
        if len(rows) != 1 or str(rows[0].get("vendorCode") or "") != offer:
            raise RuntimeError("wb_card_missing_or_ambiguous_before_write:" + offer)
        card = rows[0]
        if card.get("brand") != "Navigator":
            raise RuntimeError("wb_brand_changed_before_write:" + offer)
        codes = []
        for row in card.get("characteristics") or []:
            label = "".join(str(row.get("name") or "").casefold().split()).replace("ё", "е")
            if "тнвэд" in label or "тнвед" in label:
                value = row.get("value")
                codes.extend(value if isinstance(value, list) else [value])
        actual_codes = {str(x or "").split(" - ", 1)[0].strip() for x in codes
                        if str(x or "").split(" - ", 1)[0].strip()}
        if actual_codes != {"8539520009"}:
            raise RuntimeError("wb_tnved_changed_before_write:" + offer)
        payload = merge_wb(card, desired)
        before_by_offer[offer] = card
        if payload is not None:
            updates.append({"offer_id": offer, "nmID": str(card.get("nmID")), "payload": payload})
        else:
            updates.append({"offer_id": offer, "nmID": str(card.get("nmID")), "payload": None})
    payloads = [x["payload"] for x in updates if x["payload"] is not None]
    if payloads:
        marker = hashlib.sha256(json.dumps(payloads, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        batch = {"marker": marker, "offers": [x["offer_id"] for x in updates if x["payload"] is not None],
                 "items": len(payloads), "response": None, "uncertain": False}
        state["wb"]["mutation_batches"].append(batch)
        state["phase"] = "wb_update_in_progress"
        save(state)
        journal({"platform": "wb", "phase": "prepared", "endpoint": "/content/v2/cards/update",
                 "items": len(payloads), "payload_sha256": marker})
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
            batch["response"] = response
            batch["accepted"] = isinstance(response, dict) and response.get("error") is False
            journal({"platform": "wb", "phase": "response", "endpoint": "/content/v2/cards/update",
                     "payload_sha256": marker, "response": response})
        except Exception as exc:
            batch["uncertain"] = True
            batch["error_type"] = type(exc).__name__
            journal({"platform": "wb", "phase": "uncertain", "endpoint": "/content/v2/cards/update",
                     "payload_sha256": marker, "error_type": type(exc).__name__})
            save(state)
            raise RuntimeError("wb_update_outcome_uncertain; reconcile before any retry") from None
    save(state)

    # Immediate live readback; never resend WB writes after a visibility lag.
    for offer in sorted(OFFERS):
        card_rows = client.wb_cards(offer)
        if len(card_rows) != 1:
            raise RuntimeError("wb_readback_card_missing_or_ambiguous:" + offer)
        card = card_rows[0]
        docs = copy_documents(card)
        found = {}
        for doc_name, doc in DOCS.items():
            live_docs = (card.get("documents") or {}).get("items") or []
            matches = [x for x in live_docs if norm_number(x.get("number")) == norm_number(doc["number"])
                       and int(x.get("type") or 0) == doc["wb_type"]
                       and str(x.get("startDate") or "")[:10] == doc["issue_date"]
                       and str(x.get("endDate") or "")[:10] == doc["expire_date"]]
            verdicts = [x.get("verdict") or {} for x in matches]
            valid = any(v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid"
                        for v in verdicts)
            rejected = any(v.get("status") not in (None, 1)
                           or v.get("reason") not in (None, "", "valid") for v in verdicts)
            found[doc_name] = {"visible": bool(matches), "exact_match_count": len(matches),
                               "verdicts": verdicts,
                               "status": "valid" if valid else ("rejected_or_invalid" if rejected else
                                                                  "pending_or_verdict_absent")}
        before = before_by_offer[offer]
        before_docs = {(int(x.get("type") or 0), norm_number(x.get("number")),
                        str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10])
                       for x in copy_documents(before)}
        after_docs = {(int(x.get("type") or 0), norm_number(x.get("number")),
                       str(x.get("startDate") or "")[:10], str(x.get("endDate") or "")[:10])
                      for x in docs}
        if not before_docs <= after_docs:
            raise RuntimeError("wb_prior_documents_not_preserved:" + offer)
        if comparable_card(before) != comparable_card(card):
            raise RuntimeError("wb_non_document_card_fields_changed:" + offer)
        state["wb"]["cards"].append({"offer_id": offer, "nmID": str(card.get("nmID")),
                                     "all_target_documents_visible": all(x["visible"] for x in found.values()),
                                     "documents": found, "prior_documents_preserved": True,
                                     "non_document_fields_unchanged": True})
    save(state)

    unresolved = [x for x in state["wb"]["cards"] if not x["all_target_documents_visible"]]
    for wait_seconds in (60, 120):
        if not unresolved:
            break
        time.sleep(wait_seconds)
        next_unresolved = []
        for item in unresolved:
            rows = client.wb_cards(item["offer_id"])
            if len(rows) != 1:
                state["wb"]["delayed_readback"].append({"offer_id": item["offer_id"], "error": "card_missing"})
                next_unresolved.append(item)
                continue
            card = rows[0]
            docs = copy_documents(card)
            live_docs = (card.get("documents") or {}).get("items") or []
            for doc_name, doc in DOCS.items():
                matches = [x for x in live_docs if norm_number(x.get("number")) == norm_number(doc["number"])
                           and int(x.get("type") or 0) == doc["wb_type"]
                           and str(x.get("startDate") or "")[:10] == doc["issue_date"]
                           and str(x.get("endDate") or "")[:10] == doc["expire_date"]]
                verdicts = [x.get("verdict") or {} for x in matches]
                valid = any(v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid"
                            for v in verdicts)
                rejected = any(v.get("status") not in (None, 1)
                               or v.get("reason") not in (None, "", "valid") for v in verdicts)
                state["wb"]["delayed_readback"].append({"offer_id": item["offer_id"], "nmID": item["nmID"],
                    "document": doc_name, "visible": bool(matches),
                    "status": "valid" if valid else ("rejected_or_invalid" if rejected else "pending_or_verdict_absent")})
            if any(not (norm_number(doc["number"]) in {norm_number(x.get("number")) for x in docs})
                   for doc in DOCS.values()):
                next_unresolved.append(item)
        unresolved = next_unresolved
        save(state)
    state["wb"]["still_not_visible_after_delayed_recheck"] = len(unresolved)
    state["phase"] = "finished" if not unresolved else "needs_visibility_reconciliation"
    state["finished_at_utc"] = now()
    state["no_local_files_deleted"] = True
    save(state)
    print(json.dumps({"execution_file": str(OUT), "phase": state["phase"],
                      "ozon": {k: {"certificate_id": v.get("certificate_id"),
                                  "record_status": v.get("record_status"),
                                  "target_status_counts": v.get("target_status_counts")}
                               for k, v in state["documents"].items()},
                      "wb_cards": len(state["wb"]["cards"]),
                      "wb_document_visibility": {doc: sum(1 for row in state["wb"]["cards"]
                          if row.get("documents", {}).get(doc, {}).get("visible")) for doc in DOCS},
                      "wb_document_verdicts": {doc: dict(collections.Counter(
                          row.get("documents", {}).get(doc, {}).get("status") for row in state["wb"]["cards"]))
                          for doc in DOCS},
                      "still_not_visible_after_delayed_recheck": state["wb"]["still_not_visible_after_delayed_recheck"],
                      "local_source_files_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
