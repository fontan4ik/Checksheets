"""Create one verified Feron EL document on Ozon and bind only missing exact SKUs."""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, digest, now
from audit_feron_01315_53551 import norm

BASE = Path(__file__).resolve().parent


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    seen: set[str] = set()
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list page")
        ids = [str(x.get("certificate_id")) for x in batch]
        if seen.intersection(ids):
            raise RuntimeError("Duplicate certificate IDs during pagination")
        seen.update(ids)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate list pagination limit exceeded")


def read_bindings(client: Client, cert_id: int) -> list[dict]:
    out: list[dict] = []
    last_id = 0
    expected = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list",
                             {"certificate_id": cert_id, "limit": 500, "last_id": last_id})["result"]
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon binding page")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed while reading")
        out.extend(batch)
        if len(out) == expected:
            if len({str(x.get("sku")) for x in out}) != len(out):
                raise RuntimeError("Duplicate Ozon SKU binding")
            return out
        if not batch or len(out) > expected:
            raise RuntimeError("Incomplete Ozon binding pagination")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon last_id cursor did not advance")
        last_id = next_id


def live_targets(client: Client, targets: list[dict]) -> dict[str, dict]:
    offers = [str(x["offer_id"]) for x in targets]
    out: dict[str, dict] = {}
    for offset in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[offset:offset + 100]})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid live Ozon product list")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in out:
                raise RuntimeError("Duplicate or empty live offer")
            out[offer] = {"product_id": str(item.get("id", "")), "sku": str(item.get("sku", "")),
                          "is_archived": bool(item.get("is_archived"))}
    return out


