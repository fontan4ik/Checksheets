"""Upload Arlight 33344/26 to Ozon for the 26 exact in-scope offers only."""
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
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

PREFLIGHT = HERE / "arlight_33344_partial_preflight_live_20261021.json"
STATE = HERE / "arlight_33344_partial_ozon_execution_20261021.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/DCE8C157436F3C4E9898E20868978ACD.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА03.В.33344/26"
ISSUE = "2026-04-13"
EXPIRY = "2031-04-09"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/21321061"


def save(value: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(STATE)


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_certificates(client: Client) -> list[dict]:
    out = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_page_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return out
        page += 1
    raise RuntimeError("ozon_certificate_pages_exceeded")


def validate_live_targets(client: Client, targets: list[dict]) -> None:
    offers = [str(x["offer_id"]) for x in targets]
    products = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    attrs = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offers}, "limit": len(offers)
    }).get("result")
    if not isinstance(products, list) or len(products) != len(offers):
        raise RuntimeError("ozon_live_target_refresh_incomplete")
    if not isinstance(attrs, list) or len(attrs) != len(offers):
        raise RuntimeError("ozon_live_attribute_refresh_incomplete")
    pmap = {str(x.get("offer_id") or ""): x for x in products}
    amap = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(pmap) != set(offers) or set(amap) != set(offers):
        raise RuntimeError("ozon_live_target_set_changed")
    for target in targets:
        offer = str(target["offer_id"])
        p, a = pmap[offer], amap[offer]
        attr_map = {str(x.get("id")): x for x in a.get("attributes") or []}
        brand = [str(x.get("value") or "") for x in (attr_map.get("85") or {}).get("values") or []]
        tnv = sorted({str(x.get("value") or "").split(" - ", 1)[0].strip()
                      for x in (attr_map.get("22232") or {}).get("values") or []
                      if str(x.get("value") or "").strip()})
        if (str(p.get("product_id") or p.get("id") or "") != str(target["product_id"])
                or str(p.get("sku") or "") != str(target["sku"])
                or p.get("is_archived") is not False or brand != ["Arlight"]
                or "диммер" not in str(p.get("name") or "").casefold()
                or tnv != ["8537109800"]):
            raise RuntimeError("ozon_live_target_identity_or_scope_changed:" + offer)


def confirmed_absence(client: Client) -> bool:
    body = json.dumps({"certificate_number": NUMBER}, ensure_ascii=False,
                      separators=(",", ":")).encode()
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=body, headers=client.ozon_headers, timeout=(15, 60))
    try:
        result = response.json()
    except ValueError:
        result = {}
    return (response.status_code == 404 and isinstance(result, dict) and result.get("code") == 5
            and "not found" in str(result.get("message") or "").casefold()
            and NUMBER in str(result.get("message") or ""))


def main() -> None:
    if STATE.exists():
        raise RuntimeError("execution_state_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    targets = pre.get("ozon_targets") or []
    if (pre.get("eligible_for_partial_upload") is not True or len(targets) != 26
            or pre.get("ozon_record_count_before_upload") != 0
            or pre.get("ozon_exact_info_absent") is not True
            or digest(SOURCE) != pre.get("source_pdf_sha256")):
        raise RuntimeError("partial_scope_preflight_or_source_hash_invalid")
    offers = [str(x["offer_id"]) for x in targets]
    skus = [str(x["sku"]) for x in targets]
    product_ids = [str(x["product_id"]) for x in targets]
    if (len(set(offers)) != 26 or len(set(skus)) != 26 or len(set(product_ids)) != 26
            or any(x.get("tnved_codes") != ["8537109800"] for x in targets)):
        raise RuntimeError("ozon_partial_target_identity_not_unique_or_scope_conflict")

    client = Client()
    validate_live_targets(client, targets)
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if matches or not confirmed_absence(client):
        raise RuntimeError("ozon_certificate_absence_changed_before_create")

    state = {"started_at": now(), "phase": "preflight_verified", "number": NUMBER,
             "official_fsa_record_id": 21321061, "source_pdf_sha256": digest(SOURCE),
             "assigned_offer_count": 90, "skipped_tnved_mismatches": 64,
             "target_count": 26, "target_offers": offers,
             "create_sent": False, "certificate_id": None, "bind_batches": [],
             "local_file_deleted": False}
    save(state)
    seed = targets[0]
    expires = dt.date.fromisoformat(EXPIRY)
    request = {"params": {
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
    if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
        raise RuntimeError("ozon_create_payload_too_large")
    state.update(phase="ozon_create_prepared", create_sent=True,
                 seed_offer_id=seed["offer_id"], seed_sku=seed["sku"], updated_at=now())
    save(state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", request, mutation=True)
    except Exception as exc:
        state.update(phase="ozon_create_uncertain", error_type=type(exc).__name__, updated_at=now())
        save(state)
        raise RuntimeError("ozon_create_uncertain_reconcile_before_retry") from None
    states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    cert_id = int(created.get("certificate_id") or 0)
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
        raise RuntimeError("ozon_live_document_metadata_conflict_or_decline")

    bindings = client.ozon_bindings(cert_id)
    by_id = {str(x.get("product_id")): x for x in bindings}
    missing = []
    for target in targets:
        bound = by_id.get(str(target["product_id"]))
        if bound and str(bound.get("sku")) != str(target["sku"]):
            raise RuntimeError("ozon_binding_identity_conflict:" + str(target["offer_id"]))
        if not bound:
            missing.append(str(target["sku"]))
    state.update(phase="ozon_binding", certificate_info=info,
                 binding_count_before=len(bindings), missing_binding_count=len(missing), updated_at=now())
    save(state)
    for start in range(0, len(missing), 500):
        batch = missing[start:start + 500]
        response = client.call("ozon", "/v1/product/certificate/bind",
                               {"certificate_id": cert_id, "skus": batch}, mutation=True)
        state["bind_batches"].append({"count": len(batch), "result": response.get("result")})
        state["updated_at"] = now()
        save(state)
        if response.get("result") is not True:
            state.update(phase="ozon_bind_rejected")
            save(state)
            raise RuntimeError("ozon_bind_not_accepted")

    final_bindings = client.ozon_bindings(cert_id)
    final_by_id = {str(x.get("product_id")): x for x in final_bindings}
    rows = []
    statuses = collections.Counter()
    for target in targets:
        binding = final_by_id.get(str(target["product_id"]))
        okay = bool(binding and str(binding.get("sku")) == str(target["sku"]))
        rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                     "sku": target["sku"], "bound": okay,
                     "status": binding.get("product_status_code") if okay else None})
        if okay:
            statuses[str(binding.get("product_status_code"))] += 1
    if any(not x["bound"] for x in rows):
        state.update(phase="ozon_binding_readback_incomplete",
                     missing_offers=[x["offer_id"] for x in rows if not x["bound"]], updated_at=now())
        save(state)
        raise RuntimeError("ozon_binding_readback_incomplete")
    state.update(phase="ozon_verified_complete", certificate_info=info,
                 binding_count=len(final_bindings), verified_target_pairs=len(rows),
                 binding_status_counts=dict(statuses), verified_bindings=rows,
                 local_file_deleted=False, updated_at=now())
    save(state)
    print(json.dumps({"phase": state["phase"], "certificate_id": cert_id,
                      "certificate_status": info.get("status_code"),
                      "verified_target_pairs": len(rows), "binding_status_counts": dict(statuses),
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
