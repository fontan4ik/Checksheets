#!/usr/bin/env python3
"""Upload the two in-scope Jazzway PPC documents and attach them to exact live products."""
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
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, copy_documents, norm_number, wb_datetime  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402
from preflight_jazzway_power_connectors_20261022 import DOCS, EXPIRY, ISSUE, OUT as PREFLIGHT, TNVED  # noqa: E402

STATE = HERE / "jazzway_power_connectors_execution_20261022.json"
OZON_JOURNAL = HERE / "jazzway_power_connectors_ozon_mutations_20261022.jsonl"
WB_JOURNAL = HERE / "jazzway_power_connectors_wb_mutations_20261022.jsonl"
WB_BEFORE = HERE / "jazzway_power_connectors_wb_before_20261022.json"
WB_READBACK = HERE / "jazzway_power_connectors_wb_readback_20261022.json"


def save(path: pathlib.Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def journal(path: pathlib.Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def all_records(client: Client) -> list[dict]:
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
    raise RuntimeError("ozon_certificate_page_limit")


def record_by_number(client: Client, number: str) -> dict | None:
    matches = [x for x in all_records(client)
               if norm_number(x.get("certificate_number")) == norm_number(number)]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_records:" + number)
    return matches[0] if matches else None


def exact_wb_docs(card: dict, number: str) -> list[dict]:
    return [x for x in copy_documents(card) if norm_number(x.get("number")) == norm_number(number)]


def exact_metadata(row: dict, document: dict) -> bool:
    return (str(row.get("type")) == str(document["wb_type"])
            and str(row.get("startDate", ""))[:10] == ISSUE
            and str(row.get("endDate", ""))[:10] == EXPIRY
            and str(row.get("isEndless", "false")).lower() not in {"true", "1"})


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(ident)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def verify_fresh_ozon(client: Client, pre: dict, targets: dict[str, dict]) -> dict[str, dict]:
    offers = sorted(targets)
    p_by_offer, a_by_offer = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("fresh_ozon_product_or_attribute_response_incomplete")
        for row in p_rows:
            p_by_offer.setdefault(str(row.get("offer_id") or ""), []).append(row)
        for row in a_rows:
            a_by_offer.setdefault(str(row.get("offer_id") or ""), []).append(row)
    if set(p_by_offer) != set(offers) or set(a_by_offer) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_changed")
    result = {}
    for offer in offers:
        if len(p_by_offer[offer]) != 1 or len(a_by_offer[offer]) != 1:
            raise RuntimeError("fresh_ozon_identity_ambiguous:" + offer)
        product, attribute = p_by_offer[offer][0], a_by_offer[offer][0]
        brands = attr_values(attribute, 85)
        tnved = sorted({x.split(" - ", 1)[0].strip() for x in attr_values(attribute, 22232)})
        old = targets[offer]
        if (product.get("is_archived") is not False or brands != ["Jazzway"] or tnved != [TNVED]
                or str(product.get("product_id") or product.get("id") or "") != str(old["product_id"])
                or str(product.get("sku") or "") != str(old["sku"])):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)
        result[offer] = {"product_id": str(product.get("product_id") or product.get("id") or ""),
                         "sku": str(product.get("sku") or "")}
    return result


def verify_fresh_wb(client: Client, pre: dict) -> dict[str, str]:
    expected = {x["offer_id"]: x for x in pre["wb_targets"]}
    identities = {}
    for offer in sorted(expected):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_missing_or_duplicate:" + offer)
        card = cards[0]
        codes = sorted(set(code_values(card)))
        if (str(card.get("nmID") or "") != str(expected[offer].get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() not in {"jazzway", "jazz way"}
                or codes != [TNVED]):
            raise RuntimeError("fresh_wb_identity_or_scope_changed:" + offer)
        identities[offer] = str(card.get("nmID") or "")
    if len(identities) != 36:
        raise RuntimeError("fresh_wb_card_set_changed")
    return identities


def create_ozon_record(client: Client, document: dict, targets: dict[str, dict], state: dict) -> dict:
    number = document["number"]
    record = record_by_number(client, number)
    if record:
        if (record.get("type_code") != document["type_code"]
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("existing_ozon_record_metadata_conflict:" + number)
        bindings = client.ozon_bindings(int(record["certificate_id"]))
        expected = {(x["product_id"], x["sku"]) for x in targets.values()}
        outside = [x for x in bindings if (str(x.get("product_id") or ""), str(x.get("sku") or "")) not in expected]
        if outside:
            raise RuntimeError("existing_ozon_record_has_out_of_scope_bindings:" + number)
        state.setdefault("records_reused", {})[document["key"]] = record.get("certificate_id")
        return record

    first = targets[sorted(targets)[0]]
    expiry = dt.date.fromisoformat(EXPIRY)
    source = ROOT / document["source_file"]
    payload = {"params": {
        "name": f"{('Сертификат соответствия' if document['type_code'] == 'certificate_of_conformity' else 'Декларация о соответствии')} № {number}",
        "certificate_type": document["ozon_create_type"], "certificate_country": "RU",
        "accordance_type": "EAEU", "number": number, "issue_date": wb_datetime(ISSUE),
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [first["sku"]], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": source.name}],
    }}
    marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    journal(OZON_JOURNAL, {"key": "ozon:" + document["key"] + ":create:" + marker,
        "phase": "create_prepared", "at": now(), "number": number, "request_sha256": marker,
        "source_sha256": document["sha256"], "source_bytes": source.stat().st_size,
        "request_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())})
    state["phase"] = "ozon_create_outcome_pending"
    state["current_document"] = document["key"]
    state["ozon_create_attempted"] = True
    save(STATE, state)
    try:
        response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
        journal(OZON_JOURNAL, {"key": "ozon:" + document["key"] + ":create:" + marker,
            "phase": "create_response", "at": now(), "response": response})
        state.setdefault("create_responses", {})[document["key"]] = response
        save(STATE, state)
    except Exception as exc:
        journal(OZON_JOURNAL, {"key": "ozon:" + document["key"] + ":create:" + marker,
            "phase": "create_outcome_uncertain", "at": now(), "error_type": type(exc).__name__})
        state["phase"] = "ozon_create_outcome_uncertain_do_not_retry"
        state["error_type"] = type(exc).__name__
        save(STATE, state)
        raise

    record = None
    for attempt in range(8):
        record = record_by_number(client, number)
        if record:
            break
        if attempt < 7:
            time.sleep(2)
    if not record:
        state["phase"] = "ozon_created_record_not_visible_do_not_retry"
        state["current_document"] = document["key"]
        save(STATE, state)
        raise RuntimeError("created_record_not_visible_do_not_retry:" + number)
    if (record.get("type_code") != document["type_code"]
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("created_record_metadata_conflict:" + number)
    state.setdefault("created_ozon_records", {})[document["key"]] = {
        "certificate_id": record.get("certificate_id"), "status_code": record.get("status_code")}
    save(STATE, state)
    return record


def bind_ozon_targets(client: Client, document: dict, record: dict,
                      targets: dict[str, dict], state: dict) -> dict:
    cid = int(record["certificate_id"])
    bindings_before = client.ozon_bindings(cid)
    by_pid = {str(x.get("product_id") or ""): x for x in bindings_before}
    target_pairs = {(x["product_id"], x["sku"]) for x in targets.values()}
    outside = [x for x in bindings_before if (str(x.get("product_id") or ""), str(x.get("sku") or "")) not in target_pairs]
    if outside:
        raise RuntimeError("ozon_record_has_unexpected_bindings:" + document["number"])
    conflicts = []
    missing = []
    for offer, target in targets.items():
        row = by_pid.get(target["product_id"])
        if row and str(row.get("sku") or "") != target["sku"]:
            conflicts.append(offer)
        elif not row:
            missing.append(target)
    if conflicts:
        raise RuntimeError("ozon_existing_binding_identity_conflict:" + ",".join(conflicts))
    if missing:
        payload = {"certificate_id": cid, "skus": sorted({x["sku"] for x in missing})}
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        journal(OZON_JOURNAL, {"key": "ozon:" + document["key"] + ":bind:" + marker,
            "phase": "bind_prepared", "at": now(), "number": document["number"],
            "certificate_id": cid, "request_sha256": marker, "sku_count": len(payload["skus"])})
        state["phase"] = "ozon_bind_outcome_pending"
        state["current_document"] = document["key"]
        save(STATE, state)
        response = client.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
        journal(OZON_JOURNAL, {"key": "ozon:" + document["key"] + ":bind:" + marker,
            "phase": "bind_response", "at": now(), "response": response})
        if response.get("result") is not True:
            raise RuntimeError("ozon_bind_not_accepted_reconcile_before_retry:" + document["number"])
    after = client.ozon_bindings(cid)
    after_by_pid = {str(x.get("product_id") or ""): x for x in after}
    rows = []
    for offer, target in sorted(targets.items()):
        binding = after_by_pid.get(target["product_id"])
        exact = bool(binding and str(binding.get("sku") or "") == target["sku"])
        rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                     "exact_binding_visible": exact,
                     "product_status_code": (binding or {}).get("product_status_code")})
    status_counts = collections.Counter(x["product_status_code"] or "missing" for x in rows)
    if len(rows) != len(targets) or any(not x["exact_binding_visible"] for x in rows):
        raise RuntimeError("ozon_binding_readback_incomplete:" + document["number"])
    return {"certificate_id": cid, "record_status": record.get("status_code"),
            "expected_exact_bindings": len(targets), "visible_exact_bindings": len(rows),
            "binding_status_counts": dict(status_counts), "missing_or_conflicting": 0,
            "rows": rows}


def main() -> None:
    required = [STATE, OZON_JOURNAL, WB_JOURNAL, WB_BEFORE, WB_READBACK]
    if any(x.exists() for x in required):
        raise RuntimeError("execution_artifact_exists_reconcile_before_any_retry")
    pre = json.loads(PREFLIGHT.read_text())
    if (pre.get("read_only") is not True or pre.get("ozon_identity_scope_safe_count") != 36
            or pre.get("wb_identity_scope_safe_count") != 36 or pre.get("products_per_document") != 36
            or pre.get("tnved") != TNVED or pre.get("issue_date") != ISSUE or pre.get("expiry_date") != EXPIRY):
        raise RuntimeError("preflight_not_fully_safe_or_identity_changed")
    expected_numbers = {x["number"] for x in DOCS}
    if any(pre.get("documents", [])[i].get("number") != doc["number"] for i, doc in enumerate(DOCS)):
        raise RuntimeError("preflight_document_order_or_identity_changed")
    ozon_targets = {}
    for row in pre["ozon_targets"]:
        if not row.get("identity_scope_safe"):
            raise RuntimeError("preflight_ineligible_ozon_target:" + row.get("offer_id", ""))
        ozon_targets[row["offer_id"]] = {"offer_id": row["offer_id"], "product_id": row["product_id"], "sku": row["sku"]}
    wb_targets = {x["offer_id"]: x for x in pre["wb_targets"] if x.get("identity_scope_safe") is True}
    if len(ozon_targets) != 36 or len(wb_targets) != 36 or set(ozon_targets) != set(wb_targets):
        raise RuntimeError("cross_platform_target_sets_not_exactly_36")

    client = Client()
    fresh_targets = verify_fresh_ozon(client, pre, ozon_targets)
    fresh_wb_ids = verify_fresh_wb(client, pre)
    state = {
        "started_at_utc": now(), "brand": "Jazzway", "documents": [
            {"key": x["key"], "number": x["number"], "sha256": x["sha256"],
             "issue_date": ISSUE, "expire_date": EXPIRY} for x in DOCS],
        "ozon_target_count_per_document": len(ozon_targets), "wb_target_cards": len(wb_targets),
        "ozon_mutations_attempted": False, "wb_mutation_attempted": False,
        "wb_review_left_pending": True, "local_source_files_deleted": False,
        "phase": "fresh_prewrite_scope_passed", "ozon_final_readbacks": {},
        "fresh_wb_identity_count_before_first_write": len(fresh_wb_ids),
    }
    save(STATE, state)

    for document in DOCS:
        record = create_ozon_record(client, document, fresh_targets, state)
        if str(record.get("status_code") or "").casefold() in {"declined", "rejected", "invalid", "cancelled"}:
            state["phase"] = "ozon_record_rejected_no_binding"
            state["current_document"] = document["key"]
            save(STATE, state)
            raise RuntimeError("ozon_record_declined_do_not_bind:" + document["number"])
        readback = bind_ozon_targets(client, document, record, fresh_targets, state)
        state["ozon_mutations_attempted"] = True
        state["ozon_final_readbacks"][document["key"]] = {k: v for k, v in readback.items() if k != "rows"}
        state.setdefault("ozon_target_rows", {})[document["key"]] = readback["rows"]
        state["phase"] = "ozon_document_bound"
        save(STATE, state)
        print(json.dumps({"phase": state["phase"], "document": document["key"],
                          "ozon": state["ozon_final_readbacks"][document["key"]]}, ensure_ascii=False), flush=True)

    # Revalidate all exact WB cards immediately before write and append both document metadata entries.
    updates, before, already_exact, conflicts = [], {}, [], []
    desired_docs = [{"type": d["wb_type"], "number": d["number"],
                     "startDate": f"{ISSUE}T00:00:00Z", "endDate": f"{EXPIRY}T00:00:00Z",
                     "isEndless": False} for d in DOCS]
    for offer, expected in sorted(wb_targets.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            conflicts.append({"offer_id": offer, "reason": "exact_card_missing_or_duplicate"})
            continue
        card = cards[0]
        tnved = sorted(set(code_values(card)))
        if (str(card.get("nmID") or "") != str(expected.get("nmID") or "")
                or fresh_wb_ids.get(offer) != str(card.get("nmID") or "")
                or str(card.get("brand") or "").strip().casefold() not in {"jazzway", "jazz way"}
                or tnved != [TNVED]):
            conflicts.append({"offer_id": offer, "reason": "fresh_identity_or_tnved_changed", "tnved": tnved})
            continue
        docs = copy_documents(card)
        for document in DOCS:
            matches = [x for x in docs if norm_number(x.get("number")) == norm_number(document["number"])]
            if matches and (len(matches) != 1 or not exact_metadata(matches[0], document)):
                conflicts.append({"offer_id": offer, "reason": "same_number_metadata_conflict", "number": document["number"]})
        if any(x.get("offer_id") == offer for x in conflicts):
            continue
        if all(any(norm_number(row.get("number")) == norm_number(d["number"]) and exact_metadata(row, d)
                   for row in docs) for d in DOCS):
            already_exact.append(offer)
            continue
        payload = merge_wb(card, desired_docs)
        if payload is None:
            conflicts.append({"offer_id": offer, "reason": "merge_returned_no_update_but_docs_not_exact"})
            continue
        updates.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""), "payload": payload})
        before[offer] = card
    if conflicts:
        state["phase"] = "wb_fresh_prewrite_conflict_stop"
        state["wb_prewrite_conflicts"] = conflicts
        save(STATE, state)
        raise RuntimeError("wb_prewrite_conflict_reconcile_before_update")
    if len(updates) + len(already_exact) != 36:
        raise RuntimeError("wb_prewrite_target_count_changed")
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": before,
                     "already_exact_offers": already_exact})
    payload = [x["payload"] for x in updates]
    payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    if payload_bytes > 9_500_000:
        raise RuntimeError("wb_payload_too_large")
    marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    journal(WB_JOURNAL, {"key": "wb:jazzway_power_connectors:" + marker, "phase": "prepared",
        "at": now(), "request_sha256": marker, "request_bytes": payload_bytes,
        "cards": len(updates), "offers": [x["offer_id"] for x in updates],
        "document_numbers": [x["number"] for x in DOCS]})
    state["phase"] = "wb_update_outcome_pending"
    state["wb_mutation_attempted"] = bool(updates)
    state["wb_updates_planned"] = len(updates)
    state["wb_already_exact"] = len(already_exact)
    save(STATE, state)
    if updates:
        response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
        journal(WB_JOURNAL, {"key": "wb:jazzway_power_connectors:" + marker, "phase": "response",
            "at": now(), "response": response})
        state["wb_response"] = response
        if response.get("error") is not False:
            state["phase"] = "wb_update_rejected_reconcile_required"
            save(STATE, state)
            raise RuntimeError("wb_update_not_accepted_reconcile_before_retry")

    rows = []
    for offer, expected in sorted(wb_targets.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            rows.append({"offer_id": offer, "status": "missing_or_duplicate", "card_count": len(cards)})
            continue
        card = cards[0]
        exact_rows = {}
        for document in DOCS:
            matches = exact_wb_docs(card, document["number"])
            exact_rows[document["key"]] = {"count": len(matches),
                "exact": len(matches) == 1 and exact_metadata(matches[0], document),
                "rows": matches}
        unchanged = offer not in before or comparable_card(before[offer]) == comparable_card(card)
        if offer in already_exact:
            unchanged = True
        rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                     "status": "verified_exact" if unchanged and all(x["exact"] for x in exact_rows.values()) else "readback_mismatch",
                     "non_document_fields_unchanged": unchanged, "documents": exact_rows})
    status_counts = collections.Counter(x["status"] for x in rows)
    doc_counts = {doc["key"]: sum(x["documents"].get(doc["key"], {}).get("exact") is True for x in rows)
                  for doc in DOCS}
    wb_readback = {"checked_at_utc": now(), "read_only": True,
        "target_cards": len(wb_targets), "exact_cards_with_both_documents": status_counts.get("verified_exact", 0),
        "exact_document_cards_by_document": doc_counts, "status_counts": dict(status_counts),
        "wb_review_left_pending": True, "marketplace_verdicts_manually_changed": False,
        "local_source_files_deleted": False, "results": rows}
    save(WB_READBACK, wb_readback)
    state["wb_readback"] = {k: wb_readback[k] for k in ("target_cards", "exact_cards_with_both_documents",
        "exact_document_cards_by_document", "status_counts", "wb_review_left_pending")}
    state["finished_at_utc"] = now()
    state["phase"] = "cross_marketplace_readback_incomplete" if status_counts.get("verified_exact") != 36 else "initial_readback_complete_delayed_readback_required"
    state["local_source_files_deleted"] = False
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "ozon": state["ozon_final_readbacks"],
                      "wb": state["wb_readback"], "local_source_files_deleted": False}, ensure_ascii=False), flush=True)
    if state["phase"] == "cross_marketplace_readback_incomplete":
        raise RuntimeError("initial_wb_readback_incomplete")


if __name__ == "__main__":
    main()
