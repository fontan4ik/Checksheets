#!/usr/bin/env python3
"""Upload Gauss declaration 15079/22, bind in-scope Ozon SKUs, and add WB metadata."""
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
from api_client import Client, now  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number, wb_datetime  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.PA04.В.15079/22"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/97d9c1e23660946b6eee1c11.pdf"
SOURCE_SHA = "af19f822882e35ad0da1ed741deba0e5c6868eb744c09712a95e3aa5dd75b9ee"
ISSUE = "2022-06-10"
EXPIRY = "2027-06-08"
ALLOWED_TNVED = {"9405420012"}
PREFLIGHT = HERE / "gauss_15079_live_preflight_20261022.json"
STATE_PATH = HERE / "gauss_15079_execution_20261022.json"
OZON_JOURNAL = HERE / "gauss_15079_ozon_mutations_20261022.jsonl"
WB_JOURNAL = HERE / "gauss_15079_wb_mutations_20261022.jsonl"
WB_BEFORE = HERE / "gauss_15079_wb_before_20261022.json"
WB_READBACK = HERE / "gauss_15079_wb_readback_20261022.json"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def journal(path: pathlib.Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def all_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("live_ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("live_ozon_certificate_page_limit")


def find_record(client: Client) -> list[dict]:
    return [x for x in all_certificates(client)
            if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]


def exact_wb_docs(card: dict) -> list[dict]:
    docs = ((card.get("documents") or {}).get("items") or [])
    return [d for d in docs if norm_number(d.get("number")) == norm_number(NUMBER)]


def main() -> None:
    if any(p.exists() for p in (STATE_PATH, OZON_JOURNAL, WB_JOURNAL, WB_BEFORE, WB_READBACK)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_any_retry")
    pre = json.loads(PREFLIGHT.read_text())
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or pre.get("ozon_safe_targets") != 127 or pre.get("wb_update_targets") != 135
            or pre.get("expire_date") != EXPIRY):
        raise RuntimeError("preflight_identity_or_target_counts_changed")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source_pdf_hash_changed")
    ozon_targets = {x["offer_id"]: x for x in pre["ozon_targets"] if x.get("safe_for_ozon") is True}
    wb_targets = {x["offer_id"]: x for x in pre["wb_targets"]}
    if len(ozon_targets) != 127 or len(wb_targets) != 135:
        raise RuntimeError("preflight_target_set_not_unique")
    if len({x["sku"] for x in ozon_targets.values()}) != len(ozon_targets):
        raise RuntimeError("ozon_skus_not_unique")

    client = Client()
    state = {"started_at_utc": now(), "number": NUMBER, "source_sha256": SOURCE_SHA,
        "issue_date": ISSUE, "expire_date": EXPIRY, "ozon_preflight_targets": 127,
        "wb_preflight_targets": 135, "ozon_mutation_attempted": False,
        "wb_mutation_attempted": False, "local_source_deleted": False,
        "wb_review_left_pending": True, "phase": "fresh_prewrite_check"}
    save(STATE_PATH, state)

    # Revalidate all Ozon identities and the no-duplicate record guard immediately before create/bind.
    offers = sorted(ozon_targets)
    fresh_products, fresh_attrs = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("fresh_ozon_prewrite_page_invalid")
        for row in p_rows:
            fresh_products.setdefault(str(row.get("offer_id") or ""), []).append(row)
        for row in a_rows:
            fresh_attrs.setdefault(str(row.get("offer_id") or ""), []).append(row)
    if set(fresh_products) != set(offers) or set(fresh_attrs) != set(offers):
        raise RuntimeError("fresh_ozon_prewrite_target_set_changed")
    for offer, expected in ozon_targets.items():
        p_rows, a_rows = fresh_products[offer], fresh_attrs[offer]
        if len(p_rows) != 1 or len(a_rows) != 1:
            raise RuntimeError("fresh_ozon_product_or_attrs_ambiguous:" + offer)
        p, a = p_rows[0], a_rows[0]
        brands = attr_values(a, 85)
        tnved = sorted({v.split(" - ", 1)[0].strip() for v in attr_values(a, 22232)})
        if (p.get("is_archived") is not False
                or str(p.get("product_id") or p.get("id") or "") != expected["product_id"]
                or str(p.get("sku") or "") != expected["sku"]
                or brands != ["Gauss"] or tnved != sorted(ALLOWED_TNVED)):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)

    matches = find_record(client)
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_document_records_before_write")
    record = matches[0] if matches else None
    if record and (record.get("type_code") != "declaration"
                   or str(record.get("issue_date") or "")[:10] != ISSUE
                   or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_metadata_conflict")
    state.update({"phase": "ozon_record_prewrite_checked", "record_reused": bool(record),
        "existing_record": ({k: record.get(k) for k in ("certificate_id", "certificate_number",
            "status_code", "issue_date", "expire_date", "products_count")} if record else None)})
    save(STATE_PATH, state)

    if record is None:
        expiry = dt.date.fromisoformat(EXPIRY)
        first_target = next(iter(ozon_targets.values()))
        payload = {"params": {
            "name": "Декларация о соответствии № " + NUMBER,
            "certificate_type": "DECLARATION",
            "certificate_country": "RU", "accordance_type": "EAEU", "number": NUMBER,
            "issue_date": wb_datetime(ISSUE),
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": [first_target["sku"]], "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                       "name": SOURCE.name}]}}
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal(OZON_JOURNAL, {"phase": "create_prepared", "at": now(), "request_sha256": marker,
            "request_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()),
            "source_sha256": SOURCE_SHA, "initial_sku": first_target["sku"]})
        state.update({"phase": "ozon_create_outcome_pending", "ozon_mutation_attempted": True,
                      "ozon_create_payload_sha256": marker})
        save(STATE_PATH, state)
        try:
            response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            state["ozon_create_response"] = response
            journal(OZON_JOURNAL, {"phase": "create_response", "at": now(), "response": response})
        except Exception as exc:
            state.update({"ozon_create_error_type": type(exc).__name__, "ozon_create_outcome_uncertain": True})
            journal(OZON_JOURNAL, {"phase": "create_outcome_uncertain", "at": now(),
                                    "error_type": type(exc).__name__})
            save(STATE_PATH, state)
        save(STATE_PATH, state)
        record = None
        for attempt in range(6):
            current = find_record(client)
            if current:
                if len(current) != 1:
                    state.update({"phase": "duplicate_ozon_record_after_create", "record_matches": current})
                    save(STATE_PATH, state)
                    raise RuntimeError("duplicate_ozon_record_after_create")
                record = current[0]
                break
            if attempt < 5:
                time.sleep(2)
        if not record:
            state.update({"phase": "ozon_record_not_visible_after_create", "no_create_retry": True})
            save(STATE_PATH, state)
            raise RuntimeError("ozon_create_not_visible_do_not_retry")
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRY):
            state.update({"phase": "ozon_created_record_metadata_conflict", "created_record": record})
            save(STATE_PATH, state)
            raise RuntimeError("ozon_created_record_metadata_conflict")

    state["ozon_record"] = {k: record.get(k) for k in ("certificate_id", "certificate_number",
        "type_code", "status_code", "issue_date", "expire_date", "products_count")}
    state["ozon_record_visible"] = True
    if str(record.get("status_code") or "").casefold() in {"declined", "rejected", "invalid", "cancelled"}:
        state.update({"phase": "ozon_record_declined_no_binding", "ozon_bindings_expected": 127})
        save(STATE_PATH, state)
    else:
        cid = int(record["certificate_id"])
        bindings_before = client.ozon_bindings(cid)
        expected_pairs = {(x["product_id"], x["sku"]) for x in ozon_targets.values()}
        before_pairs = {(str(x.get("product_id") or ""), str(x.get("sku") or "")) for x in bindings_before}
        outside = [x for x in bindings_before if (str(x.get("product_id") or ""), str(x.get("sku") or "")) not in expected_pairs]
        if outside:
            state.update({"phase": "ozon_record_has_outside_bindings_stop", "outside_binding_count": len(outside)})
            save(STATE_PATH, state)
            raise RuntimeError("ozon_record_has_outside_bindings")
        missing = [x for x in ozon_targets.values() if (x["product_id"], x["sku"]) not in before_pairs]
        if missing:
            bind_payload = {"certificate_id": cid, "skus": sorted(x["sku"] for x in missing)}
            bind_marker = hashlib.sha256(json.dumps(bind_payload, sort_keys=True).encode()).hexdigest()
            journal(OZON_JOURNAL, {"phase": "bind_prepared", "at": now(), "request_sha256": bind_marker,
                "certificate_id": cid, "sku_count": len(missing), "skus": bind_payload["skus"]})
            state.update({"phase": "ozon_bind_outcome_pending", "ozon_mutation_attempted": True,
                          "ozon_bind_requested": len(missing)})
            save(STATE_PATH, state)
            try:
                response = client.call("ozon", "/v1/product/certificate/bind", bind_payload, mutation=True)
                state["ozon_bind_response"] = response
                journal(OZON_JOURNAL, {"phase": "bind_response", "at": now(), "response": response})
            except Exception as exc:
                state.update({"ozon_bind_outcome_uncertain": True, "ozon_bind_error_type": type(exc).__name__})
                journal(OZON_JOURNAL, {"phase": "bind_outcome_uncertain", "at": now(), "error_type": type(exc).__name__})
                save(STATE_PATH, state)
                raise
        binding_rows = []
        bindings_after = []
        for attempt in range(6):
            bindings_after = client.ozon_bindings(cid)
            after_by_product = {str(x.get("product_id") or ""): x for x in bindings_after}
            binding_rows = []
            for t in ozon_targets.values():
                row = after_by_product.get(t["product_id"])
                binding_rows.append({"offer_id": t["offer_id"], "product_id": t["product_id"],
                    "sku": t["sku"], "visible": bool(row),
                    "identity_exact": bool(row and str(row.get("sku")) == t["sku"]),
                    "product_status_code": (row or {}).get("product_status_code")})
            if all(x["visible"] and x["identity_exact"] for x in binding_rows):
                break
            if attempt < 5:
                time.sleep(2)
        statuses = collections.Counter(str(x.get("product_status_code") or "unknown")
                                        for x in binding_rows if x["visible"] and x["identity_exact"])
        state.update({"ozon_bindings_expected": len(ozon_targets),
            "ozon_bindings_visible_exact": sum(x["visible"] and x["identity_exact"] for x in binding_rows),
            "ozon_binding_missing_or_conflicting": [x for x in binding_rows if not x["visible"] or not x["identity_exact"]],
            "ozon_binding_status_counts": dict(statuses), "ozon_bindings_total": len(bindings_after),
            "phase": "ozon_binding_readback_complete" if all(x["visible"] and x["identity_exact"] for x in binding_rows)
                     else "ozon_binding_readback_incomplete"})
        save(STATE_PATH, state)
        save(HERE / "gauss_15079_ozon_readback_20261022.json", {
            "checked_at_utc": now(), "read_only": True, "number": NUMBER,
            "certificate_id": cid, "record_status": record.get("status_code"),
            "expected": len(ozon_targets), "exact_visible": state["ozon_bindings_visible_exact"],
            "binding_status_counts": dict(statuses), "missing_or_conflicting": state["ozon_binding_missing_or_conflicting"],
            "rows": binding_rows, "local_source_deleted": False})

    # Prepare one WB update batch, preserving all existing card fields and documents.
    desired = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
               "endDate": wb_datetime(EXPIRY), "isEndless": False}
    updates, already, exclusions, before = [], [], [], {}
    for index, (offer, expected) in enumerate(sorted(wb_targets.items()), 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            exclusions.append({"offer_id": offer, "reason": "fresh_wb_card_missing_or_duplicate", "count": len(cards)})
            continue
        card = cards[0]
        tnved = code_values(card)
        if (str(card.get("nmID") or "") != expected["nmID"]
                or str(card.get("brand") or "").strip().casefold() != "gauss"
                or tnved != sorted(ALLOWED_TNVED)):
            exclusions.append({"offer_id": offer, "reason": "fresh_wb_identity_or_scope_changed",
                                "nmID": str(card.get("nmID") or ""), "brand": card.get("brand"), "tnved": tnved})
            continue
        same = exact_wb_docs(card)
        if same:
            exact = [d for d in same if str(d.get("type")) == "2"
                     and str(d.get("startDate") or "")[:10] == ISSUE
                     and str(d.get("endDate") or "")[:10] == EXPIRY
                     and d.get("isEndless") is False]
            if len(same) == 1 and len(exact) == 1:
                already.append({"offer_id": offer, "document": exact[0]})
            else:
                exclusions.append({"offer_id": offer, "reason": "same_number_metadata_conflict", "documents": same})
            continue
        payload = merge_wb(card, [desired])
        if payload is None:
            already.append({"offer_id": offer, "document": None})
            continue
        updates.append({"offer_id": offer, "nmID": expected["nmID"], "payload": payload})
        before[offer] = card
        if index % 20 == 0:
            print(json.dumps({"phase": "fresh_wb_prewrite", "checked": index, "targets": len(wb_targets),
                              "updates": len(updates), "already_exact": len(already), "excluded": len(exclusions)},
                             ensure_ascii=False), flush=True)
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": before,
        "already_exact": already, "exclusions": exclusions})
    state.update({"wb_fresh_targets": len(wb_targets), "wb_updates_planned": len(updates),
                  "wb_already_exact": len(already), "wb_prewrite_exclusions": exclusions})
    if exclusions:
        state["phase"] = "wb_fresh_prewrite_has_exclusions"  # Problem cards remain untouched.
    save(STATE_PATH, state)
    if updates:
        payload = [x["payload"] for x in updates]
        request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        if request_bytes > 9_500_000:
            raise RuntimeError("wb_update_payload_exceeds_safe_limit")
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal(WB_JOURNAL, {"phase": "update_prepared", "at": now(), "request_sha256": marker,
            "request_bytes": request_bytes, "card_count": len(updates), "offers": [x["offer_id"] for x in updates]})
        state.update({"phase": "wb_update_outcome_pending", "wb_mutation_attempted": True,
                      "wb_updates_planned": len(updates), "wb_request_sha256": marker})
        save(STATE_PATH, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", payload, mutation=True)
            state["wb_update_response"] = response
            journal(WB_JOURNAL, {"phase": "update_response", "at": now(), "response": response})
        except Exception as exc:
            state.update({"phase": "wb_update_outcome_uncertain", "wb_update_error_type": type(exc).__name__})
            journal(WB_JOURNAL, {"phase": "update_outcome_uncertain", "at": now(), "error_type": type(exc).__name__})
            save(STATE_PATH, state)
            raise
        if response.get("error") is not False:
            state.update({"phase": "wb_update_rejected_reconcile", "wb_update_response": response})
            save(STATE_PATH, state)
            raise RuntimeError("wb_update_rejected_do_not_retry")

    before_map = {offer: card for offer, card in before.items()}
    readback_rows = []
    readback_offers = sorted(set(wb_targets) - {x["offer_id"] for x in exclusions})
    for index, offer in enumerate(readback_offers, 1):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            readback_rows.append({"offer_id": offer, "status": "missing_or_duplicate", "card_count": len(cards)})
            continue
        card = cards[0]
        docs = exact_wb_docs(card)
        exact = len(docs) == 1 and str(docs[0].get("type")) == "2" \
            and str(docs[0].get("startDate") or "")[:10] == ISSUE \
            and str(docs[0].get("endDate") or "")[:10] == EXPIRY \
            and docs[0].get("isEndless") is False
        unchanged = (offer not in before_map or comparable_card(before_map[offer]) == comparable_card(card))
        readback_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "status": "verified_exact" if exact and unchanged else "readback_mismatch",
            "exact_metadata": exact, "non_document_fields_unchanged": unchanged,
            "verdict": docs[0].get("verdict") if docs else None, "documents": docs})
        if index % 20 == 0:
            print(json.dumps({"phase": "wb_targeted_readback", "queried": index,
                "targets": len(readback_offers), "verified_exact": sum(x["status"] == "verified_exact" for x in readback_rows)},
                ensure_ascii=False), flush=True)
    status_counts = collections.Counter(x["status"] for x in readback_rows)
    verdict_counts = collections.Counter()
    for row in readback_rows:
        if row["status"] != "verified_exact":
            continue
        verdict = row.get("verdict") or {}
        key = "valid" if verdict.get("verified") is True and verdict.get("status") == 1 and verdict.get("reason") == "valid" else (
              "invalid" if verdict.get("verified") is True and verdict.get("status") == 2 else "no_verdict_yet")
        verdict_counts[key] += 1
    readback = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "target_cards": len(readback_offers), "update_attempted": bool(updates),
        "updated_cards": len(updates), "already_exact_cards": len(already),
        "excluded_cards": exclusions, "status_counts": dict(status_counts),
        "verdict_counts": dict(verdict_counts), "wb_review_left_pending": True,
        "local_source_deleted": False, "results": readback_rows}
    save(WB_READBACK, readback)
    wb_complete = status_counts.get("verified_exact", 0) == len(readback_offers)
    ozon_complete = state.get("ozon_bindings_visible_exact") == len(ozon_targets)
    state.update({"phase": "complete" if wb_complete and ozon_complete else "cross_marketplace_readback_incomplete",
        "wb_readback_status_counts": dict(status_counts), "wb_verdict_counts": dict(verdict_counts),
        "wb_exact_metadata_cards": status_counts.get("verified_exact", 0),
        "wb_review_left_pending": True, "local_source_deleted": False,
        "finished_at_utc": now()})
    save(STATE_PATH, state)
    print(json.dumps({k: v for k, v in state.items() if k not in ("ozon_create_response", "ozon_bind_response",
        "wb_update_response", "wb_prewrite_exclusions")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
