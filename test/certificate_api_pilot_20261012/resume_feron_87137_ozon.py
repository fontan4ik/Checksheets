"""Reconcile the accepted 87137/22 creation and bind only currently missing SKUs."""
from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, now

BASE = Path(__file__).resolve().parent
PLAN = json.loads((BASE / "feron_87137_ozon_plan.json").read_text(encoding="utf-8"))
CREATION = json.loads((BASE / "feron_87137_ozon_execution.json").read_text(encoding="utf-8"))
EXECUTION_PATH = BASE / "feron_87137_ozon_resume_execution.json"
VERIFICATION_PATH = BASE / "feron_87137_ozon_verification.json"
CANONICAL_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "H", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ё": "E", "Э": "E", "Д": "D", "П": "P",
})


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper().translate(CANONICAL_MAP) if ch.isalnum())


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
            raise RuntimeError("Duplicate certificate ID during pagination")
        seen.update(ids)
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1
    raise RuntimeError("Ozon certificate list exceeded pagination limit")


def certificate_info(client: Client, number: str) -> dict:
    result = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": number}).get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Invalid Ozon certificate info response")
    return result


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    items: list[dict] = []
    last_id = 0
    expected_count = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": certificate_id, "limit": 500, "last_id": last_id,
        })["result"]
        batch = result.get("items")
        count = result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon certificate products page")
        if expected_count is None:
            expected_count = count
        elif expected_count != count:
            raise RuntimeError("Ozon binding count changed while paginating")
        items.extend(batch)
        if len(items) == expected_count:
            if len({str(item.get("sku")) for item in items}) != len(items):
                raise RuntimeError("Duplicate SKU in Ozon binding listing")
            return items
        if not batch or len(items) > expected_count:
            raise RuntimeError("Incomplete Ozon binding pagination")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon last_id cursor failed to advance")
        last_id = next_id


