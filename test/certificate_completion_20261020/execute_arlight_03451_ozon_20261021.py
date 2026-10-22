"""Create and bind Arlight certificate 03451/22 on exact in-scope Ozon offers."""
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
from api_client import Client, now, digest  # noqa: E402
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

PREFLIGHT = HERE / "arlight_03451_preflight_live_20261021.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/772DD20BAEF0AD4FA297663655BFAC3A.pdf"
STATE = HERE / "arlight_03451_ozon_execution_20261021.json"
NUMBER = "ЕАЭС RU С-HK.НА46.В.03451/22"
ISSUE = "2022-04-16"
EXPIRY = "2027-04-15"
TNVED = "8504408300"
EXPECTED = 462


def save(value: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def records(client: Client) -> list[dict]:
    out = []
    page = 1
    pages = 1
    seen = set()
    while page <= pages:
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100
        }).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_missing")
        for row in batch:
            cid = int(row.get("certificate_id") or 0)
            if not cid or cid in seen:
                raise RuntimeError("ozon_certificate_id_missing_or_duplicate")
            seen.add(cid)
        out.extend(batch)
        pages = int(result.get("page_count") or page)
        page += 1
    return out


def attr_values(row: dict, attr_id: int) -> list[str]:
    for attr in row.get("attributes") or []:
        if str(attr.get("id")) == str(attr_id):
            return [str(v.get("value")) for v in attr.get("values") or []
                    if v.get("value") not in (None, "")]
    return []


def exact_absence(client: Client) -> tuple[bool, int, dict]:
    payload = {"certificate_number": NUMBER}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    entry = {"started_at": now(), "platform": "ozon", "path": "/v1/product/certificate/info",
             "mutation": False, "request_sha256": hashlib.sha256(encoded).hexdigest(),
             "request_bytes": len(encoded)}
    log = API / "api_calls.jsonl"
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**entry, "phase": "prepared"}, ensure_ascii=False) + "\n")
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=encoded, headers=client.ozon_headers, timeout=(15, 60))
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": True}
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**entry, "phase": "response", "http_status": response.status_code,
                                 "body": body, "finished_at": now()}, ensure_ascii=False) + "\n")
    absent = (response.status_code == 404 and isinstance(body, dict) and body.get("code") == 5
              and "not found" in str(body.get("message") or "").casefold()
              and NUMBER in str(body.get("message") or ""))
    return absent, response.status_code, body


