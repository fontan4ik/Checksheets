"""Create FSA-verified declaration 00909/23 on Ozon and bind exact active SKUs."""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, digest, now, save
from audit_feron_01315_53551 import norm
from build_feron_00909_ozon_plan import certificates, live_products
import build_feron_54301_ozon_plan as workbook_reader

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "feron_00909_ozon_plan.json"
RUN_PATH = BASE / "feron_00909_ozon_execution.json"
VERIFICATION_PATH = BASE / "feron_00909_ozon_verification.json"


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    out: list[dict] = []
    last_id = 0
    expected_count = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list",
                             {"certificate_id": certificate_id, "limit": 500, "last_id": last_id}).get("result", {})
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon certificate bindings page")
        if expected_count is None:
            expected_count = count
        elif expected_count != count:
            raise RuntimeError("Ozon binding count changed while paginating")
        out.extend(batch)
        if len(out) == expected_count:
            if len({str(x.get("sku")) for x in out}) != len(out):
                raise RuntimeError("Duplicate SKU in Ozon binding readback")
            return out
        if not batch or len(out) > expected_count:
            raise RuntimeError("Ozon bindings pagination incomplete")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon last_id cursor did not advance")
        last_id = next_id


def save_state(state: dict) -> None:
    state["updated_at"] = now()
    RUN_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if RUN_PATH.exists() or VERIFICATION_PATH.exists():
        raise RuntimeError("Execution evidence already exists; reconcile live Ozon before any new write")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("number") != "ЕАЭС N RU Д-CN.РА10.В.00909/23" or len(plan.get("targets", [])) != 267:
        raise RuntimeError("Unexpected FSA declaration plan")
    source = Path(plan["source_file"]["path"])
    upload = Path(plan["upload_file"]["path"])
    if not source.is_file() or digest(source) != plan["source_file"]["sha256"]:
        raise RuntimeError("Original JPG missing or changed")
    if not upload.is_file() or digest(upload) != plan["upload_file"]["sha256"] or upload.stat().st_size > 15_000_000:
        raise RuntimeError("Ozon PDF missing, changed, or over the upload size limit")
    for item in plan["local_offer_copies"]:
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError("Per-offer source copy missing or changed: " + str(path))

    workbook_reader.WORKBOOK_NUMBER_SUFFIX = "00909/23"
    rows = workbook_reader.read_target_rows()
    if len(rows) != plan["workbook_target_count"] or len(rows) != 269:
        raise RuntimeError("Workbook target set changed after planning")
    client = Client()
    fresh = live_products(client, rows)
    expected_all = {x["offer_id"]: {"product_id": x["product_id"], "sku": x["sku"], "is_archived": False}
                    for x in plan["targets"]}
    expected_all.update({x["offer_id"]: {"product_id": x["product_id"], "sku": x["sku"], "is_archived": True}
                         for x in plan["archived_excluded_pending"]})
    if set(fresh) != set(expected_all) or any(fresh.get(k) != v for k, v in expected_all.items()):
        raise RuntimeError("Fresh Ozon product identity/archive status changed; rebuild plan, no create sent")

    number = plan["number"]
    key, suffix = norm(number), norm("00909/23")
    records = certificates(client)
    candidates = [x for x in records if norm(x.get("certificate_number", "")) == key or
                  norm(x.get("certificate_number", "")).endswith(suffix)]
    if candidates:
        raise RuntimeError("Matching Ozon record appeared since plan; reconcile it instead of creating")
    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": number}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    if lookup.status_code != 404:
        raise RuntimeError(f"Exact Ozon lookup returned {lookup.status_code}; create not sent")

    targets = {str(x["sku"]): str(x["product_id"]) for x in plan["targets"]}
    if len(targets) != 267 or plan["seed_sku"] not in targets:
        raise RuntimeError("Exact active Ozon SKU mapping is incomplete")
    issue = dt.date.fromisoformat(plan["issue_date"])
    expiry = dt.date.fromisoformat(plan["expire_date"])
    params = {
        "name": "Декларация о соответствии № " + number,
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": number,
        "issue_date": issue.isoformat() + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [plan["seed_sku"]], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(upload.read_bytes()).decode("ascii"), "name": upload.name}],
    }
    state = {"started_at": now(), "phase": "create_prepared", "number": number,
             "document_type": "DECLARATION", "workbook_target_count": 269, "active_target_count": len(targets),
             "excluded_archived_offers": [x["offer_id"] for x in plan["archived_excluded_pending"]],
             "precreate_info_http_status": lookup.status_code, "precreate_info_body": lookup_body,
             "upload_sha256": plan["upload_file"]["sha256"], "source_sha256": plan["source_file"]["sha256"],
             "bind_batches": []}
    save_state(state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__})
        save_state(state)
        raise RuntimeError("Ozon create outcome uncertain; inspect live records before retry") from None
    state["create_response"] = created
    certificate_id = created.get("certificate_id")
    param_states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not certificate_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state["phase"] = "create_not_fully_validated"
        save_state(state)
        raise RuntimeError("Ozon create response incomplete; bulk bind was not sent")
    certificate_id = int(certificate_id)
    state.update({"phase": "created_response_valid", "certificate_id": certificate_id})
    save_state(state)

    records = certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(certificate_id)]
    by_number = [x for x in records if norm(x.get("certificate_number", "")) == key]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "records_by_id": len(by_id), "records_by_number": len(by_number)})
        save_state(state)
        raise RuntimeError("Created record is not uniquely visible; bind not sent")
    record = by_id[0]
    if record.get("type_code") != "declaration":
        state.update({"phase": "created_type_mismatch", "live_record": record})
        save_state(state)
        raise RuntimeError("Ozon created record type mismatch; bind not sent")
    stored_number = str(record.get("certificate_number", ""))
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(certificate_id) or info.get("type_code") != "declaration":
        state.update({"phase": "created_info_readback_mismatch", "live_record": record, "info": info})
        save_state(state)
        raise RuntimeError("Created Ozon record info mismatch; bind not sent")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "record_rejected", "live_record": record, "info": info})
        save_state(state)
        raise RuntimeError("Ozon declined the document; bind not sent")
    issue_live, expiry_live = str(info.get("issue_date", ""))[:10], str(info.get("expire_date", ""))[:10]
    if issue_live not in {plan["issue_date"], (issue + dt.timedelta(days=1)).isoformat()} or expiry_live != plan["expire_date"]:
        state.update({"phase": "created_date_conflict", "live_record": record, "info": info})
        save_state(state)
        raise RuntimeError("Ozon record dates conflict with live FSA evidence; bind not sent")

    before = read_bindings(client, certificate_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in before:
        by_sku[str(item.get("sku", ""))].append(item)
    outside = sorted(set(by_sku) - set(targets))
    duplicate = sorted(sku for sku, group in by_sku.items() if len(group) != 1)
    mismatch = sorted(sku for sku, group in by_sku.items()
                      if sku in targets and str(group[0].get("product_id")) != targets[sku])
    if outside or duplicate or mismatch:
        state.update({"phase": "initial_bindings_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicate, "product_id_mismatches": mismatch})
        save_state(state)
        raise RuntimeError("Initial bindings conflict; no additional bind sent")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "stored_number": stored_number,
                  "record_status": record.get("status_code"), "live_info": info,
                  "bindings_before": len(before), "missing_before": len(missing)})
    save_state(state)
    for start in range(0, len(missing), 500):
        batch = missing[start:start + 500]
        entry = {"index": start // 500 + 1, "count": len(batch), "phase": "prepared"}
        state["bind_batches"].append(entry)
        save_state(state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind",
                                   {"certificate_id": certificate_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state["phase"] = "bind_uncertain"
            save_state(state)
            raise RuntimeError("Ozon bind outcome uncertain; reconcile before retry") from None
        entry.update({"response": response, "phase": "accepted" if response.get("result") is True else "rejected"})
        save_state(state)
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            save_state(state)
            raise RuntimeError("Ozon rejected bind; reconcile live bindings before retry")

    final = read_bindings(client, certificate_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final:
        final_by_sku[str(item.get("sku", ""))].append(item)
    missing_after = sorted(set(targets) - set(final_by_sku))
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicate_after = sorted(sku for sku, group in final_by_sku.items() if len(group) != 1)
    mismatch_after = sorted(sku for sku, group in final_by_sku.items()
                            if sku in targets and str(group[0].get("product_id")) != targets[sku])
    if missing_after or outside_after or duplicate_after or mismatch_after or len(final) != len(targets):
        state.update({"phase": "final_bindings_mismatch", "missing_skus": missing_after,
                      "outside_skus": outside_after, "duplicate_skus": duplicate_after,
                      "product_id_mismatches": mismatch_after, "final_binding_count": len(final)})
        save_state(state)
        raise RuntimeError("Final Ozon binding set does not exactly match active targets")
    result = {
        "verified_at": now(), "number": number, "certificate_id": certificate_id,
        "stored_number": stored_number, "type_code": info.get("type_code"),
        "record_status": record.get("status_code"), "issue_date": issue_live, "expire_date": expiry_live,
        "workbook_target_count": 269, "active_target_count": len(targets), "binding_count": len(final),
        "excluded_archived_offers": [x["offer_id"] for x in plan["archived_excluded_pending"]],
        "missing_skus": missing_after, "outside_skus": outside_after,
        "duplicate_skus": duplicate_after, "product_id_mismatches": mismatch_after,
        "binding_statuses": dict(collections.Counter(str(x.get("product_status_code")) for x in final)),
        "all_bindings_approved": all(str(x.get("product_status_code")) == "approved" for x in final),
        "bindings": [{"offer_id": next(t["offer_id"] for t in plan["targets"] if t["sku"] == str(x.get("sku"))),
                      "product_id": x.get("product_id"), "sku": x.get("sku"),
                      "status": x.get("product_status_code")} for x in final],
        "source_sha256": plan["source_file"]["sha256"], "upload_sha256": plan["upload_file"]["sha256"],
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "Two mapped Ozon offers are archived, one WB card is missing, and marketplace checks must finish.",
    }
    VERIFICATION_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    state.update({"phase": "verified", "certificate_id": certificate_id,
                  "final_binding_count": len(final), "binding_statuses": result["binding_statuses"]})
    save_state(state)
    print(json.dumps({"verification": str(VERIFICATION_PATH), "number": "00909/23",
                      "certificate_id": certificate_id, "record_status": result["record_status"],
                      "binding_count": len(final), "binding_statuses": result["binding_statuses"],
                      "all_bindings_approved": result["all_bindings_approved"],
                      "excluded_archived": len(result["excluded_archived_offers"]),
                      "local_cleanup_allowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
