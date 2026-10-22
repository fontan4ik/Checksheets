"""Create declaration 54301/25 on Ozon once, bind only missing exact SKUs, verify."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, digest, now, save
from audit_feron_01315_53551 import norm

BASE = Path(__file__).resolve().parent
PLAN = BASE / "feron_54301_ozon_plan.json"
EXECUTION = BASE / "feron_54301_ozon_execution.json"
VERIFICATION = BASE / "feron_54301_ozon_verification.json"


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid Ozon certificate list response")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Ozon certificate pagination limit exceeded")


def read_bindings(client: Client, cert_id: int) -> list[dict]:
    out: list[dict] = []
    last_id = 0
    expected = None
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list",
                             {"certificate_id": cert_id, "limit": 500,
                              "last_id": last_id})["result"]
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid Ozon binding page")
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError("Ozon binding count changed during read")
        out.extend(batch)
        if len(out) == expected:
            if len({str(x.get("sku")) for x in out}) != len(out):
                raise RuntimeError("Duplicate Ozon SKU bindings")
            return out
        if not batch or len(out) > expected:
            raise RuntimeError("Incomplete Ozon binding pagination")
        next_id = int(batch[-1].get("product_id", 0))
        if next_id <= last_id:
            raise RuntimeError("Ozon last_id cursor did not advance")
        last_id = next_id


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("Execution artifact already exists; reconcile before any write")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if len(plan.get("targets", [])) != 64 or plan.get("target_count") != 64:
        raise RuntimeError("Unexpected Ozon target count")
    if plan["ozon_preflight"].get("exact_matches") or plan["ozon_preflight"].get("substring_matches"):
        raise RuntimeError("Ozon preflight found an existing matching certificate")
    source = Path(plan["upload_file"]["path"])
    if not source.is_file() or digest(source) != plan["upload_file"]["sha256"]:
        raise RuntimeError("Upload PDF missing or changed")
    if source.stat().st_size > 15_000_000:
        raise RuntimeError("Upload PDF exceeds conservative size guard")
    targets = {str(x["sku"]): str(x["product_id"]) for x in plan["targets"]}
    if len(targets) != 64 or any(not sku or not product_id for sku, product_id in targets.items()):
        raise RuntimeError("Target SKU/product_id mapping is not one-to-one")
    seed_sku = str(plan["seed_sku"])
    if seed_sku not in targets or targets[seed_sku] != str(plan["seed_product_id"]):
        raise RuntimeError("Seed SKU is not an exact target pair")

    client = Client()
    number = plan["number"]
    current = list_certificates(client)
    key = norm(number)
    exact = [x for x in current if norm(x.get("certificate_number")) == key]
    substring = [x for x in current if key in norm(x.get("certificate_number"))]
    if exact or substring:
        raise RuntimeError("Ozon now has a matching record; reconcile instead of creating")

    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": number}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    if lookup.status_code == 200:
        raise RuntimeError("Ozon info lookup resolves the certificate; reconcile before creating")
    if lookup.status_code != 404:
        raise RuntimeError(f"Ozon info lookup inconclusive ({lookup.status_code}); creation stopped")

    issue = dt.date.fromisoformat(plan["issue_date"])
    expiry = dt.date.fromisoformat(plan["expire_date"])
    params = {
        "name": "Декларация о соответствии № " + number,
        "certificate_type": "DECLARATION", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": number,
        "issue_date": issue.isoformat() + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"),
                   "name": "FERON_declaration_54301_25.pdf"}],
    }
    state = {"started_at": now(), "phase": "create_prepared", "number": number,
             "target_count": len(targets), "seed_sku": seed_sku,
             "precreate_lookup": {"http_status": lookup.status_code, "body": lookup_body},
             "source_sha256": plan["source_file"]["sha256"],
             "upload_sha256": plan["upload_file"]["sha256"], "bind_batches": []}
    save("feron_54301_ozon_execution.json", state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create",
                              {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Create outcome uncertain; reconcile live Ozon before retry") from None
    state["create_response"] = created
    cert_id = created.get("certificate_id")
    param_states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not cert_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Ozon create response incomplete; no bulk SKU bind was sent")
    cert_id = int(cert_id)
    state.update({"certificate_id": cert_id, "phase": "created_response_valid", "updated_at": now()})
    save("feron_54301_ozon_execution.json", state)

    records = list_certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(cert_id)]
    by_number = [x for x in records if norm(x.get("certificate_number")) == key]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "records_by_id": len(by_id),
                      "records_by_number": len(by_number), "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Created record is not uniquely visible; no bind was sent")
    record = by_id[0]
    stored_number = str(record.get("certificate_number", ""))
    if record.get("type_code") != "declaration":
        raise RuntimeError("Created Ozon record type differs from declaration")
    record_status = str(record.get("status_code", ""))
    if record_status in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "record_rejected", "live_record": record, "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Ozon rejected declaration; bulk binding stopped")

    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(cert_id):
        state.update({"phase": "created_info_readback_mismatch", "live_record": record,
                      "info": info, "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Ozon stored-number readback mismatch; no bind was sent")
    if info.get("type_code") != "declaration":
        raise RuntimeError("Ozon info type differs from declaration")
    issue_live = str(info.get("issue_date", ""))[:10]
    expiry_live = str(info.get("expire_date", ""))[:10]
    if issue_live not in {plan["issue_date"], (issue + dt.timedelta(days=1)).isoformat()} or expiry_live != plan["expire_date"]:
        state.update({"phase": "created_date_conflict", "live_record": record,
                      "info": info, "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Ozon date readback conflicts with the approved FSA/WB date")

    initial = read_bindings(client, cert_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in initial:
        by_sku[str(item.get("sku", ""))].append(item)
    outside = sorted(set(by_sku) - set(targets))
    duplicates = sorted(sku for sku, items in by_sku.items() if len(items) != 1)
    mismatches = sorted(sku for sku, items in by_sku.items()
                        if sku in targets and str(items[0].get("product_id")) != targets[sku])
    if outside or duplicates or mismatches:
        state.update({"phase": "initial_bindings_conflict", "outside": outside,
                      "duplicates": duplicates, "product_id_mismatches": mismatches, "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Initial bindings contain an outside SKU, duplicate, or product mismatch")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "stored_number": stored_number,
                  "live_info": info, "record_status": record_status,
                  "bindings_before": len(initial), "missing_before": len(missing), "updated_at": now()})
    save("feron_54301_ozon_execution.json", state)

    for index in range(0, len(missing), 500):
        batch = missing[index:index + 500]
        entry = {"index": index // 500 + 1, "count": len(batch), "phase": "prepared"}
        state["bind_batches"].append(entry)
        save("feron_54301_ozon_execution.json", state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind",
                                   {"certificate_id": cert_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save("feron_54301_ozon_execution.json", state)
            raise RuntimeError("Bind outcome uncertain; reconcile before retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save("feron_54301_ozon_execution.json", state)
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            save("feron_54301_ozon_execution.json", state)
            raise RuntimeError("Ozon rejected bind; reconcile live bindings before another write")

    final = read_bindings(client, cert_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final:
        final_by_sku[str(item.get("sku", ""))].append(item)
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicate_after = sorted(sku for sku, items in final_by_sku.items() if len(items) != 1)
    missing_after = sorted(set(targets) - set(final_by_sku))
    mismatch_after = sorted(sku for sku in set(targets) & set(final_by_sku)
                            if str(final_by_sku[sku][0].get("product_id")) != targets[sku])
    if outside_after or duplicate_after or missing_after or mismatch_after:
        state.update({"phase": "final_readback_incomplete", "updated_at": now(),
                      "outside": outside_after, "duplicates": duplicate_after,
                      "missing": missing_after, "product_id_mismatches": mismatch_after})
        save("feron_54301_ozon_execution.json", state)
        raise RuntimeError("Final Ozon binding readback does not match all 64 targets")
    statuses = collections.Counter(str(x.get("product_status_code")) for x in final)
    verified = {"checked_at": now(), "certificate_id": cert_id, "stored_number": stored_number,
                "record_status": record_status, "type_code": info.get("type_code"),
                "issue_date": str(info.get("issue_date", ""))[:10],
                "expire_date": str(info.get("expire_date", ""))[:10],
                "target_count": len(targets), "binding_count": len(final),
                "missing": missing_after, "outside": outside_after,
                "duplicates": duplicate_after, "product_id_mismatches": mismatch_after,
                "binding_statuses": dict(statuses),
                "all_target_links_present": True,
                "all_bindings_approved": len(final) == 64 and statuses == {"approved": 64},
                "bindings": [{"sku": str(x.get("sku")), "product_id": str(x.get("product_id")),
                              "status": x.get("product_status_code")} for x in final]}
    save("feron_54301_ozon_verification.json", verified)
    state.update({"phase": "verified", "verification_path": str(VERIFICATION),
                  "binding_statuses": dict(statuses), "updated_at": now()})
    save("feron_54301_ozon_execution.json", state)
    print(json.dumps({"phase": "verified", "certificate_id": cert_id,
                      "stored_number": stored_number, "record_status": record_status,
                      "target_count": len(targets), "binding_statuses": dict(statuses),
                      "all_bindings_approved": verified["all_bindings_approved"],
                      "verification": str(VERIFICATION)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
