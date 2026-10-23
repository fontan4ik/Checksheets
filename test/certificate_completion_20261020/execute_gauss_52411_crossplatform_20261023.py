#!/usr/bin/env python3
"""Apply Gauss declaration 52411/23 to fresh, in-scope Ozon and WB targets."""
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
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import comparable_card, norm_number, wb_datetime  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА04.В.52411/23"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/gauss/25aeb2f93ed587f14b19dc21.pdf"
SOURCE_SHA = "b9503157b344ec2ed68fe168f8b7c9f7046d28a1e7734b8a9949589c5b12ad3d"
ISSUE = "2023-06-08"
EXPIRY = "2028-06-07"
ALLOWED_TNVED = {"8513100000"}
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/17768504/common"
PREFLIGHT = HERE / "gauss_52411_crossplatform_preflight_20261023.json"
STATE = HERE / "gauss_52411_execution_20261023.json"
JOURNAL = HERE / "gauss_52411_mutation_journal_20261023.jsonl"
WB_BEFORE = HERE / "gauss_52411_wb_before_20261023.json"
READBACK = HERE / "gauss_52411_final_crossplatform_readback_20261023.json"


def save(path: pathlib.Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def journal(value: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


def attr_values(row: dict, ident: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip()
            for v in (attrs.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def live_certificates(client: Client) -> list[dict]:
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


def find_record(client: Client) -> list[dict]:
    return [x for x in live_certificates(client)
            if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]


def get_products(client: Client, offers: list[str]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    products: dict[str, list[dict]] = collections.defaultdict(list)
    attrs: dict[str, list[dict]] = collections.defaultdict(list)
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        p_rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        a_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)}).get("result")
        if not isinstance(p_rows, list) or not isinstance(a_rows, list):
            raise RuntimeError("ozon_product_response_invalid")
        for row in p_rows:
            products[str(row.get("offer_id") or "")].append(row)
        for row in a_rows:
            attrs[str(row.get("offer_id") or "")].append(row)
    return products, attrs


def fresh_ozon_targets(client: Client, expected: dict[str, dict]) -> dict[str, dict]:
    offers = sorted(expected)
    products, attrs = get_products(client, offers)
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("fresh_ozon_offer_set_changed")
    targets = {}
    for offer, old in expected.items():
        if len(products[offer]) != 1 or len(attrs[offer]) != 1:
            raise RuntimeError("fresh_ozon_identity_ambiguous:" + offer)
        p, a = products[offer][0], attrs[offer][0]
        brands = attr_values(a, 85)
        tnved = {x.split(" - ", 1)[0].strip() for x in attr_values(a, 22232)}
        pid, sku = str(p.get("product_id") or p.get("id") or ""), str(p.get("sku") or "")
        if (p.get("is_archived") is not False or pid != str(old.get("product_id") or "")
                or sku != str(old.get("sku") or "") or brands != ["Gauss"]
                or tnved != ALLOWED_TNVED):
            raise RuntimeError("fresh_ozon_identity_or_scope_changed:" + offer)
        targets[offer] = {"offer_id": offer, "product_id": pid, "sku": sku}
    return targets


def fresh_wb_cards(client: Client, expected: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    updates, before = [], {}
    wanted = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
    for offer, old in sorted(expected.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("fresh_wb_card_missing_or_duplicate:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != str(old.get("wb_nmID") or "")
                or str(card.get("brand") or "").strip().casefold() != "gauss"
                or set(code_values(card)) != ALLOWED_TNVED):
            raise RuntimeError("fresh_wb_identity_or_scope_changed:" + offer)
        docs = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and not (len(same) == len(exact) == 1):
            raise RuntimeError("fresh_wb_same_number_conflict:" + offer)
        if exact:
            continue
        payload = merge_wb(card, [wanted])
        if payload is None:
            raise RuntimeError("wb_merge_unexpected_noop:" + offer)
        updates.append(payload)
        before[offer] = card
    return updates, before


def ozon_upload_bind(client: Client, targets: dict[str, dict], state: dict) -> dict:
    matches = find_record(client)
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_record_before_write")
    record = matches[0] if matches else None
    if record and (record.get("type_code") != "declaration"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_metadata_conflict")
    if record and str(record.get("status_code") or "").casefold() in {"declined", "rejected", "invalid", "cancelled"}:
        return {"outcome": "existing_record_declined_skip", "record": record,
                "exact_visible": 0, "status_counts": {}}

    create_response = None
    if record is None:
        expires = dt.date.fromisoformat(EXPIRY)
        seed = next(iter(targets.values()))
        payload = {"params": {
            "name": "Декларация о соответствии № " + NUMBER,
            "certificate_type": "DECLARATION", "certificate_country": "RU",
            "accordance_type": "EAEU", "number": NUMBER,
            "issue_date": ISSUE + "T00:00:00Z",
            "expired_date": {"date": {"day": expires.day, "month": expires.month, "year": expires.year}},
            "skus": [seed["sku"]], "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                       "name": SOURCE.name}],
            "link_to_registry": FSA_URL,
        }}
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
            raise RuntimeError("ozon_create_payload_exceeds_limit")
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal({"at": now(), "platform": "ozon", "phase": "create_prepared",
                 "request_sha256": marker, "seed_offer": seed["offer_id"], "seed_sku": seed["sku"]})
        state.update({"phase": "ozon_create_outcome_pending", "ozon_create_attempted": True,
                      "ozon_create_payload_sha256": marker, "ozon_seed_offer": seed["offer_id"]})
        save(STATE, state)
        try:
            create_response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            journal({"at": now(), "platform": "ozon", "phase": "create_response", "response": create_response})
        except Exception as exc:
            journal({"at": now(), "platform": "ozon", "phase": "create_outcome_uncertain",
                     "error_type": type(exc).__name__})
            create_response = None
        for attempt in range(7):
            matches = find_record(client)
            if matches or attempt == 6:
                break
            time.sleep(2)
        if len(matches) != 1:
            state.update({"phase": "ozon_create_not_visible_skip", "ozon_create_error_type": None if create_response else "uncertain_or_rejected"})
            save(STATE, state)
            return {"outcome": "create_not_visible_skip", "create_response": create_response,
                    "exact_visible": 0, "status_counts": {}}
        record = matches[0]
        states = [x.get("state") for x in (create_response or {}).get("params", []) if isinstance(x, dict)]
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("created_ozon_record_metadata_conflict")
        if (not create_response or create_response.get("status") != "COMPLETED"
                or not states or set(states) != {"VALID"}):
            state.update({"phase": "ozon_create_response_unvalidated_skip_binding",
                          "ozon_record": record, "ozon_create_response": create_response})
            save(STATE, state)
            return {"outcome": "record_visible_create_response_unvalidated_skip_binding",
                    "record": record, "create_response": create_response,
                    "exact_visible": 0, "status_counts": {}}

    target_by_pid = {x["product_id"]: x for x in targets.values()}
    cid = int(record["certificate_id"])
    bindings = client.ozon_bindings(cid)
    binding_by_pid = {str(x.get("product_id") or ""): x for x in bindings}
    outside = [x for x in bindings if str(x.get("product_id") or "") not in target_by_pid]
    conflicts = [x for x in bindings if str(x.get("product_id") or "") in target_by_pid
                 and str(x.get("sku") or "") != target_by_pid[str(x.get("product_id"))]["sku"]]
    if outside or conflicts:
        raise RuntimeError("ozon_record_has_outside_or_conflicting_bindings")
    missing = [x for x in targets.values() if x["product_id"] not in binding_by_pid]
    if missing:
        payload = {"certificate_id": cid, "skus": sorted(x["sku"] for x in missing)}
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "ozon", "phase": "bind_prepared", "request_sha256": marker,
                 "certificate_id": cid, "offers": sorted(x["offer_id"] for x in missing),
                 "sku_count": len(missing)})
        state.update({"phase": "ozon_bind_outcome_pending", "ozon_bind_attempted": True,
                      "ozon_bind_payload_sha256": marker, "ozon_bind_target_count": len(missing)})
        save(STATE, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
            journal({"at": now(), "platform": "ozon", "phase": "bind_response", "response": response})
            state["ozon_bind_response"] = response
        except Exception as exc:
            journal({"at": now(), "platform": "ozon", "phase": "bind_outcome_uncertain",
                     "error_type": type(exc).__name__})
            state["ozon_bind_error_type"] = type(exc).__name__
        save(STATE, state)

    final_bindings = client.ozon_bindings(cid)
    final_by_pid = {str(x.get("product_id") or ""): x for x in final_bindings}
    rows = []
    for offer, target in sorted(targets.items()):
        binding = final_by_pid.get(target["product_id"])
        rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
            "visible_exact": bool(binding and str(binding.get("sku") or "") == target["sku"]),
            "status": (binding or {}).get("product_status_code")})
    statuses = collections.Counter(str(x["status"] or "unknown") for x in rows if x["visible_exact"])
    return {"outcome": "bound_or_reconciled", "record": record, "record_status": record.get("status_code"),
            "target_count": len(targets), "exact_visible": sum(x["visible_exact"] for x in rows),
            "status_counts": dict(statuses), "rows": rows, "outside_binding_count": len(outside)}


def main() -> None:
    if any(p.exists() for p in (STATE, JOURNAL, WB_BEFORE, READBACK)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source_file_hash_changed")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or pre.get("type_code") != "declaration" or pre.get("issue_date") != ISSUE
            or pre.get("expire_date") != EXPIRY or pre.get("fsa", {}).get("record_id") != "17768504"
            or pre.get("source_sha256") != SOURCE_SHA or pre.get("assignment_target_count") != 29
            or pre.get("ozon_safe_count") != 26 or pre.get("wb_safe_count") != 29):
        raise RuntimeError("preflight_identity_or_counts_changed")
    ozon_expected = {x["offer_id"]: x for x in pre["targets"] if x.get("ozon_safe") is True}
    wb_expected = {x["offer_id"]: x for x in pre["targets"] if x.get("wb_safe") is True}
    if (len(ozon_expected) != 26 or len(wb_expected) != 29
            or len({x["sku"] for x in ozon_expected.values()}) != 26
            or len({x["wb_nmID"] for x in wb_expected.values()}) != 29):
        raise RuntimeError("preflight_target_identity_not_unique")

    client = Client()
    state = {"started_at_utc": now(), "number": NUMBER, "source_sha256": SOURCE_SHA,
        "fsa_record_id": "17768504", "issue_date": ISSUE, "expire_date": EXPIRY,
        "preflight_targets": {"ozon": 26, "wb": 29}, "skipped_ozon_out_of_scope": [
            {"offer_id": x["offer_id"], "tnved": x["ozon_tnved"], "reason": x["ozon_blockers"]}
            for x in pre["targets"] if not x.get("ozon_safe")],
        "ozon_create_attempted": False, "ozon_bind_attempted": False,
        "wb_update_attempted": False, "local_source_deleted": False,
        "wb_review_left_pending": True, "phase": "fresh_prewrite_check"}
    save(STATE, state)

    # Verify current Ozon offer, PID/SKU, brand and code immediately before any create/bind.
    ozon_targets = fresh_ozon_targets(client, ozon_expected)
    exact_records = find_record(client)
    if len(exact_records) > 1:
        raise RuntimeError("duplicate_ozon_record_before_write")
    if exact_records:
        rec = exact_records[0]
        if (rec.get("type_code") != "declaration"
                or str(rec.get("issue_date") or "")[:10] != ISSUE
                or str(rec.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("ozon_record_metadata_changed_since_preflight")
    state.update({"phase": "ozon_prewrite_verified", "ozon_live_record_count": len(exact_records),
                  "ozon_live_target_count": len(ozon_targets)})
    save(STATE, state)
    try:
        ozon_result = ozon_upload_bind(client, ozon_targets, state)
    except Exception as exc:
        ozon_result = {"outcome": "ozon_stage_error", "error_type": type(exc).__name__}
        state.update({"ozon_error_type": type(exc).__name__, "phase": "ozon_stage_error_wb_continues"})
        save(STATE, state)
    state["ozon_result"] = {k: v for k, v in ozon_result.items() if k != "rows"}
    save(STATE, state)

    # WB is independent: fresh-read and preserve every writable card field before adding type-2 metadata.
    try:
        wb_updates, wb_before = fresh_wb_cards(client, wb_expected)
    except Exception as exc:
        state.update({"phase": "wb_fresh_prewrite_error", "wb_error_type": type(exc).__name__})
        save(STATE, state)
        raise
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": wb_before,
        "update_count": len(wb_updates), "already_exact_count": len(wb_expected) - len(wb_updates)})
    if wb_updates:
        payload_bytes = len(json.dumps(wb_updates, ensure_ascii=False, separators=(",", ":")).encode())
        if payload_bytes > 9_500_000:
            raise RuntimeError("wb_update_payload_exceeds_safe_limit")
        marker = hashlib.sha256(json.dumps(wb_updates, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "phase": "update_prepared",
                 "request_sha256": marker, "request_bytes": payload_bytes, "card_count": len(wb_updates)})
        state.update({"phase": "wb_update_outcome_pending", "wb_update_attempted": True,
                      "wb_update_payload_sha256": marker, "wb_update_cards": len(wb_updates)})
        save(STATE, state)
        try:
            wb_response = client.call("wb", "/content/v2/cards/update", wb_updates, mutation=True)
            state["wb_update_response"] = wb_response
            journal({"at": now(), "platform": "wb", "phase": "update_response", "response": wb_response})
        except Exception as exc:
            state["wb_update_error_type"] = type(exc).__name__
            journal({"at": now(), "platform": "wb", "phase": "update_outcome_uncertain",
                     "error_type": type(exc).__name__})
        save(STATE, state)

    wb_rows = []
    for offer, expected in sorted(wb_expected.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "nmID": expected["wb_nmID"], "status": "missing_or_duplicate"})
            continue
        card = cards[0]
        docs = [x for x in ((card.get("documents") or {}).get("items") or [])
                if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in docs if str(x.get("type")) == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        unchanged = (offer not in wb_before
                     or comparable_card(wb_before[offer]) == comparable_card(card))
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
            "exact_metadata": len(docs) == len(exact) == 1, "non_document_fields_unchanged": unchanged,
            "status": "verified_exact" if len(docs) == len(exact) == 1 and unchanged else "readback_mismatch",
            "verdict": (exact[0].get("verdict") if exact else None)})
    wb_statuses = collections.Counter(x["status"] for x in wb_rows)
    wb_verdicts = collections.Counter()
    for row in wb_rows:
        if row["status"] != "verified_exact":
            continue
        v = row.get("verdict") or {}
        wb_verdicts["valid" if v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid"
                    else "invalid" if v.get("verified") is True and v.get("status") == 2 else "pending_or_missing"] += 1

    ozon_record = None
    ozon_binding_rows = []
    ozon_statuses = {}
    try:
        records = find_record(client)
        if len(records) == 1:
            ozon_record = records[0]
            bindings = client.ozon_bindings(int(ozon_record["certificate_id"]))
            by_pid = {str(x.get("product_id") or ""): x for x in bindings}
            for offer, t in sorted(ozon_targets.items()):
                b = by_pid.get(t["product_id"])
                ozon_binding_rows.append({"offer_id": offer, "product_id": t["product_id"], "sku": t["sku"],
                    "exact_visible": bool(b and str(b.get("sku") or "") == t["sku"]),
                    "status": (b or {}).get("product_status_code")})
            ozon_statuses = dict(collections.Counter(str(x["status"] or "unknown")
                for x in ozon_binding_rows if x["exact_visible"]))
    except Exception as exc:
        state["ozon_readback_error_type"] = type(exc).__name__

    readback = {"checked_at_utc": now(), "read_only": True, "number": NUMBER,
        "source_sha256": SOURCE_SHA, "ozon_record": ozon_record,
        "ozon_targets": len(ozon_targets),
        "ozon_exact_visible": sum(x["exact_visible"] for x in ozon_binding_rows),
        "ozon_binding_status_counts": ozon_statuses, "ozon_bindings": ozon_binding_rows,
        "wb_targets": len(wb_expected), "wb_update_attempted": bool(wb_updates),
        "wb_exact_cards": wb_statuses.get("verified_exact", 0), "wb_card_status_counts": dict(wb_statuses),
        "wb_verdict_counts": dict(wb_verdicts), "wb_review_left_pending": True,
        "wb_cards": wb_rows, "local_source_deleted": False}
    save(READBACK, readback)
    state.update({"phase": "crossplatform_readback_complete", "ozon_exact_visible": readback["ozon_exact_visible"],
        "ozon_binding_status_counts": ozon_statuses, "wb_exact_cards": readback["wb_exact_cards"],
        "wb_card_status_counts": dict(wb_statuses), "wb_verdict_counts": dict(wb_verdicts),
        "wb_review_left_pending": True, "local_source_deleted": False, "finished_at_utc": now()})
    save(STATE, state)
    print(json.dumps({k: v for k, v in state.items() if k not in ("wb_update_response", "ozon_result")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
