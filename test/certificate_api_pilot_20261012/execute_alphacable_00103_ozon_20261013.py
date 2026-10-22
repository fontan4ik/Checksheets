"""Create AlphaCable certificate 00103/25 on Ozon and bind the seven exact offers."""
from __future__ import annotations

import base64
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PLAN = BASE / "alphacable_00103_live_preflight_20261013.json"
EXECUTION = BASE / "alphacable_00103_ozon_execution_20261013.json"
VERIFICATION = BASE / "alphacable_00103_ozon_verification_20261013.json"
PDF = ROOT / "output_to_user/certificates/alphacable/ЕАЭС_RU_С-RU.АД38.В.00103-25.pdf"
NUMBER = "ЕАЭС RU С-RU.АД38.В.00103/25"
FSA_URL = "https://pub.fsa.gov.ru/rss/certificate/view/3579119/baseInfo"
ISSUE = "2025-05-21"
EXPIRY = "2030-05-20"
MAX_REQUEST_BYTES = 15_000_000

sys.path.insert(0, str(BASE))
from api_client import Client, digest, now, save  # noqa: E402


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def list_certificates(client: Client) -> list[dict]:
    out = []
    page = 1
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list",
                             {"page": page, "page_size": 100}).get("result", {})
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Malformed Ozon certificate-list response")
        out.extend(batch)
        if len(batch) < 100:
            if len({str(x.get("certificate_id")) for x in out}) != len(out):
                raise RuntimeError("Duplicate Ozon certificate IDs")
            return out
        page += 1
    raise RuntimeError("Ozon certificate-list pagination limit exceeded")


def read_bindings(client: Client, cert_id: int) -> list[dict]:
    return client.ozon_bindings(cert_id)