def save_state(value: dict) -> None:
    EXECUTION_PATH.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if VERIFICATION_PATH.exists():
        raise RuntimeError("Verification already exists; inspect current result instead of writing again")
    certificate_id = int(CREATION.get("certificate_id", 0))
    if certificate_id != 5608768 or CREATION.get("phase") != "created_response_valid":
        raise RuntimeError("Unexpected create journal; reconcile manually before continuing")
    targets = {str(row["sku"]): str(row["product_id"]) for row in PLAN["targets"]}
    if len(targets) != 1210 or len(PLAN["targets"]) != 1210:
        raise RuntimeError("Exact target scope changed")
    client = Client()

    records = list_certificates(client)
    by_id = [item for item in records if str(item.get("certificate_id")) == str(certificate_id)]
    by_number = [item for item in records if normalize(item.get("certificate_number")) == normalize(PLAN["number"])]
    if len(by_id) != 1 or len(by_number) != 1 or by_id[0].get("certificate_id") != by_number[0].get("certificate_id"):
        raise RuntimeError("Created record is not uniquely visible by ID and normalized full number")
    record = by_id[0]
    stored_number = str(record.get("certificate_number", ""))
    info = certificate_info(client, stored_number)
    if int(info.get("certificate_id", -1)) != certificate_id or info.get("type_code") != "declaration":
        raise RuntimeError("Ozon certificate info does not match created declaration ID/type")
    if info.get("status_code") != "approved":
        raise RuntimeError(f"Ozon certificate is not approved: {info.get('status_code')!r}; no remaining bindings sent")
    issue_live = str(info.get("issue_date", ""))[:10]
    expire_live = str(info.get("expire_date", ""))[:10]
    expected_issue = PLAN["issue_date"]
    accepted_issue_dates = {expected_issue, (dt.date.fromisoformat(expected_issue) + dt.timedelta(days=1)).isoformat()}
    if issue_live not in accepted_issue_dates or expire_live != PLAN["expire_date"]:
        raise RuntimeError("Ozon effective dates differ beyond the observed one-day issue-date representation")

    state = {
        "started_at": now(),
        "phase": "reconciled_before_bind",
        "certificate_id": certificate_id,
        "requested_number": PLAN["number"],
        "ozon_stored_number": stored_number,
        "ozon_record_count": len(records),
        "matching_by_normalized_number": len(by_number),
        "live_info": info,
        "date_observation": {
            "scan_issue_date": expected_issue,
            "ozon_issue_date": issue_live,
            "wb_item_start_date_seen": "2022-04-05",
            "expire_date": expire_live,
            "note": "Ozon and WB report 2022-04-05 while the signed scan prints registration date 2022-04-04; both marketplaces currently show this document approved/valid. Preserve this observed one-day representation difference in the audit trail.",
        },
        "bind_batches": [],
    }
    save_state(state)

    live_bindings = read_bindings(client, certificate_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in live_bindings:
        by_sku[str(item.get("sku", ""))].append(item)
    outside = sorted(set(by_sku) - set(targets))
    identity_errors = [
        {"sku": sku, "expected_product_id": targets[sku], "live_product_ids": sorted({str(x.get("product_id")) for x in by_sku[sku]})}
        for sku in sorted(set(targets) & set(by_sku))
        if {str(x.get("product_id")) for x in by_sku[sku]} != {targets[sku]}
    ]
    duplicates = sorted(sku for sku, entries in by_sku.items() if len(entries) != 1)
    if outside or identity_errors or duplicates:
        raise RuntimeError("Existing Ozon bindings contain outside target SKUs or identity errors")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "initial_binding_count": len(live_bindings), "missing_before_write": len(missing), "updated_at": now()})
    save_state(state)

    for index, offset in enumerate(range(0, len(missing), 500), 1):
        batch = missing[offset:offset + 500]
        entry = {"index": index, "sku_count": len(batch), "first_sku": batch[0], "last_sku": batch[-1], "phase": "prepared"}
        state["bind_batches"].append(entry)
        save_state(state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": certificate_id, "skus": batch,
            }, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save_state(state)
            raise RuntimeError("Bind result is uncertain; read live state before another write") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save_state(state)
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            save_state(state)
            raise RuntimeError("Ozon rejected a bind batch; stop and reconcile")

    final_record = certificate_info(client, stored_number)
    final_bindings = read_bindings(client, certificate_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final_bindings:
        final_by_sku[str(item.get("sku", ""))].append(item)
    missing_after = sorted(set(targets) - set(final_by_sku))
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicate_after = sorted(sku for sku, entries in final_by_sku.items() if len(entries) != 1)
    identity_errors_after = [
        {"sku": sku, "expected_product_id": targets[sku], "live_product_ids": sorted({str(x.get("product_id")) for x in final_by_sku[sku]})}
        for sku in sorted(set(targets) & set(final_by_sku))
        if {str(x.get("product_id")) for x in final_by_sku[sku]} != {targets[sku]}
    ]
    status_counts = collections.Counter(str(item.get("product_status_code")) for item in final_bindings if str(item.get("sku")) in targets)
    verification = {
        "checked_at": now(),
        "number": PLAN["number"],
        "ozon_stored_number": stored_number,
        "certificate_id": certificate_id,
        "certificate_info": final_record,
        "target_skus": len(targets),
        "live_bindings": len(final_bindings),
        "covered_target_skus": len(set(targets) & set(final_by_sku)),
        "missing_skus": missing_after,
        "outside_target_skus": outside_after,
        "duplicate_skus": duplicate_after,
        "product_identity_mismatches": identity_errors_after,
        "product_status_counts": dict(status_counts),
        "date_observation": state["date_observation"],
    }
    verification["all_target_skus_linked"] = not missing_after and not outside_after and not duplicate_after and not identity_errors_after
    verification["all_product_statuses_approved"] = bool(status_counts) and set(status_counts) == {"approved"}
    verification["certificate_approved"] = final_record.get("status_code") == "approved"
    verification["all_verified"] = verification["all_target_skus_linked"] and verification["all_product_statuses_approved"] and verification["certificate_approved"]
    VERIFICATION_PATH.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    state.update({"phase": "all_verified" if verification["all_verified"] else "all_bindings_visible_review_pending", "finished_at": now(), "verification_path": str(VERIFICATION_PATH)})
    save_state(state)
    print(json.dumps({key: verification[key] for key in (
        "number", "ozon_stored_number", "certificate_id", "target_skus", "live_bindings",
        "covered_target_skus", "missing_skus", "outside_target_skus", "duplicate_skus",
        "product_identity_mismatches", "product_status_counts", "certificate_approved", "all_verified",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
