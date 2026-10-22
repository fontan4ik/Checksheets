"""Upload and bind the eligible Stekker 15150/25 targets on Ozon."""
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

PREFLIGHT = HERE / "stekker_15150_crossplatform_preflight_live_20261021.json"
STATE = HERE / "stekker_15150_ozon_execution_20261021.json"
LIVE_PROOF = HERE / "stekker_15150_ozon_live_eligibility_20261021.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/stekker/c3e79720d30db2f7da55a3cf.pdf"
NUMBER = "ЕАЭС N RU Д-CN.РА07.В.15150/25"
ISSUE = "2025-08-25"
EXPIRY = "2030-08-24"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/20491822"
ALLOWED_TNVED = {"8536500700", "8536691000", "8536699008", "8504405500"}


def save(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible(row: dict) -> bool:
    return (row.get("archived") is False and row.get("brand_matches") is True
            and row.get("tnved_in_scope") is True
            and row.get("product_id_matches_assignment") is True
            and row.get("sku_matches_assignment") is True)


def attr_values(row: dict, attr_id: int) -> list[str]:
    attrs = {str(x.get("id")): x for x in row.get("attributes") or []}
    return [str(x.get("value") or "").strip()
            for x in (attrs.get(str(attr_id)) or {}).get("values") or []
            if str(x.get("value") or "").strip()]


def live_check(client: Client, targets: list[dict]) -> list[dict]:
    offers = [str(x["offer_id"]) for x in targets]
    products: dict[str, dict] = {}
    attrs: dict[str, dict] = {}
    for start in range(0, len(offers), 100):
        batch = offers[start:start + 100]
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise RuntimeError("ozon_live_product_refresh_incomplete")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer in products:
                raise RuntimeError("ozon_live_duplicate_product_offer")
            products[offer] = row
        rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": batch}, "limit": len(batch)
        }).get("result")
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise RuntimeError("ozon_live_attribute_refresh_incomplete")
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer in attrs:
                raise RuntimeError("ozon_live_duplicate_attribute_offer")
            attrs[offer] = row
    if set(products) != set(offers) or set(attrs) != set(offers):
        raise RuntimeError("ozon_live_offer_set_changed")

    checked = []
    for target in targets:
        offer = str(target["offer_id"])
        product, attr = products[offer], attrs[offer]
        brands = attr_values(attr, 85)
        codes = sorted({value.split(" - ", 1)[0].strip()
                        for value in attr_values(attr, 22232)})
        product_id = str(product.get("product_id") or product.get("id") or "")
        sku = str(product.get("sku") or "")
        okay = (product_id == str(target["product_id"]) and sku == str(target["sku"])
                and product.get("is_archived") is False and len(brands) == 1
                and brands[0].casefold() == "stekker" and bool(codes)
                and set(codes) <= ALLOWED_TNVED)
        checked.append({"offer_id": offer, "product_id": product_id, "sku": sku,
                        "brand_values": brands, "tnved_codes": codes,
                        "archived": product.get("is_archived"), "eligible_now": okay})
    return checked


def list_certificates(client: Client) -> list[dict]:
    out = []
    for page in range(1, 101):
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_page_invalid")
        out.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return out
    raise RuntimeError("ozon_certificate_pages_limit")


def confirmed_absence(client: Client) -> bool:
    body = json.dumps({"certificate_number": NUMBER}, ensure_ascii=False,
                      separators=(",", ":")).encode()
    response = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                                data=body, headers=client.ozon_headers, timeout=(15, 60))
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return (response.status_code == 404 and isinstance(payload, dict)
            and payload.get("code") == 5
            and "not found" in str(payload.get("message") or "").casefold()
            and NUMBER in str(payload.get("message") or ""))


