"""Upload Arlight declaration 46711/26 and bind the seven exact connectors."""
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

PREFLIGHT = HERE / "arlight_46711_preflight_live_20261021.json"
STATE = HERE / "arlight_46711_ozon_execution_20261021.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/97331E1740F80745A33F67528E33A9AB.pdf"
NUMBER = "ЕАЭС N RU Д-HK.РА01.В.46711/26"
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/21106697"


def save(value: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(STATE)


def list_certificates(client: Client) -> list[dict]:
    records = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_missing")
        records.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return records
        page += 1


def tnved_values(attr: dict) -> list[str]:
    attrs = {str(a.get("id")): a for a in attr.get("attributes") or []}
    raw = [str(v.get("value") or "") for v in (attrs.get("22232") or {}).get("values") or []]
    return sorted({x.split(" - ", 1)[0].strip() for x in raw if x.strip()})


def main() -> None:
    if STATE.exists():
        raise RuntimeError("ozon_execution_state_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    if (not pre.get("eligible_for_upload") or pre.get("unique_exact_connector_offers") != 7
            or pre.get("ozon_target_count") != 7 or pre.get("ozon_record_matches") != 0
            or pre.get("ozon_exact_info_absent") is not True):
        raise RuntimeError("46711_preflight_not_eligible")
    if digest(SOURCE) != pre.get("source_pdf_sha256"):
        raise RuntimeError("source_pdf_hash_changed")
    targets = pre["ozon_targets"]
    if len({x["offer_id"] for x in targets}) != 7 or len({x["product_id"] for x in targets}) != 7 or len({x["sku"] for x in targets}) != 7:
        raise RuntimeError("ozon_connector_targets_not_unique")

    client = Client()
    # Refresh exact product identities and brand/model before the create call.
    ids = [x["product_id"] for x in targets]
    details = {}
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        rows = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch]}).get("items")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_product_refresh_missing")
        for row in rows:
            pid = str(row.get("product_id") or row.get("id") or "")
            if pid not in batch or pid in details:
                raise RuntimeError("ozon_product_refresh_identity_mismatch")
            details[pid] = row
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": [x["offer_id"] for x in targets]}, "limit": len(targets)
    }).get("result")
    if not isinstance(attrs, list) or len(attrs) != 7:
        raise RuntimeError("ozon_attribute_refresh_incomplete")
    attrs_by_offer = {str(x.get("offer_id")): x for x in attrs}
    if set(attrs_by_offer) != {x["offer_id"] for x in targets}:
        raise RuntimeError("ozon_attribute_offer_mismatch")
    tnved_mismatches = {}
    for target in targets:
        detail = details.get(target["product_id"])
        attr = attrs_by_offer[target["offer_id"]]
        attr_map = {str(a.get("id")): a for a in attr.get("attributes") or []}
        brands = [str(v.get("value") or "") for v in (attr_map.get("85") or {}).get("values") or []]
        name = str(detail.get("name") or "")
        if (not detail or str(detail.get("offer_id") or "") != target["offer_id"]
                or str(detail.get("product_id") or detail.get("id") or "") != target["product_id"]
                or str(detail.get("sku") or "") != target["sku"]
                or detail.get("is_archived") is not False or brands != ["Arlight"]
                or "коннектор" not in name.casefold()
                or target["model_code"] not in name.upper()):
            raise RuntimeError("ozon_connector_identity_changed:" + target["offer_id"])
        codes = tnved_values(attr)
        if codes != ["8536699008"] and codes != ["8536901000"]:
            tnved_mismatches[target["offer_id"]] = codes

    records = list_certificates(client)
    matches = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if matches:
        raise RuntimeError("ozon_normalized_record_exists_before_create")
    absence_payload = {"certificate_number": NUMBER}
    raw = json.dumps(absence_payload, ensure_ascii=False, separators=(",", ":")).encode()
    absence = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                               data=raw, headers=client.ozon_headers, timeout=(15, 60))
    try:
        absence_body = absence.json()
    except ValueError:
        absence_body = {}
    if not (absence.status_code == 404 and isinstance(absence_body, dict)
            and absence_body.get("code") == 5
            and "not found" in str(absence_body.get("message") or "").casefold()
            and NUMBER in str(absence_body.get("message") or "")):
        raise RuntimeError("ozon_exact_record_absence_not_confirmed")

    state = {"started_at": now(), "phase": "preflight_verified", "number": NUMBER,
             "source_pdf_sha256": digest(SOURCE), "official_fsa_record_id": 21106697,
             "target_count": 7, "wb_target_cards_found": pre.get("wb_safe_targets"),
             "wb_exact_cards_missing": 7 - int(pre.get("wb_safe_targets") or 0),
             "tnved_mismatches": tnved_mismatches, "create_sent": False,
             "certificate_id": None, "binding_batches": [], "local_file_deleted": False}
    save(state)
    expiry = dt.date.fromisoformat(EXPIRY)
    seed = targets[0]
    params = {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [str(seed["sku"])], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
        "link_to_registry": FSA_URL,
    }
    req = {"params": params}
    if len(json.dumps(req, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
        raise RuntimeError("ozon_create_payload_too_large")
    state.update(phase="ozon_create_prepared", create_sent=True,
                 seed_offer_id=seed["offer_id"], seed_sku=seed["sku"])
    save(state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", req, mutation=True)
    except Exception as exc:
        state.update(phase="ozon_create_uncertain", error_type=type(exc).__name__, updated_at=now())
        save(state)
        raise RuntimeError("ozon_create_uncertain_reconcile_before_retry") from None
    cert_id = int(created.get("certificate_id") or 0)
    states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    state.update(create_response=created, certificate_id=cert_id, updated_at=now())
    if not cert_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        state.update(phase="ozon_create_not_fully_validated")
        save(state)
        raise RuntimeError("ozon_create_response_invalid")
    state.update(phase="ozon_created_response_valid")
    save(state)

    info = {}
    for attempt in range(8):
        try:
            info = client.call("ozon", "/v1/product/certificate/info",
                               {"certificate_number": NUMBER}).get("result") or {}
            break
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc) or attempt == 7:
                state.update(phase="ozon_info_readback_failed", error_type=type(exc).__name__, updated_at=now())
                save(state)
                raise
            time.sleep(2)
    if (str(info.get("certificate_id")) != str(cert_id)
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or info.get("type_code") not in {"declaration", "declaration_of_conformity"}
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
    for target in targets:
        item = by_id.get(target["product_id"])
        if item and str(item.get("sku")) != target["sku"]:
            raise RuntimeError("ozon_binding_identity_conflict:" + target["offer_id"])
        if not item:
            missing.append(target["sku"])
    for start in range(0, len(missing), 500):
        batch = missing[start:start + 500]
        state.update(phase="ozon_binding_prepared", missing_binding_count=len(missing), updated_at=now())
        save(state)
        response = client.call("ozon", "/v1/product/certificate/bind",
                               {"certificate_id": cert_id, "skus": batch}, mutation=True)
        state["binding_batches"].append({"count": len(batch), "result": response.get("result")})
        state.update(updated_at=now())
        save(state)
        if response.get("result") is not True:
            state.update(phase="ozon_bind_rejected")
            save(state)
            raise RuntimeError("ozon_bind_rejected")
    final = client.ozon_bindings(cert_id)
    final_by_id = {str(x.get("product_id")): x for x in final}
    rows = []
    statuses = collections.Counter()
    for target in targets:
        item = final_by_id.get(target["product_id"])
        okay = bool(item and str(item.get("sku")) == target["sku"])
        if okay:
            statuses[str(item.get("product_status_code"))] += 1
        rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                     "sku": target["sku"], "bound": okay,
                     "status": item.get("product_status_code") if okay else None})
    if any(not x["bound"] for x in rows):
        state.update(phase="ozon_binding_readback_incomplete",
                     missing_offers=[x["offer_id"] for x in rows if not x["bound"]], updated_at=now())
        save(state)
        raise RuntimeError("ozon_binding_readback_incomplete")
    state.update(phase="ozon_verified_complete", certificate_info=info,
                 binding_count=len(final), verified_target_pairs=len(rows),
                 binding_status_counts=dict(statuses), wb_target_cards_found=0,
                 updated_at=now())
    save(state)
    print(json.dumps({"phase": state["phase"], "certificate_id": cert_id,
                      "certificate_status": info.get("status_code"),
                      "verified_target_pairs": len(rows),
                      "binding_status_counts": dict(statuses),
                      "tnved_mismatches": tnved_mismatches,
                      "wb_exact_connector_cards_found": 0,
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
