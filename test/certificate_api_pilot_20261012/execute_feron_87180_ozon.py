"""Create FERON 87180/22 once, bind exact Ozon SKUs, and verify server readback."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, digest, now

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_87180_ozon_plan.json"
EXECUTION_PATH = BASE / "feron_87180_ozon_execution.json"
VERIFICATION_PATH = BASE / "feron_87180_ozon_verification.json"
CHAR_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    seen: set[str] = set()
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list page")
        ids = [str(item.get("certificate_id")) for item in batch]
        if set(ids) & seen:
            raise RuntimeError("Duplicate certificate ID in Ozon pagination")
        seen.update(ids)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate list exceeded page limit")


def certificate_info(client: Client, number: str) -> dict:
    result = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": number}).get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Ozon certificate info returned no result")
    return result


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    out: list[dict] = []
    last_id = 0
    expected = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "limit": 500, "last_id": last_id,
        })["result"]
        batch = result.get("items")
        count = result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon product binding page")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed during read")
        out.extend(batch)
        if len(out) == expected:
            if len({str(item.get("sku")) for item in out}) != len(out):
                raise RuntimeError("Duplicate SKU in Ozon binding response")
            return out
        if not batch or len(out) > expected:
            raise RuntimeError("Incomplete Ozon binding pagination")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon last_id did not advance")
        last_id = next_id


def main() -> None:
    if EXECUTION_PATH.exists() or VERIFICATION_PATH.exists():
        raise RuntimeError("Execution artifact already exists; reconcile state before any further write")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("scope_count") != 301 or len(plan.get("targets", [])) != 301:
        raise RuntimeError("Unexpected target count")
    if plan["ozon_preflight"].get("exact_records") != 0 or plan["ozon_preflight"].get("number_substring_records") != 0:
        raise RuntimeError("Existing Ozon document record found; do not create a duplicate")
    pdf = Path(plan["ozon_upload_pdf"]["path"])
    original = Path(plan["source_file"]["path"])
    if digest(pdf) != plan["ozon_upload_pdf"]["sha256"] or digest(original) != plan["source_file"]["sha256"]:
        raise RuntimeError("Source or upload PDF changed after preflight")
    if pdf.stat().st_size * 4 // 3 > 15_000_000:
        raise RuntimeError("Ozon JSON body exceeds the observed safe request-size guard")
    targets = {str(item["sku"]): str(item["product_id"]) for item in plan["targets"]}
    if len(targets) != 301:
        raise RuntimeError("Target SKU mapping is not one-to-one")
    seed_sku = str(plan["seed_sku"])
    if seed_sku not in targets or targets[seed_sku] != str(plan["seed_product_id"]):
        raise RuntimeError("Seed product is not in the exact target mapping")

    client = Client()
    number = plan["number"]
    precheck = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        data=json.dumps({"certificate_number": number}, ensure_ascii=False).encode(),
        headers=client.ozon_headers,
        timeout=(15, 60),
    )
    try:
        precheck_body = precheck.json()
    except ValueError:
        precheck_body = {}
    if precheck.status_code == 200:
        raise RuntimeError("Ozon exact number now resolves to a record; reconcile rather than create")
    if precheck.status_code != 404 or precheck_body.get("code") != 5:
        raise RuntimeError("Ozon pre-create lookup was inconclusive; create was not sent")

    issue = dt.date.fromisoformat(plan["issue_date"])
    expiry = dt.date.fromisoformat(plan["expire_date"])
    params = {
        "name": "Декларация о соответствии № " + number,
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": number,
        "issue_date": issue.isoformat() + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(pdf.read_bytes()).decode("ascii"), "name": pdf.name}],
        "link_to_registry": "https://pub.fsa.gov.ru/rds/declaration/view/16650490",
    }
    state = {
        "started_at": now(), "phase": "create_prepared", "number": number,
        "target_skus": len(targets), "archived_target_count": plan["ozon_preflight"]["archived_products"],
        "seed_sku": seed_sku, "precreate_lookup": {"http_status": precheck.status_code, "body": precheck_body},
        "file_sha256": plan["ozon_upload_pdf"]["sha256"],
        "estimated_create_request_bytes": len(json.dumps({"params": params}, ensure_ascii=False).encode()),
        "bind_batches": [],
    }
    save(EXECUTION_PATH, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Create outcome uncertain; reconcile Ozon before retry") from None
    state["create_response"] = created
    cert_id = created.get("certificate_id")
    param_states = [item.get("state") for item in created.get("params", [])]
    if not cert_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Ozon create did not return all VALID fields; no other SKU bind attempted")
    cert_id = int(cert_id)
    state.update({"certificate_id": cert_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION_PATH, state)

    records = list_certificates(client)
    by_id = [item for item in records if str(item.get("certificate_id")) == str(cert_id)]
    by_num = [item for item in records if norm(item.get("certificate_number")) == norm(number)]
    if len(by_id) != 1 or len(by_num) != 1 or str(by_id[0].get("certificate_id")) != str(by_num[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "live_matches_by_id": len(by_id), "live_matches_by_number": len(by_num), "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Created record is not unique by ID and normalized number; no further bind attempted")
    stored_number = str(by_id[0].get("certificate_number", ""))
    info = certificate_info(client, stored_number)
    if int(info.get("certificate_id", -1)) != cert_id or info.get("type_code") != "declaration":
        raise RuntimeError("Live Ozon record does not match created declaration")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "certificate_rejected", "live_info": info, "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Ozon rejected the declaration; remaining SKU binds stopped")
    issue_live = str(info.get("issue_date", ""))[:10]
    expiry_live = str(info.get("expire_date", ""))[:10]
    allowed_issue = {plan["issue_date"], (issue + dt.timedelta(days=1)).isoformat()}
    allowed_expiry = {plan["expire_date"], "2027-04-04"}
    if issue_live not in allowed_issue or expiry_live not in allowed_expiry:
        state.update({"phase": "live_date_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Ozon live date differs beyond the recorded one-day source/registry representation")
    bindings = read_bindings(client, cert_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in bindings:
        by_sku[str(item.get("sku", ""))].append(item)
    outside = sorted(set(by_sku) - set(targets))
    duplicates = sorted(sku for sku, entries in by_sku.items() if len(entries) != 1)
    identity_errors = [sku for sku, entries in by_sku.items() if sku in targets and {str(x.get("product_id")) for x in entries} != {targets[sku]}]
    if outside or duplicates or identity_errors:
        raise RuntimeError("Seed binding readback has outside SKUs or identity conflicts")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "stored_number": stored_number, "live_info_after_create": info,
                  "initial_binding_count": len(bindings), "missing_before_bind": len(missing), "updated_at": now()})
    save(EXECUTION_PATH, state)

    for index, offset in enumerate(range(0, len(missing), 500), 1):
        batch = missing[offset:offset + 500]
        entry = {"index": index, "sku_count": len(batch), "first_sku": batch[0], "last_sku": batch[-1], "phase": "prepared"}
        state["bind_batches"].append(entry)
        save(EXECUTION_PATH, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", {"certificate_id": cert_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(EXECUTION_PATH, state)
            raise RuntimeError("Bind result uncertain; reconcile live bindings before any retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION_PATH, state)
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            save(EXECUTION_PATH, state)
            raise RuntimeError("Ozon rejected the bind batch; stop for live reconciliation")

    final_info = certificate_info(client, stored_number)
    final_bindings = read_bindings(client, cert_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final_bindings:
        final_by_sku[str(item.get("sku", ""))].append(item)
    missing_after = sorted(set(targets) - set(final_by_sku))
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicate_after = sorted(sku for sku, entries in final_by_sku.items() if len(entries) != 1)
    identity_after = [
        {"sku": sku, "expected_product_id": targets[sku], "live_product_ids": sorted({str(x.get("product_id")) for x in final_by_sku[sku]})}
        for sku in sorted(set(targets) & set(final_by_sku))
        if {str(x.get("product_id")) for x in final_by_sku[sku]} != {targets[sku]}
    ]
    status_counts = collections.Counter(str(item.get("product_status_code")) for item in final_bindings if str(item.get("sku")) in targets)
    verification = {
        "checked_at": now(), "number": number, "ozon_stored_number": stored_number,
        "certificate_id": cert_id, "certificate_info": final_info,
        "target_skus": len(targets), "archived_target_skus": plan["ozon_preflight"]["archived_products"],
        "live_binding_count": len(final_bindings), "covered_target_skus": len(set(targets) & set(final_by_sku)),
        "missing_skus": missing_after, "outside_target_skus": outside_after,
        "duplicate_skus": duplicate_after, "product_identity_mismatches": identity_after,
        "product_status_counts": dict(status_counts),
        "date_observation": {"scan_issue": "2022-04-05", "scan_expire_inclusive": "2027-04-04",
                              "registry_and_wb_expire": "2027-04-03", "ozon_issue": str(final_info.get("issue_date", ""))[:10],
                              "ozon_expire": str(final_info.get("expire_date", ""))[:10]},
    }
    verification["all_target_skus_linked"] = not missing_after and not outside_after and not duplicate_after and not identity_after
    verification["all_product_statuses_approved"] = bool(status_counts) and set(status_counts) == {"approved"}
    verification["certificate_approved"] = final_info.get("status_code") == "approved"
    verification["all_verified"] = verification["all_target_skus_linked"] and verification["all_product_statuses_approved"] and verification["certificate_approved"]
    save(VERIFICATION_PATH, verification)
    state.update({"phase": "all_verified" if verification["all_verified"] else "all_bindings_visible_review_pending", "finished_at": now(), "verification_path": str(VERIFICATION_PATH)})
    save(EXECUTION_PATH, state)
    print(json.dumps({key: verification[key] for key in (
        "number", "ozon_stored_number", "certificate_id", "target_skus", "archived_target_skus",
        "live_binding_count", "covered_target_skus", "missing_skus", "outside_target_skus",
        "duplicate_skus", "product_identity_mismatches", "product_status_counts",
        "certificate_approved", "all_verified", "date_observation",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
