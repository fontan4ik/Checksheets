from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
sys.path.insert(0, str(API))
from api_client import Client, digest, now  # noqa: E402
import run_all_found_certificates_20261014 as runner  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import (  # noqa: E402
    comparable_card, copy_documents, doc_key, norm_number, wb_datetime,
)

NUMBER = "РОСС RU.32079.04СПБ1.ОС17.90089"
ISSUE = "2025-12-01"
EXPIRY = "2028-11-30"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/8D4F02314DBE404FA8A115C777042CE4.pdf"
SOURCE_SHA256 = "0329b97077ca2ab0f41a753c9cc53ffcd117f873e6f0b544b24dfde25a6213a4"
STATE = HERE / "arlight_0123651_exact_two_execution_20261024.json"
JOURNAL = HERE / "arlight_0123651_exact_two_mutation_journal_20261024.jsonl"
TARGETS = [
    {"offer_id": "030022-1", "product_id": "6357812307", "sku": "5814249908", "nmID": "1605490381"},
    {"offer_id": "031060-1", "product_id": "6357812329", "sku": "5814250662", "nmID": "1605490382"},
]
ALLOWED_TNVED = {"9405110039"}


def save(state: dict) -> None:
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATE)


def journal(row: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now(), **row}, ensure_ascii=False) + "\n")
        stream.flush()


def norm(value: object) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", str(value or "").casefold())


def list_ozon_certificates(client: Client) -> list[dict]:
    rows = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_invalid")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
    raise RuntimeError("ozon_certificate_list_page_limit")


def live_ozon_targets(client: Client) -> list[dict]:
    product_rows = client.call("ozon", "/v3/product/info/list", {
        "product_id": [int(x["product_id"]) for x in TARGETS],
    }).get("items") or []
    attr_rows = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [x["offer_id"] for x in TARGETS]}, "limit": len(TARGETS),
    }).get("result") or []
    by_pid = {str(x.get("product_id") or x.get("id") or ""): x for x in product_rows}
    by_offer = {str(x.get("offer_id") or ""): x for x in attr_rows}
    if len(by_pid) != len(TARGETS) or len(by_offer) != len(TARGETS):
        raise RuntimeError("ozon_target_readback_incomplete")
    refreshed = []
    for target in TARGETS:
        product = by_pid.get(target["product_id"])
        attrs = by_offer.get(target["offer_id"])
        if (not product or not attrs or str(product.get("offer_id")) != target["offer_id"]
                or str(product.get("sku")) != target["sku"] or product.get("is_archived") is not False):
            raise RuntimeError("ozon_target_identity_changed:" + target["offer_id"])
        values = {str(x.get("id")): x for x in attrs.get("attributes") or []}
        brand = [str(x.get("value") or "").strip() for x in (values.get("85") or {}).get("values") or []]
        tnved = sorted({str(x.get("value") or "").split(" - ", 1)[0].strip()
                        for x in (values.get("22232") or {}).get("values") or []
                        if str(x.get("value") or "").strip()})
        if brand != ["Arlight"] or set(tnved) != ALLOWED_TNVED:
            raise RuntimeError("ozon_target_scope_changed:" + target["offer_id"])
        refreshed.append({**target, "brand": brand, "tnved": tnved, "name": product.get("name")})
    return refreshed


