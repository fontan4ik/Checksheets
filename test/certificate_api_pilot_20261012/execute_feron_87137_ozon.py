"""Create FERON 87137/22 once, bind the exact target SKUs, and verify readback."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import time
from pathlib import Path

from api_client import Client, digest, now, save

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_87137_ozon_plan.json"
EXECUTION_PATH = BASE / "feron_87137_ozon_execution.json"
VERIFICATION_PATH = BASE / "feron_87137_ozon_verification.json"


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    items: list[dict] = []
    last_id = 0
    expected_count = None
    while True:
        result = client.call(
            "ozon",
            "/v1/product/certificate/products/list",
            {"certificate_id": certificate_id, "limit": 500, "last_id": last_id},
        )["result"]
        batch = result.get("items")
        count = result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid certificate product-list response")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise RuntimeError("Certificate binding count changed while reading pages")
        items.extend(batch)
        if len(items) == expected_count:
            if len({str(item.get("sku")) for item in items}) != len(items):
                raise RuntimeError("Duplicate SKU in certificate binding list")
            return items
        if not batch or len(items) > expected_count:
            raise RuntimeError("Incomplete certificate binding pagination")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Certificate binding cursor did not advance")
        last_id = next_id


def certificate_info(client: Client, number: str) -> dict:
    result = client.call(
        "ozon", "/v1/product/certificate/info", {"certificate_number": number}
    ).get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Ozon certificate-info response has no result")
    return result


def main() -> None:
    if EXECUTION_PATH.exists() or VERIFICATION_PATH.exists():
        raise RuntimeError("Execution already exists; reconcile live state before any further write")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("scope_count") != 1210 or len(plan.get("targets", [])) != 1210:
        raise RuntimeError("Unexpected exact target count")
    if plan["ozon_preflight"].get("matching_exact_records") != 0:
        raise RuntimeError("An existing Ozon certificate record was found; do not create a duplicate")
    if plan["ozon_preflight"].get("identity_mismatches") != 0:
        raise RuntimeError("Product identity preflight contains mismatches")
    pdf = Path(plan["ozon_upload_pdf"]["path"])
    original = Path(plan["source_file"]["path"])
    if digest(pdf) != plan["ozon_upload_pdf"]["sha256"]:
        raise RuntimeError("Upload PDF changed after planning")
    if digest(original) != plan["source_file"]["sha256"]:
        raise RuntimeError("Original source image changed after planning")
    if pdf.stat().st_size * 4 // 3 > 15_000_000:
        raise RuntimeError("Estimated Ozon JSON request exceeds the observed safe message limit")

    targets = {str(item["sku"]): str(item["product_id"]) for item in plan["targets"]}
    if len(targets) != 1210:
        raise RuntimeError("Target SKU map is not one-to-one")
    seed_sku = str(plan["seed_sku"])
    seed_product_id = str(plan["seed_product_id"])
    if targets.get(seed_sku) != seed_product_id:
        raise RuntimeError("Seed SKU/product identity is not in the target map")

    client = Client()
    number = plan["number"]
    # Recheck the exact number immediately before a non-idempotent create.
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
        raise RuntimeError("Exact Ozon certificate appeared since preflight; reconcile instead of create")
    if precheck.status_code != 404 or precheck_body.get("code") != 5:
        raise RuntimeError("Ozon duplicate precheck was inconclusive; no create was sent")

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
        "files": [{
            "file_content": base64.b64encode(pdf.read_bytes()).decode("ascii"),
            "name": pdf.name,
        }],
        "link_to_registry": "https://pub.fsa.gov.ru/rds/declaration/view/16650447",
    }
    execution = {
        "started_at": now(),
        "phase": "create_prepared",
        "number": number,
        "target_sku_count": len(targets),
        "seed_sku": seed_sku,
        "precreate_lookup": {"http_status": precheck.status_code, "body": precheck_body},
        "create_request": {
            "path": "/v2/product/certificate/create",
            "file_sha256": plan["ozon_upload_pdf"]["sha256"],
            "request_size_estimate_bytes": len(json.dumps({"params": params}, ensure_ascii=False).encode()),
        },
        "bind_batches": [],
    }
    EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        execution.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Create result is uncertain; reconcile Ozon before any retry") from None
    execution["create_response"] = created
    certificate_id = created.get("certificate_id")
    param_states = {item.get("name"): item.get("state") for item in created.get("params", [])}
    if not certificate_id or created.get("status") != "COMPLETED" or not param_states or set(param_states.values()) != {"VALID"}:
        execution.update({"phase": "create_not_validated", "updated_at": now()})
        EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Ozon create did not return a fully valid result; no additional bindings sent")
    execution.update({"certificate_id": int(certificate_id), "phase": "created_response_valid", "updated_at": now()})
    EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")

    info = certificate_info(client, number)
    if int(info.get("certificate_id", -1)) != int(certificate_id):
        raise RuntimeError("Live Ozon number lookup does not resolve to the new certificate ID")
    if info.get("type_code") != "declaration" or str(info.get("issue_date", ""))[:10] != plan["issue_date"] or str(info.get("expire_date", ""))[:10] != plan["expire_date"]:
        raise RuntimeError("Live Ozon certificate metadata differs from the source scan")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        execution.update({"phase": "certificate_rejected", "live_info": info, "updated_at": now()})
        EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Ozon rejected the certificate; target bindings were not expanded")
    initial = read_bindings(client, int(certificate_id))
    if not any(str(item.get("sku")) == seed_sku and str(item.get("product_id")) == seed_product_id for item in initial):
        execution.update({"phase": "seed_binding_missing", "live_info": info, "initial_binding_count": len(initial), "updated_at": now()})
        EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Seed SKU is missing from Ozon readback; no remaining bindings sent")
    execution.update({"live_info_after_create": info, "initial_binding_count": len(initial), "phase": "binding_remaining_targets", "updated_at": now()})
    EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")

    remaining = [sku for sku in targets if sku != seed_sku]
    for index, offset in enumerate(range(0, len(remaining), 500), 1):
        batch = remaining[offset:offset + 500]
        entry = {"index": index, "sku_count": len(batch), "first_sku": batch[0], "last_sku": batch[-1], "phase": "prepared"}
        execution["bind_batches"].append(entry)
        EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            body = client.call("ozon", "/v1/product/certificate/bind", {"certificate_id": int(certificate_id), "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            execution.update({"phase": "bind_uncertain", "updated_at": now()})
            EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError("Bind result is uncertain; read live bindings before retry") from None
        entry["response"] = body
        entry["phase"] = "accepted" if body.get("result") is True else "rejected"
        execution["phase"] = "binding_remaining_targets"
        execution["updated_at"] = now()
        EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        if entry["phase"] != "accepted":
            execution["phase"] = "bind_rejected"
            EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError("Ozon rejected a bind batch; reconcile before any further write")

    final_info = certificate_info(client, number)
    bindings = read_bindings(client, int(certificate_id))
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in bindings:
        by_sku[str(item.get("sku", ""))].append(item)
    missing = sorted(set(targets) - set(by_sku))
    outside = sorted(set(by_sku) - set(targets))
    identity_mismatches = [
        {"sku": sku, "expected_product_id": targets[sku], "live_product_ids": sorted({str(x.get("product_id")) for x in by_sku[sku]})}
        for sku in sorted(set(targets) & set(by_sku))
        if {str(x.get("product_id")) for x in by_sku[sku]} != {targets[sku]}
    ]
    duplicate_skus = sorted(sku for sku, items in by_sku.items() if len(items) != 1)
    statuses = collections.Counter(str(item.get("product_status_code")) for item in bindings if str(item.get("sku")) in targets)
    verification = {
        "checked_at": now(),
        "number": number,
        "certificate_id": int(certificate_id),
        "certificate_info": final_info,
        "target_sku_count": len(targets),
        "live_binding_count": len(bindings),
        "covered_target_skus": len(set(targets) & set(by_sku)),
        "missing_skus": missing,
        "outside_target_skus": outside,
        "duplicate_skus": duplicate_skus,
        "identity_mismatches": identity_mismatches,
        "product_status_counts": dict(statuses),
    }
    verification["all_target_skus_linked"] = not missing and not outside and not duplicate_skus and not identity_mismatches
    verification["all_product_statuses_approved"] = bool(statuses) and set(statuses) == {"approved"}
    verification["certificate_approved"] = final_info.get("status_code") == "approved"
    verification["all_verified"] = verification["all_target_skus_linked"] and verification["all_product_statuses_approved"] and verification["certificate_approved"]
    VERIFICATION_PATH.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    execution.update({"phase": "all_verified" if verification["all_verified"] else "all_bindings_accepted_verification_pending", "finished_at": now(), "verification_path": str(VERIFICATION_PATH)})
    EXECUTION_PATH.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: verification[k] for k in ("number", "certificate_id", "target_sku_count", "live_binding_count", "covered_target_skus", "missing_skus", "outside_target_skus", "duplicate_skus", "identity_mismatches", "product_status_counts", "certificate_approved", "all_verified")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
