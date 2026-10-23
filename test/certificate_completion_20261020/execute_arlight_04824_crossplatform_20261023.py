#!/usr/bin/env python3
"""Upload and bind Arlight certificate 04824/22 on exact live Ozon/WB targets."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
import run_all_found_certificates_20261014 as runner  # noqa: E402
from api_client import Client, now, digest  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

PREFLIGHT = HERE / "arlight_04824_crossplatform_preflight_20261023.json"
OUT = HERE / "arlight_04824_crossplatform_execution_20261023.json"
JOURNAL = HERE / "arlight_04824_crossplatform_mutation_journal_20261023.jsonl"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/B5C5BB7F9BA5554A937519F74325C68F.pdf"
NUMBER = "ЕАЭС RU С-HK.АБ53.В.04824/22"
ISSUE_DATE = "2022-06-20"
EXPIRY_DATE = "2027-06-19"
TNVED = {"9405310000"}


def atomic_json(value: object) -> None:
    temp = OUT.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(OUT)


def append_journal(value: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now(), **value}, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def code_values(values: list[object]) -> set[str]:
    return {str(value or "").split(" - ", 1)[0].strip() for value in values
            if str(value or "").split(" - ", 1)[0].strip()}


def brand_and_tnved(attribute: dict) -> tuple[list[str], set[str]]:
    attrs = {str(x.get("id")): x for x in attribute.get("attributes") or []}
    brand = [str(x.get("value") or "").strip()
             for x in (attrs.get("85") or {}).get("values") or []
             if str(x.get("value") or "").strip()]
    tnved = code_values([x.get("value") for x in (attrs.get("22232") or {}).get("values") or []])
    return brand, tnved


def refresh_ozon_targets(client: Client, expected: list[dict]) -> list[dict]:
    refreshed = []
    for start in range(0, len(expected), 100):
        chunk = expected[start:start + 100]
        pids = [str(x["product_id"]) for x in chunk]
        offers = [str(x["offer_id"]) for x in chunk]
        product_rows = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in pids],
        }).get("items") or []
        attr_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": offers}, "limit": len(offers),
        }).get("result") or []
        by_pid = {str(x.get("product_id") or x.get("id") or ""): x for x in product_rows}
        by_offer = {str(x.get("offer_id") or ""): x for x in attr_rows}
        if len(by_pid) != len(chunk) or len(by_offer) != len(chunk):
            raise RuntimeError("ozon_fresh_identity_read_incomplete")
        for target in chunk:
            product = by_pid.get(str(target["product_id"]))
            attr = by_offer.get(str(target["offer_id"]))
            if (not product or not attr
                    or str(product.get("offer_id") or "") != target["offer_id"]
                    or str(product.get("sku") or "") != target["sku"]
                    or str(attr.get("id") or attr.get("product_id") or "") != target["product_id"]
                    or product.get("is_archived") is not False):
                raise RuntimeError("ozon_product_identity_changed:" + target["offer_id"])
            brand, tnved = brand_and_tnved(attr)
            if brand != ["Arlight"] or tnved != TNVED:
                raise RuntimeError("ozon_brand_or_tnved_changed:" + target["offer_id"])
            refreshed.append({**target, "live_ozon_brand": brand,
                              "live_ozon_tnved": sorted(tnved),
                              "live_ozon_name": product.get("name")})
    return refreshed


def list_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        data = client.call("ozon", "/v1/product/certificate/list",
                           {"page": page, "page_size": 100}).get("result") or {}
        batch = data.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(data.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def exact_ozon_record(rows: list[dict]) -> dict | None:
    matches = [row for row in rows if norm_number(row.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_certificate_records")
    if not matches:
        return None
    record = matches[0]
    if (record.get("type_code") != "certificate_of_conformity"
            or record.get("accordance_type_code") != "EAEU"
            or str(record.get("issue_date") or "")[:10] != ISSUE_DATE
            or str(record.get("expire_date") or "")[:10] != EXPIRY_DATE):
        raise RuntimeError("ozon_certificate_metadata_conflict")
    return record


def create_ozon_record(client: Client, targets: list[dict], state: dict) -> dict | None:
    record = exact_ozon_record(list_certificates(client))
    if record:
        state["ozon"].update({"created": False, "existing_record": True,
                               "certificate_id": str(record["certificate_id"]),
                               "record_status": record.get("status_code")})
        atomic_json(state)
        if record.get("status_code") in {"declined", "rejected", "invalid"}:
            state["ozon"]["blocked_reason"] = "existing_exact_record_declined"
            atomic_json(state)
            return None
        return record

    expiry = dt.date.fromisoformat(EXPIRY_DATE)
    payload = {"params": {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": NUMBER,
        "issue_date": wb_datetime(ISSUE_DATE),
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": sorted(x["sku"] for x in targets),
        "product_type": "UNKNOWN",
        "link_to_registry": state["fsa_evidence"]["registry_url"],
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
    }}
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(payload_bytes) >= 15_000_000:
        raise RuntimeError("ozon_payload_limit")
    marker = hashlib.sha256(payload_bytes).hexdigest()
    state["ozon"].update({"create_prepared": True, "create_payload_sha256": marker,
                          "create_payload_bytes": len(payload_bytes), "create_target_count": len(targets)})
    atomic_json(state)
    append_journal({"platform": "ozon", "phase": "prepared",
                    "endpoint": "/v2/product/certificate/create", "number": NUMBER,
                    "source_sha256": digest(SOURCE), "payload_sha256": marker,
                    "payload_bytes": len(payload_bytes), "target_count": len(targets)})
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        append_journal({"platform": "ozon", "phase": "response",
                        "endpoint": "/v2/product/certificate/create", "number": NUMBER,
                        "response": response, "payload_sha256": marker})
        state["ozon"].update({"create_response": response})
    except Exception as exc:
        append_journal({"platform": "ozon", "phase": "uncertain",
                        "endpoint": "/v2/product/certificate/create", "number": NUMBER,
                        "error_type": type(exc).__name__, "payload_sha256": marker})
        state["ozon"]["create_error_type"] = type(exc).__name__
        state["ozon"]["create_outcome_uncertain"] = True
        atomic_json(state)
        # Reconcile once. Never replay an uncertain create request.
    matches = [row for row in list_certificates(client)
               if norm_number(row.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) != 1:
        state["ozon"]["record_reconciliation"] = "not_visible_or_ambiguous; create_not_retried"
        atomic_json(state)
        return None
    record = exact_ozon_record(matches)
    state["ozon"].update({"created": True, "certificate_id": str(record["certificate_id"]),
                          "record_status": record.get("status_code"),
                          "record_reconciled": True})
    atomic_json(state)
    return record


def verify_ozon_bindings(client: Client, record: dict, targets: list[dict], state: dict) -> None:
    if not targets:
        state["ozon"].update({"target_count": 0, "readback": []})
        atomic_json(state)
        return
    certificate_id = int(record["certificate_id"])
    bindings = client.ozon_bindings(certificate_id)
    by_pid = {}
    for binding in bindings:
        pid = str(binding.get("product_id") or "")
        if not pid or pid in by_pid:
            raise RuntimeError("ozon_duplicate_binding_product_id")
        by_pid[pid] = binding
    rejected = [target for target in targets if (by_pid.get(target["product_id"]) or {}).get("product_status_code")
                in {"declined", "rejected", "invalid"}]
    missing = [target for target in targets if target["product_id"] not in by_pid]
    if missing and not rejected and record.get("status_code") not in {"declined", "rejected", "invalid"}:
        request = {"certificate_id": certificate_id, "skus": sorted(x["sku"] for x in missing)}
        marker = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        state["ozon"].update({"bind_prepared": True, "bind_payload_sha256": marker,
                              "missing_before_bind": len(missing)})
        atomic_json(state)
        append_journal({"platform": "ozon", "phase": "prepared",
                        "endpoint": "/v1/product/certificate/bind", "number": NUMBER,
                        "certificate_id": certificate_id, "sku_count": len(missing),
                        "payload_sha256": marker})
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            append_journal({"platform": "ozon", "phase": "response",
                            "endpoint": "/v1/product/certificate/bind", "number": NUMBER,
                            "certificate_id": certificate_id, "response": response,
                            "payload_sha256": marker})
            state["ozon"]["bind_response"] = response
        except Exception as exc:
            append_journal({"platform": "ozon", "phase": "uncertain",
                            "endpoint": "/v1/product/certificate/bind", "number": NUMBER,
                            "certificate_id": certificate_id, "error_type": type(exc).__name__,
                            "payload_sha256": marker})
            state["ozon"]["bind_error_type"] = type(exc).__name__
            state["ozon"]["bind_outcome_uncertain"] = True
            atomic_json(state)
        # Read back the one attempted batch. Do not repeat it if any target is missing.
        bindings = client.ozon_bindings(certificate_id)
        by_pid = {str(x.get("product_id") or ""): x for x in bindings}
    readback = []
    for target in targets:
        binding = by_pid.get(target["product_id"])
        readback.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                         "sku": target["sku"], "present": bool(binding),
                         "sku_matches": bool(binding and str(binding.get("sku")) == target["sku"]),
                         "status": binding.get("product_status_code") if binding else None})
    state["ozon"].update({
        "record_status": record.get("status_code"),
        "binding_count": len(bindings),
        "target_count": len(targets),
        "readback": readback,
        "readback_status_counts": dict(collections.Counter(str(x["status"] or "missing") for x in readback)),
        "present_count": sum(x["present"] and x["sku_matches"] for x in readback),
        "declined_target_count": len(rejected),
    })
    atomic_json(state)


def tnved(card: dict) -> set[str]:
    found: set[str] = set()
    for item in card.get("characteristics") or []:
        name = "".join(str(item.get("name") or "").casefold().split()).replace("ё", "е")
        if "тнвэд" not in name and "тнвед" not in name:
            continue
        raw = item.get("value")
        for value in raw if isinstance(raw, list) else [raw]:
            if value:
                found.add(str(value).split(" - ", 1)[0].strip())
    return found


def exact_wb_doc(card: dict) -> tuple[str, list[dict]]:
    docs = copy_documents(card)
    same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
    exact = [x for x in same if doc_key(x) == (1, norm_number(NUMBER))
             and str(x.get("startDate") or "")[:10] == ISSUE_DATE
             and str(x.get("endDate") or "")[:10] == EXPIRY_DATE
             and x.get("isEndless") is False]
    if not same:
        return "missing", []
    if len(same) == 1 and len(exact) == 1:
        return "exact", exact
    return "metadata_conflict", same


def document_signature(doc: dict) -> tuple:
    return (doc_key(doc), str(doc.get("startDate") or "")[:10],
            str(doc.get("endDate") or "")[:10], bool(doc.get("isEndless")))


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("execution_artifacts_exist_reconcile_before_retry")
    if not PREFLIGHT.is_file():
        raise RuntimeError("preflight_missing")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    pre_checked = dt.datetime.fromisoformat(str(pre["checked_at_utc"]).replace("Z", "+00:00"))
    if (pre.get("read_only") is not True
            or (dt.datetime.now(dt.timezone.utc) - pre_checked).total_seconds() > 1800
            or not pre.get("ozon_targets") or not pre.get("wb_targets")):
        raise RuntimeError("preflight_not_current_or_no_dual_platform_targets")
    if digest(SOURCE) != pre["source_sha256"]:
        raise RuntimeError("source_sha256_changed")
    if not ISSUE_DATE <= dt.datetime.now(dt.timezone.utc).date().isoformat() <= EXPIRY_DATE:
        raise RuntimeError("certificate_not_current_today")

    state = {
        "started_at": now(),
        "phase": "fresh_preflight",
        "number": NUMBER,
        "fsa_evidence": pre["fsa_evidence"],
        "source_file": str(SOURCE),
        "source_sha256": digest(SOURCE),
        "ozon_target_count": len(pre["ozon_targets"]),
        "wb_target_count": len(pre["wb_targets"]),
        "preflight_blocked_edges": pre.get("blocked_edges", []),
        "local_file_deleted": False,
        "wb_review_left_to_wb": True,
        "ozon": {},
        "wb": {"phase": "not_started"},
    }
    atomic_json(state)
    client = Client()

    # Recheck current Ozon Product ID/SKU/brand/TNVED in batches immediately before upload.
    try:
        ozon_targets = refresh_ozon_targets(client, pre["ozon_targets"])
        state["ozon"]["fresh_target_recheck"] = "passed"
        state["ozon"]["fresh_target_count"] = len(ozon_targets)
        atomic_json(state)
    except Exception as exc:
        state["ozon"].update({"phase": "skipped_fresh_recheck_failed",
                              "error_type": type(exc).__name__})
        ozon_targets = []
        atomic_json(state)

    if ozon_targets:
        try:
            record = create_ozon_record(client, ozon_targets, state)
            if record:
                verify_ozon_bindings(client, record, ozon_targets, state)
        except Exception as exc:
            state["ozon"].update({"phase": "error", "error_type": type(exc).__name__})
            atomic_json(state)

    # Fresh per-offer WB reads protect current identities and all pre-existing card data.
    desired = {"type": 1, "number": NUMBER,
               "startDate": wb_datetime(ISSUE_DATE), "endDate": wb_datetime(EXPIRY_DATE),
               "isEndless": False}
    wb_client = client
    before_by_offer = {}
    prepared = []
    already_present = []
    skipped = []
    wb_targets = pre["wb_targets"]
    for index, target in enumerate(wb_targets, 1):
        offer = target["offer_id"]
        try:
            cards = wb_client.wb_cards(offer)
        except Exception as exc:
            skipped.append({"offer_id": offer, "reason": "fresh_wb_read_failed",
                            "error_type": type(exc).__name__})
            continue
        if len(cards) != 1:
            skipped.append({"offer_id": offer, "reason": "wb_card_missing_or_ambiguous",
                            "card_count": len(cards)})
            continue
        card = cards[0]
        if str(card.get("vendorCode") or "") != offer or str(card.get("nmID") or "") != target["wb_nmID"]:
            skipped.append({"offer_id": offer, "reason": "wb_identity_changed"})
            continue
        if str(card.get("brand") or "").strip().casefold() != "arlight" or tnved(card) != TNVED:
            skipped.append({"offer_id": offer, "reason": "wb_brand_or_tnved_changed",
                            "brand": card.get("brand"), "tnved": sorted(tnved(card))})
            continue
        prior_docs = copy_documents(card)
        doc_state, same = exact_wb_doc(card)
        if doc_state == "exact":
            already_present.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                    "verdict": (same[0].get("verdict") or {})})
            before_by_offer[offer] = {"card": card, "prior_signatures": [document_signature(x) for x in prior_docs]}
            continue
        if doc_state == "metadata_conflict":
            skipped.append({"offer_id": offer, "reason": "existing_wb_document_metadata_conflict",
                            "documents": same})
            continue
        try:
            payload = runner.merge_wb(card, [desired])
        except Exception as exc:
            skipped.append({"offer_id": offer, "reason": "wb_payload_merge_failed",
                            "error_type": type(exc).__name__})
            continue
        if payload is None:
            already_present.append({"offer_id": offer, "nmID": str(card["nmID"]),
                                    "verdict": {"status": "exact_document_already_present"}})
            continue
        before_by_offer[offer] = {"card": card, "prior_signatures": [document_signature(x) for x in prior_docs]}
        prepared.append({"offer_id": offer, "nmID": str(card["nmID"]),
                         "before": card, "payload": payload})
        if index % 20 == 0:
            print(json.dumps({"phase": "wb_fresh_preflight", "checked": index,
                              "total": len(wb_targets), "updates": len(prepared),
                              "already_present": len(already_present), "skipped": len(skipped)}), flush=True)

    state["wb"].update({"phase": "fresh_preflight_complete", "source_target_count": len(wb_targets),
                        "safe_update_count": len(prepared), "already_present_count": len(already_present),
                        "skipped_count": len(skipped), "skipped": skipped,
                        "already_present": already_present,
                        "unique_live_cards_checked": len(before_by_offer), "writes_sent": 0})
    atomic_json(state)

    if prepared:
        payloads = [row["payload"] for row in prepared]
        encoded = json.dumps(payloads, ensure_ascii=False, separators=(",", ":")).encode()
        if len(payloads) > 1000 or len(encoded) > 9_000_000:
            raise RuntimeError("wb_payload_limit_exceeded")
        marker = hashlib.sha256(encoded).hexdigest()
        state["wb"].update({"phase": "update_prepared", "payload_sha256": marker,
                            "payload_bytes": len(encoded), "writes_sent": 1})
        atomic_json(state)
        append_journal({"platform": "wb", "phase": "prepared",
                        "endpoint": "/content/v2/cards/update", "number": NUMBER,
                        "payload_sha256": marker, "payload_bytes": len(encoded),
                        "nmIDs": [row["nmID"] for row in prepared]})
        try:
            response = client.call("wb", "/content/v2/cards/update", payloads, mutation=True)
            state["wb"].update({"mutation_response": response,
                                "mutation_accepted": isinstance(response, dict) and response.get("error") is False,
                                "mutation_uncertain": False})
            append_journal({"platform": "wb", "phase": "response",
                            "endpoint": "/content/v2/cards/update", "number": NUMBER,
                            "payload_sha256": marker, "response": response})
        except Exception as exc:
            state["wb"].update({"mutation_error_type": type(exc).__name__, "mutation_uncertain": True})
            append_journal({"platform": "wb", "phase": "uncertain",
                            "endpoint": "/content/v2/cards/update", "number": NUMBER,
                            "payload_sha256": marker, "error_type": type(exc).__name__})
        atomic_json(state)

    # One independent readback. Never resend a card-update batch after an uncertain result.
    readback = []
    for target in wb_targets:
        offer = target["offer_id"]
        before_record = before_by_offer.get(offer)
        try:
            cards = wb_client.wb_cards(offer)
        except Exception as exc:
            readback.append({"offer_id": offer, "readback_ok": False,
                             "reason": "readback_failed", "error_type": type(exc).__name__})
            continue
        if len(cards) != 1:
            readback.append({"offer_id": offer, "readback_ok": False,
                             "reason": "card_missing_or_ambiguous", "card_count": len(cards)})
            continue
        card = cards[0]
        state_code, matches = exact_wb_doc(card)
        present = state_code == "exact" and bool(matches)
        prior_preserved = True
        unrelated_preserved = True
        if before_record:
            prior = before_record["card"]
            prior_preserved = set(before_record["prior_signatures"]).issubset(
                {document_signature(x) for x in copy_documents(card)})
            unrelated_preserved = comparable_card(prior) == comparable_card(card)
        verdicts = [x.get("verdict") or {} for x in matches]
        verdict = verdicts[0] if verdicts else {}
        readback.append({
            "offer_id": offer,
            "nmID": str(card.get("nmID") or ""),
            "readback_ok": present and prior_preserved and unrelated_preserved,
            "exact_metadata_visible": present,
            "prior_documents_preserved": prior_preserved,
            "unrelated_fields_preserved": unrelated_preserved,
            "verdict": verdict,
            "document_id": matches[0].get("id") if matches else None,
        })
    verdict_counts = collections.Counter()
    for row in readback:
        if not row.get("exact_metadata_visible"):
            verdict_counts["missing_or_conflict"] += 1
        else:
            verdict = row.get("verdict") or {}
            if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid":
                verdict_counts["valid"] += 1
            elif verdict.get("status") in (None, 0) and verdict.get("reason") in (None, ""):
                verdict_counts["pending_or_unverified"] += 1
            else:
                verdict_counts["rejected_or_invalid"] += 1
    state["wb"].update({"phase": "readback_complete", "readback": readback,
                        "readback_count": len(readback),
                        "exact_metadata_count": sum(bool(x.get("exact_metadata_visible")) for x in readback),
                        "fully_preserved_count": sum(bool(x.get("readback_ok")) for x in readback),
                        "verdict_counts": dict(verdict_counts),
                        "wb_review_left_to_wb": True})
    state.update({"finished_at": now(), "phase": "finished"})
    atomic_json(state)
    print(json.dumps({
        "phase": state["phase"],
        "ozon": {k: v for k, v in state["ozon"].items()
                 if k not in {"readback", "create_response", "bind_response"}},
        "wb": {k: v for k, v in state["wb"].items()
               if k not in {"readback", "mutation_response", "already_present", "skipped"}},
        "local_file_deleted": False,
        "state": str(OUT),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