def exact_record(rows: list[dict]) -> dict | None:
    matches = [x for x in rows if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if len(matches) > 1:
        raise RuntimeError("duplicate_ozon_number_records")
    if not matches:
        return None
    record = matches[0]
    if (record.get("type_code") != "certificate_of_conformity"
            or str(record.get("accordance_type_code") or "").casefold() != "national"
            or str(record.get("issue_date") or "")[:10] != ISSUE
            or str(record.get("expire_date") or "")[:10] != EXPIRY):
        raise RuntimeError("existing_ozon_record_metadata_conflict")
    return record


def upload_ozon(client: Client, targets: list[dict], state: dict) -> None:
    record = exact_record(list_ozon_certificates(client))
    if record is None:
        options = client.call("ozon", "/v2/product/certification/options", {})
        variants = {x.get("value") for option in options.get("option") or []
                    if option.get("name") == "CERTIFICATE_TYPE" for x in option.get("variants") or []}
        if "CERTIFICATE_OF_CONFORMITY" not in variants:
            raise RuntimeError("ozon_certificate_type_not_supported")
        params = client.call("ozon", "/v2/product/certification/params", {"params": {
            "certificate_type": "CERTIFICATE_OF_CONFORMITY", "certificate_country": "RU",
            "accordance_type": "NATIONAL", "name": "Добровольный сертификат пожарной безопасности",
            "number": NUMBER, "issue_date": wb_datetime(ISSUE), "expired_date": {"date": {"day": 30, "month": 11, "year": 2028}},
            "skus": [x["sku"] for x in targets],
        }})
        param_names = {x.get("name") for x in params.get("params") or []}
        if not {"CERTIFICATE_TYPE", "CERTIFICATE_COUNTRY", "ACCORDANCE_TYPE", "NUMBER", "ISSUE_DATE", "EXPIRED_DATE"} <= param_names:
            raise RuntimeError("ozon_current_params_schema_incomplete")
        accordance_values = {v.get("value") for p in params.get("params") or []
                             if p.get("name") == "ACCORDANCE_TYPE" for v in p.get("variants") or []}
        if "NATIONAL" not in accordance_values:
            raise RuntimeError("ozon_national_accordance_not_supported")
        expiry = dt.date.fromisoformat(EXPIRY)
        payload = {"params": {
            "name": "Добровольный сертификат пожарной безопасности № " + NUMBER,
            "certificate_type": "CERTIFICATE_OF_CONFORMITY", "certificate_country": "RU",
            "accordance_type": "NATIONAL", "number": NUMBER,
            "issue_date": wb_datetime(ISSUE),
            "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
            "skus": sorted(x["sku"] for x in targets), "product_type": "UNKNOWN",
            "link_to_registry": "https://cert.sert-reestr.net/fire_safety_097371",
            "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"), "name": SOURCE.name}],
        }}
        if digest(SOURCE) != SOURCE_SHA256:
            raise RuntimeError("source_pdf_hash_changed")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) >= 15_000_000:
            raise RuntimeError("ozon_payload_too_large")
        journal({"platform": "ozon", "phase": "prepared", "endpoint": "/v2/product/certificate/create",
                 "number": NUMBER, "source_sha256": SOURCE_SHA256, "payload_sha256": hashlib.sha256(encoded).hexdigest(),
                 "target_skus": [x["sku"] for x in targets]})
        state["ozon_phase"] = "create_sent"
        save(state)
        try:
            response = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
            journal({"platform": "ozon", "phase": "response", "endpoint": "/v2/product/certificate/create",
                     "number": NUMBER, "response": response})
        except Exception as exc:
            journal({"platform": "ozon", "phase": "uncertain", "endpoint": "/v2/product/certificate/create",
                     "number": NUMBER, "error_type": type(exc).__name__})
            state["ozon_phase"] = "create_uncertain_reconciling_no_retry"
            save(state)
            response = None
        if response is not None:
            params_state = [x.get("state") for x in response.get("params") or [] if isinstance(x, dict)]
            if response.get("status") != "COMPLETED" or (params_state and set(params_state) != {"VALID"}):
                state["ozon_phase"] = "create_incomplete_skip_binding"
                state["ozon_create_response"] = response
                save(state)
                return
        record = None
        for attempt in range(8):
            record = exact_record(list_ozon_certificates(client))
            if record is not None:
                break
            if attempt < 7:
                import time
                time.sleep(2)
        if record is None:
            state["ozon_phase"] = "create_not_visible_skip_no_retry"
            state["ozon_create_response"] = response
            save(state)
            return
        state["ozon_certificate_id"] = str(record.get("certificate_id"))
        state["ozon_created_or_reconciled"] = True
        state["ozon_create_response"] = response
        save(state)
    if record.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}:
        state["ozon_phase"] = "record_rejected_skip_binding"
        state["ozon_status"] = record.get("status_code")
        save(state)
        return
    cid = int(record["certificate_id"])
    bindings = client.ozon_bindings(cid)
    by_pid = {str(x.get("product_id")): x for x in bindings}
    known = {x["product_id"]: x for x in targets}
    if set(by_pid) - set(known):
        raise RuntimeError("ozon_record_has_out_of_scope_binding")
    missing = [x for x in targets if x["product_id"] not in by_pid]
    if missing:
        request = {"certificate_id": cid, "skus": sorted(x["sku"] for x in missing)}
        journal({"platform": "ozon", "phase": "prepared", "endpoint": "/v1/product/certificate/bind",
                 "certificate_id": cid, "skus": request["skus"]})
        state["ozon_phase"] = "bind_sent"
        save(state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", request, mutation=True)
            journal({"platform": "ozon", "phase": "response", "endpoint": "/v1/product/certificate/bind",
                     "certificate_id": cid, "response": response})
        except Exception as exc:
            journal({"platform": "ozon", "phase": "uncertain", "endpoint": "/v1/product/certificate/bind",
                     "certificate_id": cid, "error_type": type(exc).__name__})
        bindings = client.ozon_bindings(cid)
        by_pid = {str(x.get("product_id")): x for x in bindings}
    state["ozon_bindings"] = [{"offer_id": x["offer_id"], "sku": x["sku"],
                               "present": bool(by_pid.get(x["product_id"])
                                               and str(by_pid[x["product_id"]].get("sku")) == x["sku"]),
                               "status": (by_pid.get(x["product_id"]) or {}).get("product_status_code")}
                              for x in targets]
    state["ozon_status"] = record.get("status_code")
    state["ozon_phase"] = "ozon_readback_complete"
    save(state)


def update_wb(client: Client, targets: list[dict], state: dict) -> None:
    wanted = {"type": 1, "number": NUMBER, "startDate": wb_datetime(ISSUE),
              "endDate": wb_datetime(EXPIRY), "isEndless": False}
    before = {}
    updates = []
    for target in targets:
        cards = client.wb_cards(target["offer_id"])
        exact = [x for x in cards if str(x.get("nmID")) == target["nmID"]
                 and str(x.get("vendorCode")) == target["offer_id"]]
        if len(exact) != 1:
            state.setdefault("wb_skips", []).append({"offer_id": target["offer_id"], "reason": "missing_or_ambiguous_card"})
            continue
        card = exact[0]
        if card.get("brand") != "Arlight":
            state.setdefault("wb_skips", []).append({"offer_id": target["offer_id"], "reason": "brand_changed"})
            continue
        tnved = set()
        for characteristic in card.get("characteristics") or []:
            name = str(characteristic.get("name") or "").casefold()
            if "тнвэд" in name or "тнвед" in name:
                value = characteristic.get("value")
                for raw in value if isinstance(value, list) else [value]:
                    if raw:
                        tnved.add(str(raw).split(" - ", 1)[0].strip())
        if tnved != ALLOWED_TNVED:
            state.setdefault("wb_skips", []).append({"offer_id": target["offer_id"], "reason": "tnved_changed", "tnved": sorted(tnved)})
            continue
        docs = copy_documents(card)
        existing = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        if existing:
            if all(doc_key(x) == doc_key(wanted)
                   and str(x.get("startDate", ""))[:10] == ISSUE
                   and str(x.get("endDate", ""))[:10] == EXPIRY for x in existing):
                state.setdefault("wb_already_exact", []).append(target["offer_id"])
                before[target["offer_id"]] = card
                continue
            state.setdefault("wb_skips", []).append({"offer_id": target["offer_id"], "reason": "existing_metadata_conflict"})
            continue
        payload = runner.merge_wb(card, [wanted])
        if payload is None:
            state.setdefault("wb_already_exact", []).append(target["offer_id"])
            before[target["offer_id"]] = card
            continue
        before[target["offer_id"]] = card
        updates.append((target, payload))
    if updates:
        journal({"platform": "wb", "phase": "prepared", "endpoint": "/content/v2/cards/update",
                 "cards": [x[0]["nmID"] for x in updates], "number": NUMBER})
        state["wb_phase"] = "update_sent"
        save(state)
        try:
            response = client.call("wb", "/content/v2/cards/update", [x[1] for x in updates], mutation=True)
            journal({"platform": "wb", "phase": "response", "endpoint": "/content/v2/cards/update",
                     "response": response, "number": NUMBER})
            state["wb_response"] = response
        except Exception as exc:
            journal({"platform": "wb", "phase": "uncertain", "endpoint": "/content/v2/cards/update",
                     "error_type": type(exc).__name__, "number": NUMBER})
            state["wb_response_uncertain"] = True
        state["wb_phase"] = "readback_after_update"
        save(state)
    readback = []
    for target in targets:
        card = next((x for x in client.wb_cards(target["offer_id"])
                     if str(x.get("nmID")) == target["nmID"] and x.get("vendorCode") == target["offer_id"]), None)
        docs = copy_documents(card or {})
        found = [x for x in docs if norm_number(x.get("number")) == norm_number(NUMBER)]
        exact = [x for x in found if doc_key(x) == doc_key(wanted)
                 and str(x.get("startDate", ""))[:10] == ISSUE
                 and str(x.get("endDate", ""))[:10] == EXPIRY]
        preserved = bool(card and target["offer_id"] in before
                         and comparable_card(card) == comparable_card(before[target["offer_id"]]))
        readback.append({"offer_id": target["offer_id"], "nmID": target["nmID"],
                         "exact_document_visible": len(exact) == 1, "existing_conflict_count": len(found) - len(exact),
                         "other_card_fields_preserved": preserved,
                         "verdict": exact[0].get("verdict") if exact else None})
    state["wb_readback"] = readback
    state["wb_phase"] = "wb_readback_complete"
    state["local_pdf_deleted"] = False
    save(state)


def main() -> None:
    if STATE.exists() or JOURNAL.exists():
        raise RuntimeError("execution state exists; reconcile live state before any retry")
    if not SOURCE.is_file() or digest(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("source PDF missing or hash changed")
    state = {"started_at": now(), "number": NUMBER, "source_sha256": SOURCE_SHA256,
             "source_is_voluntary": True, "source_does_not_replace_mandatory_certification": True,
             "targets": TARGETS, "local_pdf_deleted": False}
    save(state)
    client = Client()
    targets = live_ozon_targets(client)
    state["ozon_targets_refreshed"] = targets
    state["ozon_number_absent_before_write"] = exact_record(list_ozon_certificates(client)) is None
    if not state["ozon_number_absent_before_write"]:
        raise RuntimeError("unexpected exact Ozon record appeared; reconcile before write")
    save(state)
    upload_ozon(client, targets, state)
    update_wb(client, targets, state)
    state["finished_at"] = now()
    state["phase"] = "complete_readback"
    save(state)
    print(json.dumps({k: state.get(k) for k in (
        "phase", "number", "ozon_phase", "ozon_certificate_id", "ozon_status", "ozon_bindings",
        "wb_phase", "wb_response", "wb_readback", "wb_skips", "wb_already_exact", "local_pdf_deleted",
        "source_does_not_replace_mandatory_certification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