def run(suffix: str) -> None:
    compact = suffix.replace("/", "")
    plan_path = BASE / f"feron_{compact}_ozon_plan.json"
    execution_path = BASE / f"feron_{compact}_ozon_execution.json"
    verification_path = BASE / f"feron_{compact}_ozon_verification.json"
    if execution_path.exists() or verification_path.exists():
        raise RuntimeError("Execution artifact exists; reconcile live Ozon before any further write")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("number_suffix") != suffix or plan.get("target_count") != 19 or len(plan.get("targets", [])) != 19:
        raise RuntimeError("Unexpected document plan or target count")
    if plan.get("local_cleanup_allowed") is not False:
        raise RuntimeError("Plan must prohibit local cleanup while marketplace coverage is incomplete")
    if not plan.get("manual_review", {}).get("completed"):
        raise RuntimeError("Source/manual evidence review is not completed")
    source = Path(plan["source_file"]["path"])
    upload = Path(plan["upload_file"]["path"])
    if not source.is_file() or digest(source) != plan["source_file"]["sha256"]:
        raise RuntimeError("Original source file missing or changed")
    if not upload.is_file() or digest(upload) != plan["upload_file"]["sha256"]:
        raise RuntimeError("Upload file missing or changed")
    if upload.stat().st_size > 15_000_000:
        raise RuntimeError("Upload file exceeds size guard")
    for item in plan["local_offer_copies"]:
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError("A per-offer local copy is missing or changed: " + str(path))

    targets = {str(x["sku"]): str(x["product_id"]) for x in plan["targets"]}
    if len(targets) != 19 or any(not sku or not product_id for sku, product_id in targets.items()):
        raise RuntimeError("Target SKU/product mapping is not unique")
    seed_sku = str(plan["seed_sku"])
    if seed_sku not in targets or targets[seed_sku] != str(plan["seed_product_id"]):
        raise RuntimeError("Seed is outside the exact target map")

    client = Client()
    live = live_targets(client, plan["targets"])
    if len(live) != 19:
        raise RuntimeError("Live Ozon product count changed")
    mismatches = {offer: {"expected": target, "live": live.get(offer)}
                  for offer, target in ((str(x["offer_id"]), {"product_id": str(x["product_id"]), "sku": str(x["sku"]), "is_archived": False})
                                        for x in plan["targets"])
                  if live.get(offer) != target}
    if mismatches:
        raise RuntimeError("Ozon product identity changed since plan; no create sent")

    number = str(plan["number"])
    key, tail = norm(number), norm(suffix)
    records = list_certificates(client)
    candidates = [x for x in records if norm(x.get("certificate_number")) == key or
                  norm(x.get("certificate_number", "")).endswith(tail)]
    if candidates:
        raise RuntimeError("Ozon now contains a matching suffix; reconcile instead of creating")

    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": number}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    if lookup.status_code != 404:
        raise RuntimeError(f"Ozon exact-number info lookup returned {lookup.status_code}; no create sent")

    issue = dt.date.fromisoformat(plan["issue_date"])
    expiry = dt.date.fromisoformat(plan["expire_date"])
    params = {
        "name": ("Сертификат соответствия № " if plan["document_type"] == "CERTIFICATE_OF_CONFORMITY" else "Декларация о соответствии № ") + number,
        "certificate_type": plan["document_type"], "certificate_country": "RU",
        "accordance_type": "EAEU", "number": number,
        "issue_date": issue.isoformat() + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(upload.read_bytes()).decode("ascii"),
                   "name": upload.name}],
    }
    state = {"started_at": now(), "phase": "create_prepared", "number": number,
             "document_type": plan["document_type"], "target_count": 19,
             "seed_sku": seed_sku, "precreate_info_http_status": lookup.status_code,
             "precreate_info_body": lookup_body, "upload_sha256": plan["upload_file"]["sha256"],
             "source_sha256": plan["source_file"]["sha256"], "bind_batches": []}
    execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Create outcome is uncertain; inspect live Ozon before retry") from None
    state["create_response"] = created
    cert_id = created.get("certificate_id")
    states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not cert_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Ozon create response is incomplete; no bulk bind sent")
    cert_id = int(cert_id)
    state.update({"certificate_id": cert_id, "phase": "created_response_valid", "updated_at": now()})
    execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    records = list_certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(cert_id)]
    by_number = [x for x in records if norm(x.get("certificate_number")) == key]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "records_by_id": len(by_id),
                      "records_by_number": len(by_number), "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Created record is not uniquely visible; no bind sent")
    record = by_id[0]
    if record.get("type_code") != plan["ozon_type_code"]:
        state.update({"phase": "created_type_mismatch", "live_record": record, "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Created Ozon record type does not match the plan")
    stored_number = str(record.get("certificate_number", ""))
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(cert_id) or info.get("type_code") != plan["ozon_type_code"]:
        state.update({"phase": "created_info_readback_mismatch", "live_record": record, "info": info, "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Created Ozon record info readback mismatch; no bind sent")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "record_rejected", "live_record": record, "info": info, "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Ozon rejected the document; no bind sent")
    issue_live, expiry_live = str(info.get("issue_date", ""))[:10], str(info.get("expire_date", ""))[:10]
    allowed_issue = {plan["issue_date"], (issue + dt.timedelta(days=1)).isoformat()}
    if issue_live not in allowed_issue or expiry_live != plan["expire_date"]:
        state.update({"phase": "created_date_conflict", "live_record": record, "info": info, "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Ozon dates conflict with official register; no bind sent")

    initial = read_bindings(client, cert_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for binding in initial:
        by_sku[str(binding.get("sku", ""))].append(binding)
    outside = sorted(set(by_sku) - set(targets))
    duplicates = sorted(sku for sku, group in by_sku.items() if len(group) != 1)
    product_mismatches = sorted(sku for sku, group in by_sku.items()
                                if sku in targets and str(group[0].get("product_id")) != targets[sku])
    if outside or duplicates or product_mismatches:
        state.update({"phase": "initial_bindings_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "product_id_mismatches": product_mismatches,
                      "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Initial bindings contain a conflict; no additional bind sent")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "stored_number": stored_number,
                  "record_status": record.get("status_code"), "live_info": info,
                  "bindings_before": len(initial), "missing_before": len(missing), "updated_at": now()})
    execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    for index in range(0, len(missing), 500):
        batch = missing[index:index + 500]
        entry = {"index": index // 500 + 1, "count": len(batch), "phase": "prepared"}
        state["bind_batches"].append(entry)
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            response = client.call("ozon", "/v1/product/certificate/bind",
                                   {"certificate_id": cert_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError("Bind outcome uncertain; reconcile live bindings before retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError("Ozon rejected bind; reconcile live state before another write")

    final = read_bindings(client, cert_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for binding in final:
        final_by_sku[str(binding.get("sku", ""))].append(binding)
    missing_after = sorted(set(targets) - set(final_by_sku))
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicate_after = sorted(sku for sku, group in final_by_sku.items() if len(group) != 1)
    mismatch_after = sorted(sku for sku, group in final_by_sku.items()
                            if sku in targets and str(group[0].get("product_id")) != targets[sku])
    if missing_after or outside_after or duplicate_after or mismatch_after or len(final) != 19:
        state.update({"phase": "final_bindings_mismatch", "missing_skus": missing_after,
                      "outside_skus": outside_after, "duplicate_skus": duplicate_after,
                      "product_id_mismatches": mismatch_after, "final_binding_count": len(final),
                      "updated_at": now()})
        execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("Final Ozon bindings do not exactly match the 19 target products")

    result = {
        "verified_at": now(), "number": number, "certificate_id": cert_id,
        "stored_number": stored_number, "type_code": info.get("type_code"),
        "record_status": record.get("status_code"), "issue_date": issue_live, "expire_date": expiry_live,
        "target_count": 19, "binding_count": len(final), "missing_skus": missing_after,
        "outside_skus": outside_after, "duplicate_skus": duplicate_after,
        "product_id_mismatches": mismatch_after,
        "binding_statuses": dict(collections.Counter(str(x.get("product_status_code")) for x in final)),
        "all_bindings_approved": all(str(x.get("product_status_code")) == "approved" for x in final),
        "bindings": [{"product_id": x.get("product_id"), "sku": x.get("sku"),
                      "status": x.get("product_status_code")} for x in final],
        "source_sha256": plan["source_file"]["sha256"], "upload_sha256": plan["upload_file"]["sha256"],
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "At least three target WB cards are absent, and Ozon must complete final checks for all bindings.",
    }
    verification_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    state.update({"phase": "verified", "certificate_id": cert_id, "final_binding_count": len(final),
                  "binding_statuses": result["binding_statuses"], "updated_at": now()})
    execution_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verification": str(verification_path), "number": suffix,
                      "certificate_id": cert_id, "record_status": result["record_status"],
                      "binding_count": len(final), "binding_statuses": result["binding_statuses"],
                      "all_bindings_approved": result["all_bindings_approved"],
                      "local_cleanup_allowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("number_suffix", choices=("05934/22", "53534/22"))
    run(parser.parse_args().number_suffix)
