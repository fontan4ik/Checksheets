"""Create and bind the source-verified Arlight declaration on Ozon once."""
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

PREFLIGHT = HERE / "arlight_46569_preflight_live_20261021.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/97331E1740F80745A33F67528E33A9AB.pdf"
STATE = HERE / "arlight_46569_ozon_execution_20261021.json"
NUMBER = "ЕАЭС N RU Д-CN.РА01.В.46569/26"
ISSUE = "2026-01-30"
EXPIRY = "2031-01-29"


def save(value: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(STATE)


def certificate_records(client: Client) -> list[dict]:
    rows = []
    page = 1
    while True:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result") or {}
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("ozon_certificate_list_missing")
        rows.extend(batch)
        if not batch or page >= int(result.get("page_count") or 0):
            return rows
        page += 1


def main() -> None:
    if STATE.exists():
        raise RuntimeError("ozon_execution_state_exists_reconcile_before_retry")
    pre = json.loads(PREFLIGHT.read_text())
    if (not pre.get("eligible_for_upload") or pre.get("unique_offer_targets") != 905
            or pre.get("ozon_targets_checked") != 905 or pre.get("ozon_scope_counts") != {"in_scope": 905}
            or pre.get("ozon_normalized_record_matches") != 0
            or pre.get("wb_existing_target_cards_with_same_number") != 0):
        raise RuntimeError("preflight_is_not_fully_eligible")
    if digest(SOURCE) != pre.get("source_pdf_sha256"):
        raise RuntimeError("source_pdf_hash_changed")
    targets = pre["ozon_targets"]
    if len({x["offer_id"] for x in targets}) != 905 or len({x["product_id"] for x in targets}) != 905 or len({x["sku"] for x in targets}) != 905:
        raise RuntimeError("ozon_preflight_targets_not_unique")

    client = Client()
    # Reconfirm current identities immediately before the first write.
    current_by_id = {}
    ids = [x["product_id"] for x in targets]
    for start in range(0, len(ids), 500):
        batch = ids[start:start + 500]
        rows = client.call("ozon", "/v3/product/info/list", {
            "product_id": [int(x) for x in batch]}).get("items")
        if not isinstance(rows, list):
            raise RuntimeError("ozon_product_refresh_missing")
        for row in rows:
            pid = str(row.get("product_id") or row.get("id") or "")
            if pid in current_by_id or pid not in batch:
                raise RuntimeError("ozon_product_refresh_identity_mismatch")
            current_by_id[pid] = row
    if set(current_by_id) != set(ids):
        raise RuntimeError("ozon_product_refresh_incomplete")
    for target in targets:
        item = current_by_id[target["product_id"]]
        if (str(item.get("offer_id")) != target["offer_id"]
                or str(item.get("sku")) != target["sku"]
                or item.get("is_archived") is not False):
            raise RuntimeError("ozon_product_changed_before_upload:" + target["offer_id"])

    records = certificate_records(client)
    exact = [x for x in records if norm_number(x.get("certificate_number")) == norm_number(NUMBER)]
    if exact:
        raise RuntimeError("normalized_ozon_record_exists_before_create:" + ",".join(
            str(x.get("certificate_id")) for x in exact))

    state = {"started_at": now(), "phase": "preflight_verified", "number": NUMBER,
             "certificate_id": None, "target_count": len(targets),
             "source_sha256": digest(SOURCE), "create_sent": False,
             "bind_batches": [], "local_file_deleted": False}
    save(state)
    expiry = dt.date.fromisoformat(EXPIRY)
    params = {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [str(targets[0]["sku"])], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
        "link_to_registry": "https://pub.fsa.gov.ru/rds/declaration/view/21106549",
    }
    request = {"params": params}
    if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()) > 9_500_000:
        raise RuntimeError("ozon_create_payload_too_large")
    state.update(phase="ozon_create_prepared", create_sent=True,
                 seed_offer_id=targets[0]["offer_id"], seed_sku=targets[0]["sku"])
    save(state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", request, mutation=True)
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
        bound = by_id.get(target["product_id"])
        if bound and str(bound.get("sku")) != target["sku"]:
            raise RuntimeError("ozon_binding_identity_conflict:" + target["offer_id"])
        if not bound:
            missing.append(target["sku"])
    state.update(phase="ozon_binding", certificate_info=info,
                 binding_count_before=len(bindings), missing_binding_count=len(missing))
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
    status_counts = collections.Counter()
    for target in targets:
        binding = final_by_id.get(target["product_id"])
        okay = bool(binding and str(binding.get("sku")) == target["sku"])
        rows.append({"offer_id": target["offer_id"], "product_id": target["product_id"],
                     "sku": target["sku"], "bound": okay,
                     "status": binding.get("product_status_code") if okay else None})
        if okay:
            status_counts[str(binding.get("product_status_code"))] += 1
    if any(not x["bound"] for x in rows):
        state.update(phase="ozon_binding_readback_incomplete", missing_offers=[x["offer_id"] for x in rows if not x["bound"]], updated_at=now())
        save(state)
        raise RuntimeError("ozon_binding_readback_incomplete")
    state.update(phase="ozon_verified_complete", binding_count=len(final_bindings),
                 verified_target_pairs=len(rows), binding_status_counts=dict(status_counts),
                 updated_at=now())
    save(state)
    print(json.dumps({"phase": state["phase"], "certificate_id": cert_id,
                      "certificate_status": info.get("status_code"),
                      "verified_target_pairs": len(rows),
                      "binding_status_counts": dict(status_counts),
                      "source_pdf_deleted": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
