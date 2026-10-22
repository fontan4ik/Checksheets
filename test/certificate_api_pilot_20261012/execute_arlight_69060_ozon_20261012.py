"""Create the verified Arlight declaration on Ozon once, then bind exact products."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

PREFLIGHT = BASE / "arlight_69060_preflight_20261012.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/F6522803E046324C87BC430F67671163.pdf"
EXECUTION = BASE / "arlight_69060_ozon_execution_20261012.json"
VERIFICATION = BASE / "arlight_69060_ozon_verification_20261012.json"
NUMBER = "ЕАЭС N RU Д-HK.РА02.В.69060/25"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/19978046/product"
SOURCE_SHA256 = "baeb142abdd28d42ae6cbbe4993134f3726364e94ca66c3b09d913d52b81db04"
ISSUE_DATE = "2025-03-10"
EXPIRY_DATE = "2030-03-09"
MAX_REQUEST_BYTES = 15_000_000


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def read_certificates(client: Client) -> list[dict]:
    rows = []
    page = 1
    last_page_count = 0
    while True:
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result", {})
        batch = result.get("certificates")
        count = result.get("page_count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Ozon certificate list omitted certificates/page_count")
        if count < page or count < last_page_count:
            raise RuntimeError("Ozon certificate pagination cursor/count moved backwards")
        last_page_count = count
        rows.extend(batch)
        if page >= count or len(batch) < 100:
            break
        page += 1
    if len({str(x.get("certificate_id")) for x in rows}) != len(rows):
        raise RuntimeError("Ozon certificate list contains duplicate certificate IDs")
    return rows


def fresh_product_info(client: Client, targets: list[dict]) -> None:
    expected = {str(x["offer_id"]): x for x in targets}
    rows = {}
    offers = sorted(expected)
    for offset in range(0, len(offers), 100):
        batch = offers[offset:offset + 100]
        result = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items")
        if not isinstance(result, list):
            raise RuntimeError("Ozon product info omitted items")
        for item in result:
            offer = str(item.get("offer_id") or "")
            if offer not in batch or offer in rows:
                raise RuntimeError("Ozon product info returned an unknown or duplicate offer")
            rows[offer] = item
    if set(rows) != set(expected):
        raise RuntimeError(f"Fresh Ozon info returned {len(rows)} of {len(expected)} offers")
    for offer, target in expected.items():
        row = rows[offer]
        product_id = str(row.get("product_id") or row.get("id") or "")
        if (product_id != str(target["product_id"]) or str(row.get("sku")) != str(target["sku"])
                or row.get("is_archived")):
            raise RuntimeError(f"Ozon product ID/SKU/archive state changed for {offer}")


def read_info(client: Client) -> dict:
    return client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER,
    }).get("result", {})


def read_bindings(client: Client, certificate_id: int) -> list[dict]:
    return client.ozon_bindings(certificate_id)


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("An execution journal already exists; reconcile live Ozon state before any further write")
    plan = json.loads(PREFLIGHT.read_text())
    if (not plan.get("ready_for_ozon_create_and_binding") or len(plan.get("targets", [])) != 549
            or plan.get("ozon_attribute_mismatch_count") != 0
            or plan.get("tnved_scope_exclusions", [{}])[0].get("offer_id") != "028858(1)-1"):
        raise RuntimeError("Saved preflight is not the complete, expected 549-product exact-scope plan")
    if not SOURCE.is_file() or digest(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("Official local upload PDF is missing or changed")
    targets = plan["targets"]
    by_sku = {str(x["sku"]): str(x["product_id"]) for x in targets}
    if len(by_sku) != 549 or len({str(x["product_id"]) for x in targets}) != 549:
        raise RuntimeError("Target SKU/product identity mapping is not one-to-one")

    client = Client()
    fresh_product_info(client, targets)
    live_records = read_certificates(client)
    same_number = [x for x in live_records
                   if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if same_number:
        raise RuntimeError("Ozon now has this normalized declaration number; reconcile rather than create")
    # The single-number information lookup must also prove absence before creating.
    response = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
        headers=client.ozon_headers, timeout=(15, 60),
    )
    try:
        lookup_body = response.json()
    except ValueError:
        lookup_body = {}
    if response.status_code != 404 or lookup_body.get("code") != 5:
        raise RuntimeError("Ozon exact-number lookup did not confirm absence; no create sent")

    seed = sorted(targets, key=lambda x: str(x["offer_id"]))[0]
    params = {
        "name": "Декларация о соответствии № " + NUMBER,
        "certificate_type": "DECLARATION",
        "certificate_country": "RU",
        "accordance_type": "EAEU",
        "number": NUMBER,
        "issue_date": ISSUE_DATE + "T00:00:00Z",
        "expired_date": {"date": {"day": 9, "month": 3, "year": 2030}},
        "skus": [str(seed["sku"])],
        "product_type": "UNKNOWN",
        "link_to_registry": FSA_URL,
        "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                   "name": SOURCE.name}],
    }
    request_bytes = json.dumps({"params": params}, ensure_ascii=False, separators=(",", ":")).encode()
    if len(request_bytes) >= MAX_REQUEST_BYTES:
        raise RuntimeError("Ozon create request would exceed the tested 15 MB limit")
    state = {
        "started_at": now(), "phase": "create_prepared", "number": NUMBER,
        "document_type": "DECLARATION", "target_offer_count": len(targets),
        "target_sku_count": len(by_sku), "excluded_out_of_tnved_scope": plan["tnved_scope_exclusions"],
        "seed_offer_id": seed["offer_id"], "seed_product_id": seed["product_id"],
        "seed_sku": seed["sku"], "source_pdf_sha256": digest(SOURCE),
        "source_pdf_bytes": SOURCE.stat().st_size, "fsa_registry_url": FSA_URL,
        "precreate_certificate_count": len(live_records),
        "precreate_info_lookup": {"http_status": response.status_code, "body": lookup_body},
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "request_bytes": len(request_bytes), "bind_batches": [],
    }
    save(EXECUTION, state)
    state.update({"phase": "create_sent", "updated_at": now()})
    save(EXECUTION, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", {"params": params}, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon create result is uncertain; reconcile live state before retry") from None
    state["create_response"] = created
    certificate_id = created.get("certificate_id")
    param_states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not certificate_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon create response is incomplete/invalid; no bulk bindings sent")
    certificate_id = int(certificate_id)
    state.update({"certificate_id": certificate_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION, state)

    records = read_certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(certificate_id)]
    by_number = [x for x in records if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "by_id_count": len(by_id),
                      "by_number_count": len(by_number), "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Created Ozon declaration is not uniquely visible; stop without bulk binding")
    info = read_info(client)
    expected_type = str(info.get("type_code") or "").lower()
    if int(info.get("certificate_id", -1)) != certificate_id or expected_type not in {"declaration", "declaration_of_conformity"}:
        state.update({"phase": "created_record_identity_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon live declaration type/ID conflicts; stop without binding")
    if norm(info.get("certificate_number")) != norm(NUMBER):
        raise RuntimeError("Ozon live certificate info returned a different declaration number")
    if str(info.get("issue_date", ""))[:10] != ISSUE_DATE or str(info.get("expire_date", ""))[:10] != EXPIRY_DATE:
        state.update({"phase": "live_date_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon stored dates differ from active FSA record")
    if str(info.get("accordance_type_code") or "").upper() != "EAEU":
        state.update({"phase": "live_accordance_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon stored accordance type differs from EAEU")
    if str(info.get("status_code") or "").lower() in {"declined", "rejected", "cancelled", "invalid"}:
        state.update({"phase": "certificate_rejected", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon rejected the declaration; stop before additional bindings")

    before = read_bindings(client, certificate_id)
    grouped = defaultdict(list)
    for item in before:
        grouped[str(item.get("sku") or "")].append(item)
    outside = sorted(set(grouped) - set(by_sku))
    duplicates = sorted(sku for sku, items in grouped.items() if len(items) != 1)
    identity_mismatches = [sku for sku, items in grouped.items() if sku in by_sku
                           and {str(x.get("product_id")) for x in items} != {by_sku[sku]}]
    if outside or duplicates or identity_mismatches:
        state.update({"phase": "initial_binding_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "identity_mismatches": identity_mismatches,
                      "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Initial Ozon bindings contain an outside SKU or identity conflict")
    if str(seed["sku"]) not in grouped:
        raise RuntimeError("Ozon create seed binding absent; reconcile before continuing")
    missing = sorted(set(by_sku) - set(grouped))
    state.update({"phase": "binding_missing_only", "live_info_before_bind": info,
                  "initial_binding_count": len(before), "missing_before_bind": len(missing), "updated_at": now()})
    save(EXECUTION, state)

    for offset in range(0, len(missing), 500):
        batch = missing[offset:offset + 500]
        entry = {"index": len(state["bind_batches"]) + 1, "sku_count": len(batch),
                 "first_sku": batch[0], "last_sku": batch[-1], "phase": "prepared"}
        state["bind_batches"].append(entry)
        state.update({"phase": "binding_missing_only", "updated_at": now()})
        save(EXECUTION, state)
        try:
            result = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": certificate_id, "skus": batch,
            }, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(EXECUTION, state)
            raise RuntimeError("Ozon bind result uncertain; read live bindings before retry") from None
        entry["response"] = result
        entry["phase"] = "accepted" if result.get("result") is True else "rejected"
        state.update({"updated_at": now()})
        save(EXECUTION, state)
        if entry["phase"] != "accepted":
            state.update({"phase": "bind_rejected", "updated_at": now()})
            save(EXECUTION, state)
            raise RuntimeError("Ozon rejected a binding batch; reconcile before any retry")

    final_info = read_info(client)
    after = read_bindings(client, certificate_id)
    after_by_sku = defaultdict(list)
    for item in after:
        after_by_sku[str(item.get("sku") or "")].append(item)
    missing_after = sorted(set(by_sku) - set(after_by_sku))
    outside_after = sorted(set(after_by_sku) - set(by_sku))
    duplicates_after = sorted(sku for sku, items in after_by_sku.items() if len(items) != 1)
    mismatches_after = [sku for sku, items in after_by_sku.items() if sku in by_sku
                        and {str(x.get("product_id")) for x in items} != {by_sku[sku]}]
    statuses = Counter(str(items[0].get("product_status_code")) for sku, items in after_by_sku.items()
                       if sku in by_sku and len(items) == 1)
    verification = {
        "checked_at": now(), "number": NUMBER, "certificate_id": certificate_id,
        "certificate_info": final_info, "target_offer_count": len(targets),
        "target_sku_count": len(by_sku), "binding_row_count": len(after),
        "covered_target_sku_count": len(set(by_sku) & set(after_by_sku)),
        "missing_skus": missing_after, "outside_target_skus": outside_after,
        "duplicate_skus": duplicates_after, "product_identity_mismatches": mismatches_after,
        "product_status_counts": dict(statuses),
        "all_target_pairs_linked": not (missing_after or outside_after or duplicates_after or mismatches_after),
        "certificate_status": final_info.get("status_code"),
        "certificate_approved": str(final_info.get("status_code") or "").lower() == "approved",
    }
    verification["all_bindings_confirmed"] = verification["all_target_pairs_linked"]
    save(VERIFICATION, verification)
    state.update({"phase": "all_bindings_confirmed" if verification["all_bindings_confirmed"]
                  else "bindings_incomplete", "finished_at": now(),
                  "verification_path": str(VERIFICATION), "final_info": final_info})
    save(EXECUTION, state)
    print(json.dumps({k: verification[k] for k in (
        "number", "certificate_id", "target_offer_count", "target_sku_count", "binding_row_count",
        "covered_target_sku_count", "missing_skus", "outside_target_skus", "duplicate_skus",
        "product_identity_mismatches", "product_status_counts", "certificate_status",
        "certificate_approved", "all_bindings_confirmed")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