def main() -> None:
    if STATE.exists() or LIVE_PROOF.exists():
        raise RuntimeError("execution_or_live_proof_exists_reconcile_first")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if (pre.get("read_only") is not True or pre.get("number") != NUMBER
            or pre.get("official_fsa", {}).get("record_id") != 20491822
            or pre.get("ozon_exact_certificate_record_count") != 0
            or pre.get("source_pdf_sha256") != digest(SOURCE)):
        raise RuntimeError("preflight_or_pdf_hash_invalid")
    targets = [row for row in pre.get("ozon_targets") or [] if eligible(row)]
    if len(targets) != 371:
        raise RuntimeError(f"eligible_ozon_target_count_changed:{len(targets)}")
    offers = [str(x["offer_id"]) for x in targets]
    product_ids = [str(x["product_id"]) for x in targets]
    skus = [str(x["sku"]) for x in targets]
    if (len(set(offers)) != len(targets) or len(set(product_ids)) != len(targets)
            or len(set(skus)) != len(targets)
            or any(not x["tnved_codes"] or not set(x["tnved_codes"]) <= ALLOWED_TNVED for x in targets)):
        raise RuntimeError("ozon_target_identity_or_scope_conflict")

    client = Client()
    fresh_targets = live_check(client, targets)
    if len(fresh_targets) != len(targets) or any(not x["eligible_now"] for x in fresh_targets):
        save(LIVE_PROOF, {"checked_at": now(), "number": NUMBER, "targets": fresh_targets,
                          "eligible_now_count": sum(x["eligible_now"] for x in fresh_targets),
                          "complete": False})
        raise RuntimeError("live_ozon_scope_changed_or_refresh_incomplete")
    matches = [x for x in list_certificates(client)
               if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if matches or not confirmed_absence(client):
        raise RuntimeError("ozon_certificate_absence_changed_before_create")

    save(LIVE_PROOF, {"checked_at": now(), "number": NUMBER, "targets": fresh_targets,
                      "eligible_now_count": len(fresh_targets), "complete": True,
                      "source_pdf_sha256": digest(SOURCE), "registry_sample_date_condition": True})
    state = {"started_at": now(), "phase": "preflight_verified", "number": NUMBER,
             "official_fsa_record_id": 20491822, "source_pdf_sha256": digest(SOURCE),
             "eligible_target_count": len(targets), "ineligible_tnved_offers": [
                 x["offer_id"] for x in pre["ozon_targets"] if x.get("tnved_in_scope") is not True],
             "ineligible_brand_offers": [
                 x["offer_id"] for x in pre["ozon_targets"] if x.get("brand_matches") is not True],
             "sample_date_condition": "FSA says applies to product made from the sample manufacture date in the sampling act; public card shows protocol 2025-07-31, not the sampling-act date",
             "target_offers": offers, "create_sent": False, "certificate_id": None,
             "bind_batches": [], "local_file_deleted": False}
    save(STATE, state)

    seed = targets[0]
    expiry = dt.date.fromisoformat(EXPIRY)
    request = {"params": {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed["sku"]], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
        "link_to_registry": FSA_URL,
    }}
    if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
        raise RuntimeError("ozon_create_payload_too_large")
    state.update(phase="ozon_create_prepared", create_sent=True,
                 seed_offer_id=seed["offer_id"], seed_sku=seed["sku"], updated_at=now())
    save(STATE, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", request, mutation=True)
    except Exception as exc:
        state.update(phase="ozon_create_uncertain", error_type=type(exc).__name__, updated_at=now())
        save(STATE, state)
        raise RuntimeError("ozon_create_uncertain_read_live_before_retry") from None
    states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    certificate_id = int(created.get("certificate_id") or 0)
    state.update(create_response=created, certificate_id=certificate_id or None, updated_at=now())
    if not certificate_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        state.update(phase="ozon_create_response_invalid")
        save(STATE, state)
        raise RuntimeError("ozon_create_response_invalid_reconcile_before_retry")
    state.update(phase="ozon_created_response_valid")
    save(STATE, state)

    info = {}
    for attempt in range(8):
        try:
            info = client.call("ozon", "/v1/product/certificate/info",
                               {"certificate_number": NUMBER}).get("result") or {}
            break
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc) or attempt == 7:
                state.update(phase="ozon_info_readback_failed", error_type=type(exc).__name__, updated_at=now())
                save(STATE, state)
                raise
            time.sleep(2)
    if (str(info.get("certificate_id")) != str(certificate_id)
            or norm_number(info.get("certificate_number")) != norm_number(NUMBER)
            or info.get("type_code") not in {"declaration", "declaration_of_conformity"}
            or str(info.get("issue_date", ""))[:10] != ISSUE
            or str(info.get("expire_date", ""))[:10] != EXPIRY
            or str(info.get("accordance_type_code", "")).upper() != "EAEU"
            or info.get("status_code") in {"declined", "rejected", "invalid", "cancelled"}):
        state.update(phase="ozon_metadata_conflict", certificate_info=info, updated_at=now())
        save(STATE, state)
        raise RuntimeError("ozon_live_document_metadata_conflict_or_decline")

    bindings = client.ozon_bindings(certificate_id)
    by_id = {str(x.get("product_id")): x for x in bindings}
    missing = []
    for target in targets:
        binding = by_id.get(str(target["product_id"]))
        if binding and str(binding.get("sku")) != str(target["sku"]):
            raise RuntimeError("ozon_binding_identity_conflict:" + str(target["offer_id"]))
        if not binding:
            missing.append(str(target["sku"]))
    state.update(phase="ozon_binding", certificate_info=info,
                 binding_count_before=len(bindings), missing_binding_count=len(missing), updated_at=now())
    save(STATE, state)
    for start in range(0, len(missing), 100):
        batch = missing[start:start + 100]
        response = client.call("ozon", "/v1/product/certificate/bind",
                               {"certificate_id": certificate_id, "skus": batch}, mutation=True)
        state["bind_batches"].append({"count": len(batch), "result": response.get("result")})
        state["updated_at"] = now()
        save(STATE, state)
        if response.get("result") is not True:
            state.update(phase="ozon_bind_rejected")
            save(STATE, state)
            raise RuntimeError("ozon_bind_not_accepted_reconcile_before_retry")

    final_info = client.call("ozon", "/v1/product/certificate/info",
                             {"certificate_number": NUMBER}).get("result") or {}
    final_bindings = client.ozon_bindings(certificate_id)
    final_by_id = {str(x.get("product_id")): x for x in final_bindings}
    rows = []
    statuses = collections.Counter()
    for target in targets:
        binding = final_by_id.get(str(target["product_id"]))
        okay = bool(binding and str(binding.get("sku")) == str(target["sku"]))
        row = {"offer_id": target["offer_id"], "product_id": target["product_id"],
               "sku": target["sku"], "bound": okay,
               "status": binding.get("product_status_code") if okay else None}
        rows.append(row)
        if okay:
            statuses[str(binding.get("product_status_code"))] += 1
    if (any(not x["bound"] for x in rows)
            or str(final_info.get("certificate_id")) != str(certificate_id)
            or norm_number(final_info.get("certificate_number")) != norm_number(NUMBER)):
        state.update(phase="ozon_binding_readback_incomplete",
                     missing_offers=[x["offer_id"] for x in rows if not x["bound"]],
                     final_certificate_info=final_info, updated_at=now())
        save(STATE, state)
        raise RuntimeError("ozon_binding_readback_incomplete")
    state.update(phase="ozon_verified_complete", certificate_info=final_info,
                 binding_count=len(final_bindings), verified_target_pairs=len(rows),
                 binding_status_counts=dict(statuses), verified_bindings=rows,
                 local_file_deleted=False, updated_at=now())
    save(STATE, state)
    print(json.dumps({"phase": state["phase"], "certificate_id": certificate_id,
                      "certificate_status": final_info.get("status_code"),
                      "verified_target_pairs": len(rows), "binding_status_counts": dict(statuses),
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