def main() -> None:
    if STATE.exists():
        raise RuntimeError("ozon_execution_state_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (not pre.get("ozon_exact_record_absence_confirmed")
            or pre.get("ozon_exact_record_preexisting") is not False
            or pre.get("eligible_ozon_targets") != EXPECTED
            or pre.get("ozon_scope_counts") != {"in_scope": EXPECTED}
            or pre.get("ozon_targets_checked") != EXPECTED):
        raise RuntimeError("ozon_preflight_not_fully_eligible")
    if digest(SOURCE) != pre.get("source_pdf_sha256"):
        raise RuntimeError("source_pdf_hash_changed")
    targets = pre.get("ozon_targets") or []
    offers = {str(x.get("offer_id") or "") for x in targets}
    products = {str(x.get("product_id") or "") for x in targets}
    skus = {str(x.get("sku") or "") for x in targets}
    if len(targets) != EXPECTED or len(offers) != EXPECTED or len(products) != EXPECTED or len(skus) != EXPECTED or "" in skus:
        raise RuntimeError("ozon_target_identity_not_unique")

    client = Client()
    # Refresh product identity and regulatory attributes immediately before create.
    current_by_id = {}
    product_ids = [x["product_id"] for x in targets]
    for offset in range(0, len(product_ids), 500):
        batch = product_ids[offset:offset + 500]
        rows = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch]
        }).get("items")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_product_refresh_missing")
        for row in rows:
            pid = str(row.get("product_id") or row.get("id") or "")
            if pid not in batch or pid in current_by_id:
                raise RuntimeError("ozon_product_refresh_identity_mismatch")
            current_by_id[pid] = row
    if set(current_by_id) != set(product_ids):
        raise RuntimeError("ozon_product_refresh_incomplete")
    attrs_by_offer = {}
    offer_list = sorted(offers)
    for offset in range(0, len(offer_list), 100):
        batch = offer_list[offset:offset + 100]
        rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_attribute_refresh_missing")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in attrs_by_offer:
                raise RuntimeError("ozon_attribute_refresh_identity_mismatch")
            attrs_by_offer[offer] = row
    if set(attrs_by_offer) != offers:
        raise RuntimeError("ozon_attribute_refresh_incomplete")
    for target in targets:
        pid, offer = target["product_id"], target["offer_id"]
        detail, attr = current_by_id[pid], attrs_by_offer[offer]
        brands = attr_values(attr, 85)
        raw_codes = attr_values(attr, 22232)
        codes = sorted({v.split(" - ", 1)[0].strip() for v in raw_codes if v.strip()})
        identity = (str(detail.get("offer_id") or "") == offer
                    and str(detail.get("product_id") or detail.get("id") or "") == pid
                    and str(detail.get("sku") or "") == target["sku"]
                    and str(attr.get("offer_id") or "") == offer
                    and str(attr.get("id") or attr.get("product_id") or "") == pid
                    and detail.get("is_archived") is False)
        if (not identity or len(brands) != 1 or brands[0].strip().casefold() != "arlight"
                or codes != [TNVED]):
            raise RuntimeError("ozon_target_changed_before_create:" + offer)

    existing = [x for x in records(client)
                if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if existing:
        raise RuntimeError("normalized_ozon_record_exists_before_create:" + ",".join(
            str(x.get("certificate_id")) for x in existing))
    absent, http_status, absence_body = exact_absence(client)
    if not absent:
        raise RuntimeError(f"ozon_exact_record_absence_no_longer_confirmed:{http_status}")

    state = {"started_at": now(), "phase": "preflight_verified", "number": NUMBER,
             "certificate_id": None, "target_count": EXPECTED, "source_sha256": digest(SOURCE),
             "exact_lookup_http_status": http_status, "exact_lookup_body": absence_body,
             "create_sent": False, "bind_batches": [], "local_file_deleted": False}
    save(state)
    expiry = dt.date.fromisoformat(EXPIRY)
    params = {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [targets[0]["sku"]], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
    }
    payload = {"params": params}
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
        raise RuntimeError("ozon_create_payload_too_large")
    state.update(phase="ozon_create_prepared", create_sent=True,
                 seed_offer_id=targets[0]["offer_id"], seed_sku=targets[0]["sku"])
    save(state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", payload, mutation=True)
    except Exception as exc:
        state.update(phase="ozon_create_uncertain", error_type=type(exc).__name__, updated_at=now())
        save(state)
        raise RuntimeError("ozon_create_uncertain_reconcile_live_before_retry") from None
    states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    cert_id = int(created.get("certificate_id") or 0)
    state.update(create_response=created, certificate_id=cert_id, updated_at=now())
    if not cert_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        state.update(phase="ozon_create_not_validated")
        save(state)
        raise RuntimeError("ozon_create_response_not_fully_validated")
    state.update(phase="ozon_created_response_valid")
    save(state)

    info = {}
    for attempt in range(8):
        try:
            info = client.call("ozon", "/v1/product/certificate/info", {
                "certificate_number": NUMBER
            }).get("result") or {}
            break
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc) or attempt == 7:
                state.update(phase="ozon_info_readback_failed", error_type=type(exc).__name__, updated_at=now())
                save(state)
                raise
            time.sleep(2)
    if (str(info.get("certificate_id")) != str(cert_id)
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or info.get("type_code") != "certificate_of_conformity"
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or str(info.get("accordance_type_code", "")).upper() != "EAEU"
            or info.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        state.update(phase="ozon_metadata_conflict", certificate_info=info, updated_at=now())
        save(state)
        raise RuntimeError("ozon_live_document_metadata_conflict")

    bindings = client.ozon_bindings(cert_id)
    by_id = {str(x.get("product_id")): x for x in bindings}
    missing = []
    target_by_id = {t["product_id"]: t for t in targets}
    outside = set(by_id) - set(target_by_id)
    if outside:
        raise RuntimeError("seed_binding_contains_outside_product_ids")
    for target in targets:
        binding = by_id.get(target["product_id"])
        if binding and str(binding.get("sku")) != target["sku"]:
            raise RuntimeError("ozon_binding_identity_conflict:" + target["offer_id"])
        if not binding:
            missing.append(target["sku"])
    state.update(phase="ozon_binding", certificate_info=info, binding_count_before=len(bindings),
                 missing_binding_count=len(missing))
    save(state)
    for offset in range(0, len(missing), 100):
        batch = missing[offset:offset + 100]
        response = client.call("ozon", "/v1/product/certificate/bind", {
            "certificate_id": cert_id, "skus": batch
        }, mutation=True)
        state["bind_batches"].append({"count": len(batch), "result": response.get("result")})
        state["updated_at"] = now()
        save(state)
        if response.get("result") is not True:
            state.update(phase="ozon_bind_rejected")
            save(state)
            raise RuntimeError("ozon_bind_not_accepted")

    final_bindings = client.ozon_bindings(cert_id)
    by_id = {str(x.get("product_id")): x for x in final_bindings}
    status_counts = collections.Counter()
    rows = []
    for target in targets:
        binding = by_id.get(target["product_id"])
        okay = bool(binding and str(binding.get("sku")) == target["sku"])
        status = str(binding.get("product_status_code")) if okay else None
        rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                     "sku": target["sku"], "bound": okay, "status": status})
        if okay:
            status_counts[status or "unknown"] += 1
    outside = sorted(set(by_id) - set(target_by_id))
    missing_pairs = [x["offer_id"] for x in rows if not x["bound"]]
    if missing_pairs or outside or len(by_id) != EXPECTED:
        state.update(phase="ozon_binding_readback_incomplete", missing_offers=missing_pairs,
                     outside_product_ids=outside, binding_row_count=len(final_bindings), updated_at=now())
        save(state)
        raise RuntimeError("ozon_binding_readback_incomplete")
    state.update(phase="ozon_verified_complete", binding_count=len(final_bindings),
                 verified_target_pairs=len(rows), binding_status_counts=dict(status_counts),
                 updated_at=now(), local_file_deleted=False)
    save(state)
    print(json.dumps({"phase": state["phase"], "certificate_id": cert_id,
                      "certificate_status": info.get("status_code"),
                      "verified_target_pairs": len(rows),
                      "binding_status_counts": dict(status_counts),
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
