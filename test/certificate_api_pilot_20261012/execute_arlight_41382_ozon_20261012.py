"""Create 41382/26 once on Ozon, bind only FSA-TNVED-scoped targets, and read back."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
from api_client import Client, digest, now  # noqa: E402
from build_bulk_cleanup_candidates_20261012 import norm  # noqa: E402

PREFLIGHT = BASE / "arlight_41382_ozon_preflight_scoped_v2_20261012.json"
WB_BEFORE = BASE / "arlight_41382_wb_fullcards_before_20261012.json"
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/arlight/F1AD317FA132F2448DFFCC8233E3D0C0.pdf"
EXECUTION = BASE / "arlight_41382_ozon_execution_20261012.json"
VERIFICATION = BASE / "arlight_41382_ozon_verification_20261012.json"
NUMBER = "ЕАЭС N RU Д-RU.РА08.В.41382/26"
ISSUE_DATE = "2026-09-16"
EXPIRY_DATE = "2031-09-15"
SOURCE_SHA256 = "f21eee1e430f86bbef6f7570767243bf27dfe3fe7b7648e58ff7a1b87b04e193"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/21895502/product"
FSA_TNVED = {"9405110039", "9405110013", "9405110033", "9405420039"}


def save(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def read_certificates(client: Client) -> list[dict]:
    rows, page, last_count = [], 1, 0
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {
            "page": page, "page_size": 100,
        }).get("result", {})
        batch, count = result.get("certificates"), result.get("page_count")
        if not isinstance(batch, list) or not isinstance(count, int) or count < last_count or page > count:
            raise RuntimeError("Ozon certificate pagination invalid or moved backwards")
        last_count = count
        rows.extend(batch)
        if page >= count or len(batch) < 100:
            break
        page += 1
    if len({str(x.get("certificate_id")) for x in rows}) != len(rows):
        raise RuntimeError("Ozon certificate list contains duplicate certificate IDs")
    return rows


def read_info(client: Client) -> dict:
    return client.call("ozon", "/v1/product/certificate/info", {
        "certificate_number": NUMBER,
    }).get("result", {})


def main() -> None:
    if EXECUTION.exists() or VERIFICATION.exists():
        raise RuntimeError("41382 Ozon create/bind was already attempted; reconcile before another write")
    plan = json.loads(PREFLIGHT.read_text())
    wb = json.loads(WB_BEFORE.read_text())
    targets = [x for x in plan.get("targets", []) if x.get("tnved_in_scope")]
    if (not plan.get("ready_for_wb_full_read_and_ozon_create_or_bind") or len(targets) != 339
            or plan.get("tnved_scope_exclusion_count") != 29 or not wb.get("complete")
            or wb.get("target_count") != 339 or wb.get("targets_found") != 339
            or wb.get("duplicate_nmids") != 0):
        raise RuntimeError("Fresh exact source, TN VED scope, or WB full-card readback is incomplete")
    if not SOURCE.is_file() or digest(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("Official manufacturer source PDF is missing or changed")
    by_sku = {str(x["sku"]): str(x["product_id"]) for x in targets}
    if (len(by_sku) != 339 or len({str(x["product_id"]) for x in targets}) != 339
            or any(str(x["tnved_values"][0]).split(" - ", 1)[0].strip() not in FSA_TNVED
                   for x in targets)):
        raise RuntimeError("Ozon eligible target set is not one-to-one or contains an out-of-scope TN VED")

    client = Client()
    offers = sorted(str(x["offer_id"]) for x in targets)
    product_rows = {}
    for offset in range(0, len(offers), 100):
        batch = offers[offset:offset + 100]
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": batch}).get("items") or []
        for row in rows:
            offer = str(row.get("offer_id") or "")
            if offer not in batch or offer in product_rows:
                raise RuntimeError("Ozon fresh product info contains unknown or duplicate offers")
            product_rows[offer] = row
    if set(product_rows) != set(offers):
        raise RuntimeError("Fresh Ozon product info is incomplete")
    for target in targets:
        offer = str(target["offer_id"])
        row = product_rows[offer]
        if (str(row.get("id") or row.get("product_id")) != str(target["product_id"])
                or str(row.get("sku")) != str(target["sku"]) or row.get("is_archived")):
            raise RuntimeError(f"Fresh Ozon product identity/archive state mismatch: {offer}")
        attr_rows = client.call("ozon", "/v4/product/info/attributes", {
            "filter": {"offer_id": [offer]}, "limit": 1,
        }).get("result") or []
        if len(attr_rows) != 1 or attr_rows[0].get("offer_id") != offer:
            raise RuntimeError(f"Fresh Ozon attributes missing for {offer}")
        attrs = {str(x.get("id")): x for x in attr_rows[0].get("attributes") or []}
        brand = [str(v.get("value")) for v in (attrs.get("85") or {}).get("values") or []]
        tnved = [str(v.get("value")) for v in (attrs.get("22232") or {}).get("values") or []]
        codes = {x.split(" - ", 1)[0].strip() for x in tnved}
        if brand != ["Arlight"] or not codes or not codes.issubset(FSA_TNVED):
            raise RuntimeError(f"Fresh Ozon brand/TN VED changed scope for {offer}")

    records = read_certificates(client)
    existing = [x for x in records if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if existing:
        raise RuntimeError("Ozon now has a matching 41382/26 record; reconcile it instead of creating another")
    absence = client.http.post(
        "https://api-seller.ozon.ru/v1/product/certificate/info",
        data=json.dumps({"certificate_number": NUMBER}, ensure_ascii=False).encode(),
        headers=client.ozon_headers, timeout=(15, 60))
    try:
        absence_body = absence.json()
    except ValueError:
        absence_body = {}
    if absence.status_code != 404 or absence_body.get("code") != 5:
        raise RuntimeError("Ozon exact-number query does not confirm absence; no create sent")

    seed = next(x for x in targets if str(x["offer_id"]) == offers[0])
    params = {"name": "Декларация о соответствии № " + NUMBER,
              "certificate_type": "DECLARATION", "certificate_country": "RU",
              "accordance_type": "EAEU", "number": NUMBER,
              "issue_date": ISSUE_DATE + "T00:00:00Z",
              "expired_date": {"date": {"day": 15, "month": 9, "year": 2031}},
              "skus": [str(seed["sku"])], "product_type": "UNKNOWN",
              "link_to_registry": FSA_URL,
              "files": [{"file_content": base64.b64encode(SOURCE.read_bytes()).decode("ascii"),
                         "name": SOURCE.name}]}
    request = {"params": params}
    request_bytes = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
    if len(request_bytes) > 15_000_000:
        raise RuntimeError("Ozon document upload request exceeds tested size limit")
    state = {"started_at": now(), "phase": "create_prepared", "number": NUMBER,
             "document_type": "DECLARATION", "accordance": "EAEU", "target_offer_count": 339,
             "target_sku_count": 339, "excluded_by_fsa_tnved": plan["tnved_scope_exclusions"],
             "issue_date": ISSUE_DATE, "expiry_date": EXPIRY_DATE,
             "source_file_sha256": digest(SOURCE), "source_file_bytes": SOURCE.stat().st_size,
             "fsa_record_id": 21895502, "fsa_registry_url": FSA_URL,
             "precreate_certificate_count": len(records),
             "exact_absence_lookup": {"http_status": absence.status_code, "code": absence_body.get("code")},
             "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
             "request_bytes": len(request_bytes), "seed_offer_id": seed["offer_id"],
             "seed_product_id": seed["product_id"], "seed_sku": seed["sku"], "binding_batches": []}
    save(EXECUTION, state)
    state.update({"phase": "create_sent", "sent_at": now()})
    save(EXECUTION, state)
    try:
        created = client.call("ozon", "/v2/product/certificate/create", request, mutation=True)
    except Exception as exc:
        state.update({"phase": "create_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon create outcome uncertain; reconcile live state before any retry") from None
    state["create_response"] = created
    certificate_id = created.get("certificate_id")
    param_states = [x.get("state") for x in created.get("params", []) if isinstance(x, dict)]
    if not certificate_id or created.get("status") != "COMPLETED" or not param_states or set(param_states) != {"VALID"}:
        state.update({"phase": "create_not_fully_validated", "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon create response is incomplete or invalid; stop and inspect")
    certificate_id = int(certificate_id)
    state.update({"certificate_id": certificate_id, "phase": "created_response_valid", "updated_at": now()})
    save(EXECUTION, state)

    records = read_certificates(client)
    by_id = [x for x in records if str(x.get("certificate_id")) == str(certificate_id)]
    by_number = [x for x in records if norm(x.get("certificate_number") or x.get("number")) == norm(NUMBER)]
    if len(by_id) != 1 or len(by_number) != 1 or str(by_id[0].get("certificate_id")) != str(by_number[0].get("certificate_id")):
        state.update({"phase": "created_not_uniquely_visible", "updated_at": now(),
                      "by_id_count": len(by_id), "by_number_count": len(by_number)})
        save(EXECUTION, state)
        raise RuntimeError("Created Ozon declaration is not uniquely visible; do not bind")
    info = read_info(client)
    if (int(info.get("certificate_id", -1)) != certificate_id or norm(info.get("certificate_number")) != norm(NUMBER)
            or str(info.get("type_code", "")).lower() not in {"declaration", "declaration_of_conformity"}
            or str(info.get("accordance_type_code", "")).upper() != "EAEU"
            or str(info.get("issue_date", ""))[:10] != ISSUE_DATE
            or str(info.get("expire_date", ""))[:10] != EXPIRY_DATE
            or str(info.get("status_code", "")).lower() in {"declined", "rejected", "cancelled", "invalid"}):
        state.update({"phase": "created_live_record_conflict", "live_info": info, "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon live declaration identity/status/dates conflict; stop before further binding")

    before = client.ozon_bindings(certificate_id)
    expected = {str(x["sku"]): str(x["product_id"]) for x in targets}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in before:
        grouped[str(item.get("sku") or "")].append(item)
    outside = sorted(set(grouped) - set(expected))
    duplicates = sorted(sku for sku, items in grouped.items() if len(items) != 1)
    mismatches = sorted(sku for sku, items in grouped.items() if sku in expected
                        and {str(x.get("product_id")) for x in items} != {expected[sku]})
    if outside or duplicates or mismatches or seed["sku"] not in grouped:
        state.update({"phase": "initial_binding_conflict", "outside_skus": outside,
                      "duplicate_skus": duplicates, "identity_mismatches": mismatches,
                      "initial_binding_count": len(before), "updated_at": now()})
        save(EXECUTION, state)
        raise RuntimeError("Ozon seed or other initial binding is outside/mismatched; stop before bind")
    missing = sorted(set(expected) - set(grouped))
    state.update({"phase": "binding_missing_only", "initial_binding_count": len(before),
                  "missing_skus": len(missing), "updated_at": now()})
    save(EXECUTION, state)
    for offset in range(0, len(missing), 500):
        batch = missing[offset:offset + 500]
        entry = {"index": len(state["binding_batches"]) + 1, "sku_count": len(batch), "phase": "prepared"}
        state["binding_batches"].append(entry)
        save(EXECUTION, state)
        try:
            result = client.call("ozon", "/v1/product/certificate/bind", {
                "certificate_id": certificate_id, "skus": batch,
            }, mutation=True)
        except Exception as exc:
            entry.update({"phase": "uncertain", "error_type": type(exc).__name__})
            state.update({"phase": "bind_uncertain", "updated_at": now()})
            save(EXECUTION, state)
            raise RuntimeError("Ozon bind outcome uncertain; read live state before any retry") from None
        entry["response"] = result
        entry["phase"] = "accepted" if result.get("result") is True else "rejected"
        state.update({"updated_at": now()})
        save(EXECUTION, state)
        if entry["phase"] != "accepted":
            state.update({"phase": "bind_rejected", "updated_at": now()})
            save(EXECUTION, state)
            raise RuntimeError("Ozon rejected a binding batch; reconcile before retry")

    final_info = read_info(client)
    after = client.ozon_bindings(certificate_id)
    after_by_sku: dict[str, list[dict]] = defaultdict(list)
    for item in after:
        after_by_sku[str(item.get("sku") or "")].append(item)
    missing_after = sorted(set(expected) - set(after_by_sku))
    outside_after = sorted(set(after_by_sku) - set(expected))
    duplicate_after = sorted(sku for sku, items in after_by_sku.items() if len(items) != 1)
    identity_after = sorted(sku for sku, items in after_by_sku.items() if sku in expected
                            and {str(x.get("product_id")) for x in items} != {expected[sku]})
    product_statuses = Counter(str(items[0].get("product_status_code")) for sku, items in after_by_sku.items()
                                if sku in expected and len(items) == 1)
    verification = {"checked_at": now(), "number": NUMBER, "certificate_id": certificate_id,
                    "certificate_info": final_info, "target_offer_count": 339, "target_sku_count": 339,
                    "binding_row_count": len(after), "covered_target_sku_count": len(set(expected) & set(after_by_sku)),
                    "missing_skus": missing_after, "outside_target_skus": outside_after,
                    "duplicate_skus": duplicate_after, "product_identity_mismatches": identity_after,
                    "product_status_counts": dict(product_statuses),
                    "tnved_scope_exclusion_count": 29,
                    "tnved_scope_exclusions": plan["tnved_scope_exclusions"],
                    "certificate_status": final_info.get("status_code"),
                    "certificate_approved": final_info.get("status_code") == "approved",
                    "all_target_pairs_linked": not (missing_after or outside_after or duplicate_after or identity_after),
                    "local_cleanup_allowed": False}
    verification["all_bindings_confirmed"] = verification["all_target_pairs_linked"]
    save(VERIFICATION, verification)
    state.update({"phase": "all_bindings_confirmed" if verification["all_bindings_confirmed"] else "bindings_incomplete",
                  "finished_at": now(), "verification_path": str(VERIFICATION), "final_info": final_info})
    save(EXECUTION, state)
    print(json.dumps({k: verification[k] for k in (
        "number", "certificate_id", "target_offer_count", "binding_row_count", "covered_target_sku_count",
        "missing_skus", "outside_target_skus", "duplicate_skus", "product_identity_mismatches",
        "product_status_counts", "certificate_status", "certificate_approved",
        "all_bindings_confirmed", "tnved_scope_exclusion_count", "local_cleanup_allowed")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
