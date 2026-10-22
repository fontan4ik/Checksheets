"""Create FERON certificate 04998/22 once, bind exact SKUs, and verify readback."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, digest, now

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_04998_ozon_plan.json"
EXECUTION_PATH = BASE / "feron_04998_ozon_execution.json"
VERIFICATION_PATH = BASE / "feron_04998_ozon_verification.json"
CHAR_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CHAR_MAP) if ch.isalnum())


def save(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def list_certificates(client: Client) -> list[dict]:
    items: list[dict] = []
    page = 1
    seen: set[str] = set()
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list page")
        ids = [str(item.get("certificate_id")) for item in batch]
        if set(ids) & seen:
            raise RuntimeError("Duplicate Ozon certificate ID during pagination")
        seen.update(ids)
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1
    raise RuntimeError("Ozon certificate list pagination limit exceeded")


def get_info(client: Client, number: str) -> dict:
    result = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": number}).get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Ozon info response has no result")
    return result


def read_bindings(client: Client, cert_id: int) -> list[dict]:
    items: list[dict] = []
    last_id = 0
    count_expected = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": cert_id, "limit": 500, "last_id": last_id,
        })["result"]
        batch = result.get("items")
        count = result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon binding page")
        if count_expected is None:
            count_expected = count
        elif count != count_expected:
            raise RuntimeError("Ozon binding count changed during read")
        items.extend(batch)
        if len(items) == count_expected:
            if len({str(item.get("sku")) for item in items}) != len(items):
                raise RuntimeError("Duplicate Ozon binding SKU")
            return items
        if not batch or len(items) > count_expected:
            raise RuntimeError("Incomplete Ozon binding pagination")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon last_id cursor did not advance")
        last_id = next_id


def main() -> None:
    if EXECUTION_PATH.exists() or VERIFICATION_PATH.exists():
        raise RuntimeError("Execution already exists; inspect and reconcile before any write")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("scope_count") != 300 or len(plan.get("targets", [])) != 300:
        raise RuntimeError("Unexpected target count")
    if plan["ozon_preflight"].get("matching_records") or plan["ozon_preflight"].get("number_substring_matches"):
        raise RuntimeError("Ozon already has a matching certificate; do not create another")
    source = Path(plan["source_file"]["path"])
    if digest(source) != plan["source_file"]["sha256"]:
        raise RuntimeError("Original certificate PDF changed after planning")
    if source.stat().st_size * 4 // 3 > 15_000_000:
        raise RuntimeError("Estimated Ozon JSON body exceeds safe request-size guard")
    targets = {str(x["sku"]): str(x["product_id"]) for x in plan["targets"]}
    if len(targets) != 300:
        raise RuntimeError("Target SKU mapping is not one-to-one")
    seed_sku = str(plan["seed_sku"])
    if seed_sku not in targets or targets[seed_sku] != str(plan["seed_product_id"]):
        raise RuntimeError("Seed product is not in target set")

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
        raise RuntimeError("Ozon now resolves exact certificate number; reconcile instead of create")
    if precheck.status_code != 404 or precheck_body.get("code") != 5:
        raise RuntimeError("Ozon pre-create lookup inconclusive; create not sent")

    issue = dt.date.fromisoformat(plan["issue_date"])
    expiry = dt.date.fromisoformat(plan["expire_date"])
    params = {
        "name": "Сертификат соответствия № " + number,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": number,
        "issue_date": issue.isoformat() + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku],
        "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"), "name": "FERON_certificate_04998_22.pdf"}],
    }
    state = {
        "started_at": now(), "phase": "create_prepared", "number": number,
        "target_skus": len(targets), "archived_target_count": plan["ozon_preflight"]["archived_products"],
        "seed_sku": seed_sku, "precreate_lookup": {"http_status": precheck.status_code, "body": precheck_body},
        "source_file_sha256": plan["source_file"]["sha256"],
        "estimated_create_request_bytes": len(json.dumps({"params": params}, ensure_ascii=False).encode()),
        "bind_batches": [],
    }
    save(EXECUTION_PATH, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Create outcome uncertain; reconcile Ozon before any retry") from None
    state["create_response"] = created
    cert_id = created.get("certificate_id")
    states = [x.get("state") for x in created.get("params", [])]
    if not cert_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Create response incomplete; no more SKU binds sent")
    cert_id = int(cert_id)
    state.update({"certificate_id": cert_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION_PATH, state)

    records = list_certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(cert_id)]
    by_number = [x for x in records if normalize(x.get("certificate_number")) == normalize(number)]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "by_id_count": len(by_id), "by_number_count": len(by_number), "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Created certificate is not uniquely visible; no remaining bind sent")
    stored_number = str(by_id[0].get("certificate_number", ""))
    info = get_info(client, stored_number)
    if int(info.get("certificate_id", -1)) != cert_id or info.get("type_code") != "certificate_of_conformity":
        raise RuntimeError("Ozon record type/ID does not match created certificate")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "certificate_rejected", "live_info": info, "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Ozon rejected the certificate; remaining SKU binds stopped")
    issue_live = str(info.get("issue_date", ""))[:10]
    expire_live = str(info.get("expire_date", ""))[:10]
    allowed_issues = {plan["issue_date"], (issue + dt.timedelta(days=1)).isoformat()}
    if issue_live not in allowed_issues or expire_live != plan["expire_date"]:
        state.update({"phase": "live_date_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION_PATH, state)
        raise RuntimeError("Ozon dates conflict with the visually checked original/registry dates")

    initial = read_bindings(client, cert_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in initial:
        by_sku[str(item.get("sku", ""))].append(item)
    outside = sorted(set(by_sku) - set(targets))
    duplicates = sorted(sku for sku, items in by_sku.items() if len(items) != 1)
    mismatches = [sku for sku, items in by_sku.items() if sku in targets and {str(x.get("product_id")) for x in items} != {targets[sku]}]
    if outside or duplicates or mismatches:
        raise RuntimeError("Seed binding readback contains an outside SKU, duplicate, or product ID mismatch")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "stored_number": stored_number, "live_info_after_create": info,
                  "initial_binding_count": len(initial), "missing_before_bind": len(missing), "updated_at": now()})
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
            raise RuntimeError("Bind outcome uncertain; reconcile live bindings before retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION_PATH, state)
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            save(EXECUTION_PATH, state)
            raise RuntimeError("Ozon rejected a bind batch; reconcile before another write")

    final_info = get_info(client, stored_number)
    final_bindings = read_bindings(client, cert_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final_bindings:
        final_by_sku[str(item.get("sku", ""))].append(item)
    missing_after = sorted(set(targets) - set(final_by_sku))
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicates_after = sorted(sku for sku, items in final_by_sku.items() if len(items) != 1)
    identity_after = [
        {"sku": sku, "expected_product_id": targets[sku], "live_product_ids": sorted({str(x.get("product_id")) for x in final_by_sku[sku]})}
        for sku in sorted(set(targets) & set(final_by_sku))
        if {str(x.get("product_id")) for x in final_by_sku[sku]} != {targets[sku]}
    ]
    statuses = collections.Counter(str(item.get("product_status_code")) for item in final_bindings if str(item.get("sku")) in targets)
    verification = {
        "checked_at": now(), "number": number, "ozon_stored_number": stored_number,
        "certificate_id": cert_id, "certificate_info": final_info,
        "target_skus": len(targets), "archived_target_skus": plan["ozon_preflight"]["archived_products"],
        "live_binding_count": len(final_bindings), "covered_target_skus": len(set(targets) & set(final_by_sku)),
        "missing_skus": missing_after, "outside_target_skus": outside_after,
        "duplicate_skus": duplicates_after, "product_identity_mismatches": identity_after,
        "product_status_counts": dict(statuses),
    }
    verification["all_target_skus_linked"] = not missing_after and not outside_after and not duplicates_after and not identity_after
    verification["all_product_statuses_approved"] = bool(statuses) and set(statuses) == {"approved"}
    verification["certificate_approved"] = final_info.get("status_code") == "approved"
    verification["all_verified"] = verification["all_target_skus_linked"] and verification["all_product_statuses_approved"] and verification["certificate_approved"]
    save(VERIFICATION_PATH, verification)
    state.update({"phase": "all_verified" if verification["all_verified"] else "all_bindings_visible_review_pending", "finished_at": now(), "verification_path": str(VERIFICATION_PATH)})
    save(EXECUTION_PATH, state)
    print(json.dumps({key: verification[key] for key in (
        "number", "ozon_stored_number", "certificate_id", "target_skus", "archived_target_skus",
        "live_binding_count", "covered_target_skus", "missing_skus", "outside_target_skus",
        "duplicate_skus", "product_identity_mismatches", "product_status_counts",
        "certificate_approved", "all_verified",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
