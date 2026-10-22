"""Create Feron certificate 01324/22 on Ozon and bind the exact 103 target SKUs."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
from pathlib import Path

from api_client import Client, digest, now
from execute_feron_04998_ozon import get_info, list_certificates, normalize, read_bindings

BASE = Path(__file__).resolve().parent
PLAN = BASE / "feron_01324_ozon_plan.json"
EXECUTION = BASE / "feron_01324_ozon_execution.json"
VERIFICATION = BASE / "feron_01324_ozon_verification.json"
NUMBER = "ЕАЭС RU С-CN.НВ85.В.01324/22"


def save(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("Execution evidence already exists; reconcile live Ozon before any write")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan.get("number") != NUMBER or plan.get("target_count") != 103 or len(plan.get("targets", [])) != 103:
        raise RuntimeError("Unexpected certificate plan or target count")
    if plan["ozon_preflight"].get("matching_records") or plan["ozon_preflight"].get("number_substring_matches"):
        raise RuntimeError("Ozon preflight found a matching record; reconcile instead of creating")
    source = Path(plan["source_file"]["path"])
    if not source.is_file() or digest(source) != plan["source_file"]["sha256"]:
        raise RuntimeError("Original certificate PDF is missing or changed")
    if source.stat().st_size > 15_000_000:
        raise RuntimeError("Original certificate PDF exceeds conservative Ozon payload limit")

    targets = {str(x["sku"]): str(x["product_id"]) for x in plan["targets"]}
    if len(targets) != 103 or any(not k or not v for k, v in targets.items()):
        raise RuntimeError("Ozon SKU/product_id target map is not one-to-one")
    seed_sku = str(plan["seed_sku"])
    if seed_sku not in targets or targets[seed_sku] != str(plan["seed_product_id"]):
        raise RuntimeError("Seed SKU is not an exact target pair")
    for item in plan["local_offer_copies"]:
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError("Offer copy changed after plan: " + item["offer_id"])

    client = Client()
    live_products: dict[str, dict] = {}
    offers = [x["offer_id"] for x in plan["targets"]]
    for start in range(0, len(offers), 100):
        body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[start:start + 100]})
        items = body.get("items") or body.get("result", {}).get("items")
        if not isinstance(items, list):
            raise RuntimeError("Invalid Ozon product info response before create")
        for item in items:
            offer = str(item.get("offer_id", ""))
            if not offer or offer in live_products:
                raise RuntimeError("Duplicate or empty live Ozon offer before create")
            live_products[offer] = {"product_id": str(item.get("id", "")),
                                    "sku": str(item.get("sku", "")),
                                    "is_archived": bool(item.get("is_archived"))}
    expected = {x["offer_id"]: {"product_id": str(x["product_id"]), "sku": str(x["sku"]),
                                "is_archived": False} for x in plan["targets"]}
    if live_products != expected:
        raise RuntimeError("Live Ozon offer/product_id/SKU or archive state changed; create not sent")

    certs = list_certificates(client)
    key, suffix = normalize(NUMBER), normalize("01324/22")
    if any(normalize(x.get("certificate_number")) == key or
           normalize(x.get("certificate_number", "")).endswith(suffix) for x in certs):
        raise RuntimeError("Matching Ozon certificate appeared; reconcile instead of creating")
    precheck = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
        headers=client.ozon_headers, timeout=(15, 60))
    try:
        precheck_body = precheck.json()
    except ValueError:
        precheck_body = {}
    if precheck.status_code != 404 or precheck_body.get("code") != 5:
        raise RuntimeError("Exact Ozon lookup was inconclusive; create not sent")

    issue = dt.date.fromisoformat(plan["issue_date"])
    expiry = dt.date.fromisoformat(plan["expire_date"])
    params = {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY", "certificate_country": "RU",
        "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": issue.isoformat() + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [seed_sku], "product_type": "UNKNOWN",
        "files": [{"file_content": base64.b64encode(source.read_bytes()).decode("ascii"),
                   "name": "FERON_certificate_01324_22.pdf"}],
    }
    state = {"started_at": now(), "phase": "create_prepared", "number": NUMBER,
             "target_count": 103, "seed_offer": plan["seed_offer"], "seed_sku": seed_sku,
             "source_sha256": plan["source_file"]["sha256"],
             "estimated_request_bytes": len(json.dumps({"params": params}, ensure_ascii=False).encode()),
             "precreate_lookup": {"http_status": precheck.status_code, "body": precheck_body},
             "bind_batches": []}
    save(EXECUTION, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon create outcome uncertain; reconcile live record before retry") from None
    state["create_response"] = created
    cert_id = created.get("certificate_id")
    states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not cert_id or created.get("status") != "COMPLETED" or not states or set(states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon create response is incomplete; no additional binds sent")
    cert_id = int(cert_id)
    state.update({"certificate_id": cert_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION, state)

    visible = list_certificates(client)
    by_id = [x for x in visible if str(x.get("certificate_id")) == str(cert_id)]
    by_number = [x for x in visible if normalize(x.get("certificate_number")) == key]
    if len(by_id) != 1 or len(by_number) != 1 or by_id[0] != by_number[0]:
        state.update({"phase": "created_not_uniquely_visible", "by_id_count": len(by_id),
                      "by_number_count": len(by_number), "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Created Ozon certificate is not uniquely visible; remaining binds stopped")
    stored_number = str(by_id[0].get("certificate_number", ""))
    info = get_info(client, stored_number)
    if int(info.get("certificate_id", -1)) != cert_id or info.get("type_code") != "certificate_of_conformity":
        raise RuntimeError("Ozon record ID/type mismatch; remaining binds stopped")
    if info.get("status_code") in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "certificate_rejected", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon rejected the certificate; remaining binds stopped")
    issue_live, expiry_live = str(info.get("issue_date", ""))[:10], str(info.get("expire_date", ""))[:10]
    if issue_live not in {plan["issue_date"], (issue + dt.timedelta(days=1)).isoformat()} or expiry_live != plan["expire_date"]:
        state.update({"phase": "live_date_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon certificate dates differ from the original and FSA registry")

    initial = read_bindings(client, cert_id)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in initial:
        by_sku[str(item.get("sku", ""))].append(item)
    outside = sorted(set(by_sku) - set(targets))
    duplicates = sorted(s for s, group in by_sku.items() if len(group) != 1)
    mismatches = sorted(s for s, group in by_sku.items()
                        if s in targets and {str(x.get("product_id")) for x in group} != {targets[s]})
    if outside or duplicates or mismatches:
        state.update({"phase": "initial_bindings_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "product_id_mismatches": mismatches,
                      "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Initial seed binding is inconsistent; no more binds sent")
    missing = sorted(set(targets) - set(by_sku))
    state.update({"phase": "binding_missing_only", "stored_number": stored_number,
                  "record_status": by_id[0].get("status_code"), "live_info": info,
                  "initial_binding_count": len(initial), "missing_before_bind": len(missing), "updated_at": now()})
    save(EXECUTION, state)
    for index, start in enumerate(range(0, len(missing), 500), 1):
        batch = missing[start:start + 500]
        entry = {"index": index, "sku_count": len(batch), "first_sku": batch[0],
                 "last_sku": batch[-1], "phase": "prepared"}
        state["bind_batches"].append(entry)
        save(EXECUTION, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind",
                                   {"certificate_id": cert_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(EXECUTION, state)
            raise RuntimeError("Ozon bind outcome uncertain; reconcile live bindings before retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION, state)
        if entry["phase"] != "accepted":
            state["phase"] = "bind_rejected"
            save(EXECUTION, state)
            raise RuntimeError("Ozon rejected the bind batch; reconcile before retry")

    final_info = get_info(client, stored_number)
    final = read_bindings(client, cert_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final:
        final_by_sku[str(item.get("sku", ""))].append(item)
    missing_after = sorted(set(targets) - set(final_by_sku))
    outside_after = sorted(set(final_by_sku) - set(targets))
    duplicates_after = sorted(s for s, group in final_by_sku.items() if len(group) != 1)
    identity_mismatches = [{"sku": sku, "expected_product_id": targets[sku],
                            "live_product_ids": sorted({str(x.get("product_id")) for x in final_by_sku[sku]})}
                           for sku in sorted(set(targets) & set(final_by_sku))
                           if {str(x.get("product_id")) for x in final_by_sku[sku]} != {targets[sku]}]
    statuses = collections.Counter(str(x.get("product_status_code")) for x in final
                                   if str(x.get("sku")) in targets)
    verification = {"verified_at": now(), "number": NUMBER, "stored_number": stored_number,
        "certificate_id": cert_id, "certificate_info": final_info, "target_skus": 103,
        "binding_count": len(final), "covered_target_skus": len(set(targets) & set(final_by_sku)),
        "missing_skus": missing_after, "outside_skus": outside_after,
        "duplicate_skus": duplicates_after, "product_id_mismatches": identity_mismatches,
        "binding_statuses": dict(statuses),
        "bindings": [{"offer_id": next(x["offer_id"] for x in plan["targets"] if x["sku"] == str(b.get("sku"))),
                      "product_id": str(b.get("product_id")), "sku": str(b.get("sku")),
                      "status": str(b.get("product_status_code"))} for b in final]}
    verification["all_target_skus_linked"] = not any((missing_after, outside_after, duplicates_after, identity_mismatches))
    verification["certificate_approved"] = final_info.get("status_code") == "approved"
    verification["all_bindings_approved"] = bool(statuses) and set(statuses) == {"approved"}
    verification["all_verified"] = (verification["all_target_skus_linked"] and
                                     verification["certificate_approved"] and
                                     verification["all_bindings_approved"])
    verification["local_cleanup_allowed"] = False
    verification["local_cleanup_reason"] = "WB still has missing cards and pending certificate rows; keep originals and local copies."
    save(VERIFICATION, verification)
    state.update({"phase": "all_verified" if verification["all_verified"] else "bindings_visible_review_pending",
                  "finished_at": now(), "verification_path": str(VERIFICATION)})
    save(EXECUTION, state)
    print(json.dumps({k: verification[k] for k in
        ("number", "certificate_id", "target_skus", "binding_count", "binding_statuses",
         "certificate_approved", "all_target_skus_linked", "all_verified", "local_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
