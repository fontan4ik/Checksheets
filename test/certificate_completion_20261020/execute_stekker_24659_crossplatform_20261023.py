#!/usr/bin/env python3
"""Upload and bind STEKKER BGS declaration 24659/26 on both marketplaces."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from apply_arlight_52132_wb_20261020 import code_values  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number, wb_datetime  # noqa: E402
from run_all_found_certificates_20261014 import merge_wb  # noqa: E402

NUMBER = "ЕАЭС N RU Д-CN.РА01.В.24659/26"
ISSUE = "2026-01-22"
EXPIRY = "2031-01-21"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/21081324/common"
SIGNED = ROOT / "output_to_user/certificates/additional_search/brand_research/stekker/residual_2026_10_02/docs/declaration_24659_26_feron_official.jpg"
SIGNED_SHA = "05fe178706e69de44bb0a18752ec5ca7f78599978e65d58bf528cf235321b5dd"
EXTRACT = ROOT / "output_to_user/certificates/additional_search/brand_research/stekker/residual_2026_10_02/docs/declaration_24659_26_fsa_official_extract.pdf"
EXTRACT_SHA = "4ce605742413da9171d1b758ff6a4552ff12ea852fb207d64f0b569b46700cd2"
PREFLIGHT = HERE / "stekker_24659_crossplatform_preflight_20261023.json"
STATE = HERE / "stekker_24659_execution_20261023.json"
JOURNAL = HERE / "stekker_24659_mutation_journal_20261023.jsonl"
WB_BEFORE = HERE / "stekker_24659_wb_before_20261023.json"
READBACK = HERE / "stekker_24659_crossplatform_readback_20261023.json"
EXPECTED = {
    "50282-1": {"product_id": "4659687060", "sku": "4368299310", "wb_nmID": "1055655750"},
    "50283-1": {"product_id": "4659599904", "sku": "4368226578", "wb_nmID": "1055646340"},
    "50284-1": {"product_id": "4659755505", "sku": "4368361608", "wb_nmID": "1055651057"},
}


def save(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def journal(value: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


def attr_values(row: dict, ident: int) -> list[str]:
    by = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(v.get("value") or "").strip() for v in (by.get(str(ident)) or {}).get("values") or []
            if str(v.get("value") or "").strip()]


def live_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        body = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})
        result = body.get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def exact_records(client: Client) -> list[dict]:
    key = norm_number(NUMBER)
    return [row for row in live_certificates(client) if norm_number(row.get("certificate_number")) == key]


def ozon_targets(client: Client) -> dict[str, dict]:
    offers = sorted(EXPECTED)
    p_rows, a_rows = {}, {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        for row in client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []:
            p_rows.setdefault(str(row.get("offer_id") or ""), []).append(row)
        for row in client.call("ozon", "/v4/product/info/attributes", {
                "filter": {"offer_id": batch}, "limit": len(batch)}).get("result") or []:
            a_rows.setdefault(str(row.get("offer_id") or ""), []).append(row)
    if set(p_rows) != set(offers) or set(a_rows) != set(offers):
        raise RuntimeError("ozon_offer_set_changed_or_incomplete")
    targets = {}
    for offer, old in EXPECTED.items():
        if len(p_rows[offer]) != 1 or len(a_rows[offer]) != 1:
            raise RuntimeError("ozon_offer_missing_or_ambiguous:" + offer)
        product, attributes = p_rows[offer][0], a_rows[offer][0]
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        brand = [x.casefold() for x in attr_values(attributes, 85)]
        tnved = {x.split(" - ", 1)[0].strip() for x in attr_values(attributes, 22232)}
        if (product.get("is_archived") is not False or product_id != old["product_id"]
                or sku != old["sku"] or brand != ["stekker"] or tnved != {"4202929800"}):
            raise RuntimeError("ozon_live_identity_brand_or_tnved_changed:" + offer)
        targets[offer] = {"offer_id": offer, "product_id": product_id, "sku": sku,
                          "name": product.get("name"), "tnved": sorted(tnved)}
    return targets


def wb_updates(client: Client) -> tuple[list[dict], dict[str, dict]]:
    updates, before = [], {}
    wanted = {"type": 2, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
    for offer, old in sorted(EXPECTED.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            raise RuntimeError("wb_card_missing_or_ambiguous:" + offer)
        card = cards[0]
        if (str(card.get("nmID") or "") != old["wb_nmID"]
                or str(card.get("brand") or "").strip().casefold() != "stekker"):
            raise RuntimeError("wb_live_identity_or_brand_changed:" + offer)
        docs = ((card.get("documents") or {}).get("items") or [])
        same = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in same if str(x.get("type") or "") == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        if same and not (len(same) == len(exact) == 1):
            raise RuntimeError("wb_same_number_metadata_conflict:" + offer)
        if exact:
            continue
        payload = merge_wb(card, [wanted])
        if payload is None:
            raise RuntimeError("wb_merge_noop:" + offer)
        updates.append(payload)
        before[offer] = card
    return updates, before


def create_or_bind(client: Client, targets: dict[str, dict], state: dict) -> dict:
    matches = exact_records(client)
    if len(matches) > 1:
        raise RuntimeError("ozon_duplicate_record")
    record = matches[0] if matches else None
    if record and (record.get("type_code") != "declaration"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_metadata_conflict")
    create_response = None
    if record is None:
        expiry = dt.date.fromisoformat(EXPIRY)
        seed = targets[sorted(targets)[0]]
        params = {
            "name": "Декларация о соответствии № " + NUMBER,
            "certificate_type": "DECLARATION", "certificate_country": "RU",
            "accordance_type": "EAEU", "number": NUMBER,
            "issue_date": ISSUE + "T00:00:00Z",
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": [seed["sku"]], "product_type": "UNKNOWN",
            "files": [{"file_content": base64.b64encode(SIGNED.read_bytes()).decode("ascii"),
                       "name": SIGNED.name}],
            "link_to_registry": FSA_URL,
        }
        payload = {"params": params}
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
            raise RuntimeError("ozon_create_payload_too_large")
        marker = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal({"at": now(), "platform": "ozon", "phase": "create_prepared", "request_sha256": marker,
                 "seed_offer": seed["offer_id"], "seed_sku": seed["sku"]})
        state.update({"phase": "ozon_create_outcome_pending", "ozon_create_attempted": True,
                      "ozon_create_payload_sha256": marker, "ozon_seed_offer": seed["offer_id"]})
        save(STATE, state)
        try:
            create_response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            journal({"at": now(), "platform": "ozon", "phase": "create_response", "response": create_response})
        except Exception as exc:
            journal({"at": now(), "platform": "ozon", "phase": "create_outcome_uncertain",
                     "error_type": type(exc).__name__})
        for attempt in range(7):
            matches = exact_records(client)
            if matches or attempt == 6:
                break
            time.sleep(2)
        if len(matches) != 1:
            return {"outcome": "create_not_visible_no_bind", "create_response": create_response,
                    "exact_visible": 0, "binding_status_counts": {}}
        record = matches[0]
        parameter_states = [x.get("state") for x in (create_response or {}).get("params", []) if isinstance(x, dict)]
        if (record.get("type_code") != "declaration"
                or str(record.get("issue_date") or "")[:10] != ISSUE
                or str(record.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("created_ozon_record_metadata_conflict")
        if not create_response or create_response.get("status") != "COMPLETED" or not parameter_states or set(parameter_states) != {"VALID"}:
            return {"outcome": "record_visible_create_response_invalid_no_bind", "record": record,
                    "create_response": create_response, "exact_visible": 0, "binding_status_counts": {}}

    certificate_id = int(record["certificate_id"])
    target_by_pid = {x["product_id"]: x for x in targets.values()}
    bindings = client.ozon_bindings(certificate_id)
    by_pid = {str(x.get("product_id") or ""): x for x in bindings}
    if any(str(x.get("product_id") or "") not in target_by_pid for x in bindings):
        raise RuntimeError("ozon_existing_record_has_outside_bindings")
    for pid, row in by_pid.items():
        if str(row.get("sku") or "") != target_by_pid[pid]["sku"]:
            raise RuntimeError("ozon_existing_binding_sku_conflict")
    missing = [t for t in targets.values() if t["product_id"] not in by_pid]
    if missing:
        bind = {"certificate_id": certificate_id, "skus": sorted(x["sku"] for x in missing)}
        marker = hashlib.sha256(json.dumps(bind, sort_keys=True).encode()).hexdigest()
        journal({"at": now(), "platform": "ozon", "phase": "bind_prepared", "request_sha256": marker,
                 "certificate_id": certificate_id, "offers": sorted(x["offer_id"] for x in missing)})
        state.update({"phase": "ozon_bind_outcome_pending", "ozon_bind_attempted": True,
                      "ozon_bind_payload_sha256": marker, "ozon_bind_target_count": len(missing)})
        save(STATE, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", bind, mutation=True)
            journal({"at": now(), "platform": "ozon", "phase": "bind_response", "response": response})
            state["ozon_bind_response"] = response
        except Exception as exc:
            journal({"at": now(), "platform": "ozon", "phase": "bind_outcome_uncertain",
                     "error_type": type(exc).__name__})
            state["ozon_bind_error_type"] = type(exc).__name__
        save(STATE, state)
    final = client.ozon_bindings(certificate_id)
    final_by_pid = {str(x.get("product_id") or ""): x for x in final}
    rows = []
    for offer, target in sorted(targets.items()):
        binding = final_by_pid.get(target["product_id"])
        rows.append({"offer_id": offer, "product_id": target["product_id"], "sku": target["sku"],
                     "visible_exact": bool(binding and str(binding.get("sku") or "") == target["sku"]),
                     "status": (binding or {}).get("product_status_code")})
    return {"outcome": "bound_or_reconciled", "record": record, "record_status": record.get("status_code"),
            "certificate_id": certificate_id, "target_count": len(targets),
            "exact_visible": sum(x["visible_exact"] for x in rows),
            "binding_status_counts": dict(collections.Counter(str(x["status"] or "unknown") for x in rows if x["visible_exact"])),
            "rows": rows}


def main() -> None:
    if any(path.exists() for path in (STATE, JOURNAL, WB_BEFORE, READBACK)):
        raise RuntimeError("execution_artifact_exists_reconcile_before_retry")
    if hashlib.sha256(SIGNED.read_bytes()).hexdigest() != SIGNED_SHA or hashlib.sha256(EXTRACT.read_bytes()).hexdigest() != EXTRACT_SHA:
        raise RuntimeError("source_sha_mismatch")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if pre.get("read_only") is not True or pre.get("number") != NUMBER or pre.get("assignment_count") != 3:
        raise RuntimeError("preflight_identity_or_count_changed")
    state = {"started_at_utc": now(), "number": NUMBER, "issue_date": ISSUE, "expire_date": EXPIRY,
             "source_signed_jpg_sha256": SIGNED_SHA, "source_fsa_extract_sha256": EXTRACT_SHA,
             "fsa_record_id": "21081324", "sample_date_clause_present": True,
             "sample_date_from_act_found": False, "preflight_target_count": 3,
             "wb_review_left_pending": True, "local_source_deleted": False, "phase": "fresh_prewrite_check"}
    save(STATE, state)
    client = Client()
    targets = ozon_targets(client)
    existing = exact_records(client)
    if len(existing) > 1:
        raise RuntimeError("duplicate_ozon_record_before_write")
    if existing:
        rec = existing[0]
        if (rec.get("type_code") != "declaration" or str(rec.get("issue_date") or "")[:10] != ISSUE
                or str(rec.get("expire_date") or "")[:10] != EXPIRY):
            raise RuntimeError("ozon_record_conflict_before_write")
    state.update({"ozon_prewrite_targets": targets, "ozon_existing_record_count": len(existing),
                  "phase": "ozon_prewrite_verified"})
    save(STATE, state)
    try:
        ozon_result = create_or_bind(client, targets, state)
    except Exception as exc:
        ozon_result = {"outcome": "ozon_stage_error", "error_type": type(exc).__name__}
        state.update({"ozon_error_type": type(exc).__name__, "phase": "ozon_stage_error_wb_continues"})
        save(STATE, state)
    state["ozon_result"] = {k: v for k, v in ozon_result.items() if k != "rows"}
    state["ozon_rows"] = ozon_result.get("rows", [])
    save(STATE, state)

    updates, before = wb_updates(client)
    save(WB_BEFORE, {"checked_at_utc": now(), "read_only": True, "cards": before,
                     "update_count": len(updates), "already_exact_count": 3 - len(updates)})
    if updates:
        size = len(json.dumps(updates, ensure_ascii=False, separators=(",", ":")).encode())
        if size > 9_500_000:
            raise RuntimeError("wb_payload_too_large")
        marker = hashlib.sha256(json.dumps(updates, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        journal({"at": now(), "platform": "wb", "phase": "update_prepared", "request_sha256": marker,
                 "request_bytes": size, "card_count": len(updates)})
        state.update({"phase": "wb_update_outcome_pending", "wb_update_attempted": True,
                      "wb_update_payload_sha256": marker, "wb_update_cards": len(updates)})
        save(STATE, state)
        try:
            response = client.call("wb", "/content/v2/cards/update", updates, mutation=True)
            state["wb_update_response"] = response
            journal({"at": now(), "platform": "wb", "phase": "update_response", "response": response})
        except Exception as exc:
            state["wb_update_error_type"] = type(exc).__name__
            journal({"at": now(), "platform": "wb", "phase": "update_outcome_uncertain",
                     "error_type": type(exc).__name__})
        save(STATE, state)

    wb_rows = []
    for offer, expected in sorted(EXPECTED.items()):
        cards = [x for x in client.wb_cards(offer) if str(x.get("vendorCode") or "") == offer]
        if len(cards) != 1:
            wb_rows.append({"offer_id": offer, "nmID": expected["wb_nmID"], "exact_visible": False,
                            "error": "missing_or_duplicate_card"})
            continue
        card = cards[0]
        items = (card.get("documents") or {}).get("items") or []
        exact = [x for x in items if norm_number(x.get("number")) == norm_number(NUMBER)
                 and str(x.get("type") or "") == "2"
                 and str(x.get("startDate") or "")[:10] == ISSUE
                 and str(x.get("endDate") or "")[:10] == EXPIRY
                 and x.get("isEndless") is False]
        verdicts = [(x.get("verdict") or {}) for x in exact]
        wb_rows.append({"offer_id": offer, "nmID": str(card.get("nmID") or ""),
                        "exact_visible": len(exact) == 1,
                        "verdicts": verdicts,
                        "review_status": "valid" if any(v.get("verified") is True and v.get("status") == 1 and v.get("reason") == "valid" for v in verdicts)
                        else "pending_or_verdict_absent" if not any(v.get("status") not in (None, 1) or v.get("reason") not in (None, "", "valid") for v in verdicts)
                        else "rejected_or_invalid"})
    report = {"checked_at_utc": now(), "number": NUMBER, "ozon": ozon_result,
              "wb": {"target_count": 3, "exact_metadata_count": sum(x.get("exact_visible") is True for x in wb_rows),
                     "rows": wb_rows, "review_status_counts": dict(collections.Counter(x.get("review_status", "missing") for x in wb_rows))},
              "sample_date_clause_present": True, "date_in_sampling_act_found": False,
              "local_files_deleted": False, "sources_retained": [str(SIGNED), str(EXTRACT)]}
    save(READBACK, report)
    state.update({"phase": "finished_with_readback", "finished_at_utc": now(),
                  "readback_file": str(READBACK), "wb_exact_metadata_count": report["wb"]["exact_metadata_count"]})
    save(STATE, state)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