def live_product_ids(client: Client, targets: list[dict]) -> None:
    offers = [str(x["offer_id"]) for x in targets]
    body = client.call("ozon", "/v3/product/info/list", {"offer_id": offers})
    items = body.get("items") or body.get("result", {}).get("items")
    if not isinstance(items, list):
        raise RuntimeError("Fresh Ozon product info omitted items")
    live = {}
    for row in items:
        offer = str(row.get("offer_id") or "")
        if not offer or offer in live:
            raise RuntimeError("Ozon returned missing or duplicate product offer")
        live[offer] = row
    expected = {str(x["offer_id"]): x for x in targets}
    if set(live) != set(expected):
        raise RuntimeError("Ozon product info offer set changed")
    for offer, target in expected.items():
        row = live[offer]
        if (str(row.get("id") or row.get("product_id") or "") != str(target["product_id"])
                or str(row.get("sku") or "") != str(target["sku"])
                or row.get("is_archived")):
            raise RuntimeError(f"Ozon product identity/archive state changed for {offer}")


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("Execution journal already exists; reconcile live state before any write")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ozon = plan.get("ozon", {})
    targets = plan.get("targets") or []
    if (len(targets) != 7 or not ozon.get("all_identities_exact") or not ozon.get("all_in_scope")
            or ozon.get("matching_number_records") or ozon.get("exact_number_lookup", {}).get("http_status") != 404
            or ozon.get("exact_number_lookup", {}).get("body", {}).get("code") != 5):
        raise RuntimeError("Saved Ozon preflight does not prove seven exact in-scope targets and certificate absence")
    if not PDF.is_file() or digest(PDF) != plan.get("file_sha256"):
        raise RuntimeError("Official AlphaCable PDF missing or changed since preflight")

    by_sku = {str(x["sku"]): str(x["product_id"]) for x in targets}
    if len(by_sku) != 7 or any(not k or not v for k, v in by_sku.items()):
        raise RuntimeError("Target SKU/Product ID map is not one-to-one")

    client = Client()
    live_product_ids(client, targets)
    existing = list_certificates(client)
    if any(norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER) for x in existing):
        raise RuntimeError("Ozon now contains this number; reconcile before continuing")
    lookup = client.http.post("https://api-seller.ozon.ru/v1/product/certificate/info",
                              data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
                              headers=client.ozon_headers, timeout=(15, 60))
    try:
        lookup_body = lookup.json()
    except ValueError:
        lookup_body = {}
    if lookup.status_code != 404 or lookup_body.get("code") != 5:
        raise RuntimeError("Ozon exact-number lookup no longer proves absence; no create sent")

    issue = dt.date.fromisoformat(ISSUE)
    expiry = dt.date.fromisoformat(EXPIRY)
    seed = sorted(targets, key=lambda x: str(x["offer_id"]))[0]
    params = {
        "name": "Сертификат соответствия № " + NUMBER,
        "certificate_type": "CERTIFICATE_OF_CONFORMITY",
        "certificate_country": "RU", "accordance_type": "EAEU", "number": NUMBER,
        "issue_date": ISSUE + "T00:00:00Z",
        "expired_date": {"date": {"day": expiry.day, "month": expiry.month, "year": expiry.year}},
        "skus": [str(seed["sku"])], "product_type": "UNKNOWN",
        "link_to_registry": FSA_URL,
        "files": [{"file_content": base64.b64encode(PDF.read_bytes()).decode("ascii"),
                   "name": PDF.name}],
    }
    request = json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode()
    if len(request) >= MAX_REQUEST_BYTES:
        raise RuntimeError("Ozon create request exceeds the tested request size")
    state = {
        "started_at": now(), "phase": "create_prepared", "number": NUMBER,
        "document_type": "CERTIFICATE_OF_CONFORMITY", "fsa_record_id": 3579119,
        "fsa_registry_url": FSA_URL, "issue_date": ISSUE, "expiry_date": EXPIRY,
        "target_count": len(targets), "targets": targets,
        "source_pdf_path": str(PDF), "source_pdf_sha256": digest(PDF),
        "source_pdf_bytes": PDF.stat().st_size,
        "seed_offer_id": seed["offer_id"], "seed_product_id": seed["product_id"], "seed_sku": seed["sku"],
        "precreate_certificate_count": len(existing),
        "precreate_info_lookup": {"http_status": lookup.status_code, "body": lookup_body},
        "create_request_sha256": hashlib.sha256(request).hexdigest(),
        "create_request_bytes": len(request), "bind_batches": [],
    }
    save(EXECUTION.name, state)
    state.update({"phase": "create_sent", "updated_at": now()})
    save(EXECUTION.name, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon create outcome is uncertain; reconcile live state before retry") from None
    state["create_response"] = created
    cert_id = created.get("certificate_id")
    param_states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not cert_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon create response incomplete; binding stopped")
    cert_id = int(cert_id)
    state.update({"certificate_id": cert_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION.name, state)

    records = list_certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(cert_id)]
    by_number = [x for x in records if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "records_by_id": len(by_id),
                      "records_by_number": len(by_number), "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Created record is not uniquely visible; binding stopped")
    record = by_id[0]
    if record.get("type_code") != "certificate_of_conformity":
        state.update({"phase": "created_type_mismatch", "live_record": record, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon stored document type mismatch; binding stopped")
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": NUMBER}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(cert_id):
        state.update({"phase": "created_info_readback_mismatch", "info": info, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon certificate detail readback mismatch; binding stopped")
    issue_live = str(info.get("issue_date", ""))[:10]
    expiry_live = str(info.get("expire_date", ""))[:10]
    if issue_live not in {ISSUE, (issue + dt.timedelta(days=1)).isoformat()} or expiry_live != EXPIRY:
        state.update({"phase": "created_date_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon readback dates differ from the verified FSA record")
    record_status = str(info.get("status_code", record.get("status_code", "")))
    if record_status in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "record_rejected", "live_record": record, "live_info": info, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Ozon rejected the certificate; binding stopped")

    before = read_bindings(client, cert_id)
    before_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for row in before:
        before_by_sku[str(row.get("sku") or "")].append(row)
    outside = sorted(set(before_by_sku) - set(by_sku))
    duplicates = sorted(sku for sku, rows in before_by_sku.items() if len(rows) != 1)
    mismatches = sorted(sku for sku, rows in before_by_sku.items()
                        if sku in by_sku and str(rows[0].get("product_id")) != by_sku[sku])
    if outside or duplicates or mismatches:
        state.update({"phase": "initial_binding_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "product_id_mismatches": mismatches,
                      "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Initial binding set conflicts with exact target mapping")
    missing = sorted(set(by_sku) - set(before_by_sku))
    state.update({"phase": "binding_missing_only", "record_status": record_status,
                  "live_record": record, "live_info": info,
                  "initial_binding_count": len(before), "missing_before": missing,
                  "updated_at": now()})
    save(EXECUTION.name, state)
    for offset in range(0, len(missing), 500):
        batch = missing[offset:offset + 500]
        entry = {"batch": len(state["bind_batches"]) + 1, "skus": batch, "phase": "prepared"}
        state["bind_batches"].append(entry)
        save(EXECUTION.name, state)
        try:
            response = client.call("ozon", "/v1/product/certificate/bind",
                                   {"certificate_id": cert_id, "skus": batch}, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(EXECUTION.name, state)
            raise RuntimeError("Ozon bind outcome uncertain; reconcile before any retry") from None
        entry["response"] = response
        entry["phase"] = "accepted" if response.get("result") is True else "rejected"
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION.name, state)
        if entry["phase"] != "accepted":
            state.update({"phase": "bind_rejected", "updated_at": now()})
            save(EXECUTION.name, state)
            raise RuntimeError("Ozon rejected binding; reconcile live state before retry")

    final = read_bindings(client, cert_id)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for row in final:
        final_by_sku[str(row.get("sku") or "")].append(row)
    outside_after = sorted(set(final_by_sku) - set(by_sku))
    missing_after = sorted(set(by_sku) - set(final_by_sku))
    duplicate_after = sorted(sku for sku, rows in final_by_sku.items() if len(rows) != 1)
    mismatch_after = sorted(sku for sku in set(by_sku) & set(final_by_sku)
                            if str(final_by_sku[sku][0].get("product_id")) != by_sku[sku])
    if outside_after or missing_after or duplicate_after or mismatch_after:
        state.update({"phase": "final_readback_incomplete", "outside_skus": outside_after,
                      "missing_skus": missing_after, "duplicate_skus": duplicate_after,
                      "product_id_mismatches": mismatch_after, "updated_at": now()})
        save(EXECUTION.name, state)
        raise RuntimeError("Final Ozon binding set does not exactly match seven targets")
    statuses = collections.Counter(str(x.get("product_status_code") or "") for x in final)
    verification = {
        "checked_at_utc": now(), "certificate_id": cert_id, "number": NUMBER,
        "record_status": record_status, "type_code": info.get("type_code"),
        "issue_date": issue_live, "expiry_date": expiry_live,
        "target_count": len(targets), "binding_count": len(final),
        "all_target_product_id_sku_pairs_present": True,
        "outside_skus": outside_after, "missing_skus": missing_after,
        "duplicates": duplicate_after, "product_id_mismatches": mismatch_after,
        "binding_status_counts": dict(statuses),
        "all_target_bindings_approved": len(final) == 7 and statuses == {"approved": 7},
        "bindings": final,
    }
    state.update({"phase": "ozon_verified_approved" if verification["all_target_bindings_approved"]
                  else "ozon_applied_status_pending", "verification": verification, "updated_at": now()})
    save(EXECUTION.name, state)
    save(VERIFICATION.name, verification)
    print(json.dumps({"certificate_id": cert_id, "record_status": record_status,
                      "binding_status_counts": dict(statuses),
                      "all_target_bindings_approved": verification["all_target_bindings_approved"],
                      "execution": str(EXECUTION), "verification": str(VERIFICATION)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
