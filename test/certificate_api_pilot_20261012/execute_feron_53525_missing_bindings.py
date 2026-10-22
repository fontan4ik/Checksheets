"""Attach only the three audited archived Feron 53525/22 offers to the existing Ozon record."""
from __future__ import annotations
import collections
import datetime as dt
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from api_client import Client, now  # noqa: E402

CERT_ID = 5423327
TARGETS = {
    "48348-1": {"product_id": "520295014", "sku": "986319910"},
    "11671-1": {"product_id": "520295030", "sku": "986319943"},
    "48347-1": {"product_id": "520295015", "sku": "986320248"},
}
PREFLIGHT_PATH = BASE / "feron_53525_bind_preflight_20261012.json"
EXECUTION_PATH = BASE / "feron_53525_bind_execution_20261012.json"


def save(data: dict) -> None:
    temp = EXECUTION_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(EXECUTION_PATH)


def list_certificates(client: Client) -> list[dict]:
    out: list[dict] = []
    page = 1
    seen: set[str] = set()
    while page <= 100:
        result = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        batch = result.get("certificates")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid certificate list response")
        ids = [str(x.get("certificate_id")) for x in batch]
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise RuntimeError("Duplicate certificate IDs during pagination")
        seen.update(ids)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    raise RuntimeError("Certificate list pagination limit exceeded")


def read_bindings(client: Client) -> list[dict]:
    out: list[dict] = []
    last_id = 0
    expected_count = None
    seen_cursors: set[int] = set()
    while True:
        result = client.call("ozon", "/v1/product/certificate/products/list", {
            "certificate_id": CERT_ID, "limit": 500, "last_id": last_id,
        })["result"]
        batch, count = result.get("items"), result.get("count")
        if not isinstance(batch, list) or not isinstance(count, int):
            raise RuntimeError("Invalid binding-list response")
        if expected_count is None:
            expected_count = count
        elif count != expected_count:
            raise RuntimeError("Binding count changed during pagination")
        out.extend(batch)
        if len(out) == expected_count:
            if len({str(x.get("sku")) for x in out}) != len(out):
                raise RuntimeError("Duplicate SKU in binding list")
            return out
        if not batch:
            raise RuntimeError("Binding pagination stopped before expected count")
        next_id = int(batch[-1].get("product_id") or 0)
        if next_id <= last_id or next_id in seen_cursors:
            raise RuntimeError("Binding cursor failed to advance")
        seen_cursors.add(next_id)
        last_id = next_id


def main() -> None:
    if EXECUTION_PATH.exists():
        raise RuntimeError("Execution journal already exists; read it and reconcile instead of repeating a write")
    audit = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    if audit.get("certificate_id") != CERT_ID or audit.get("exact_three_still_missing") is not True:
        raise RuntimeError("Expected preflight evidence is missing or changed")
    client = Client()

    # Refresh every identity and the approved record immediately before the write.
    info_body = client.call("ozon", "/v3/product/info/list", {"offer_id": list(TARGETS)})
    product_items = info_body.get("items") or info_body.get("result", {}).get("items")
    if not isinstance(product_items, list) or len(product_items) != len(TARGETS):
        raise RuntimeError("Fresh product identity readback is incomplete")
    by_offer = {str(x.get("offer_id")): x for x in product_items}
    if set(by_offer) != set(TARGETS):
        raise RuntimeError("Fresh product readback returned different offer IDs")
    product_readback = []
    for offer, expected in TARGETS.items():
        item = by_offer[offer]
        if str(item.get("product_id") or item.get("id")) != expected["product_id"] or str(item.get("sku")) != expected["sku"]:
            raise RuntimeError(f"Product identity changed for {offer}")
        if item.get("is_archived") is not True:
            raise RuntimeError(f"Offer {offer} is no longer archived; inspect live state before binding")
        product_readback.append({"offer_id": offer, "product_id": expected["product_id"], "sku": expected["sku"], "is_archived": True})

    records = list_certificates(client)
    matching_id = [x for x in records if str(x.get("certificate_id")) == str(CERT_ID)]
    if len(matching_id) != 1:
        raise RuntimeError("Certificate ID 5423327 is not uniquely visible")
    record = matching_id[0]
    stored_number = str(record.get("certificate_number") or "")
    if "53525/22" not in stored_number or record.get("status_code") != "approved":
        raise RuntimeError("Existing declaration number/status changed")
    details = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result")
    if not isinstance(details, dict) or str(details.get("certificate_id")) != str(CERT_ID) or details.get("status_code") != "approved":
        raise RuntimeError("Fresh certificate detail is not approved")
    if str(details.get("type_code")) != "declaration":
        raise RuntimeError("Existing record is not a declaration")
    expire = str(details.get("expire_date", ""))[:10]
    if expire != "2027-09-14":
        raise RuntimeError(f"Certificate effective end date changed: {expire!r}")

    before = read_bindings(client)
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in before:
        by_sku[str(item.get("sku"))].append(item)
    missing = []
    for offer, expected in TARGETS.items():
        entries = by_sku.get(expected["sku"], [])
        if not entries:
            missing.append({"offer_id": offer, **expected})
        elif len(entries) != 1 or str(entries[0].get("product_id")) != expected["product_id"]:
            raise RuntimeError(f"Existing binding is duplicated or has wrong product_id for {offer}")
    if missing != [{"offer_id": offer, **TARGETS[offer]} for offer in TARGETS]:
        raise RuntimeError(f"Missing SKU set is not exactly the audited three: {missing}")
    if len(before) != 251 or any(str(x.get("product_status_code")) != "approved" for x in before):
        raise RuntimeError("Existing 251 bindings changed; stop and reconcile before writing")

    state = {
        "prepared_at": now(),
        "phase": "prepared",
        "certificate_id": CERT_ID,
        "ozon_number": stored_number,
        "certificate_status": details.get("status_code"),
        "expire_date": expire,
        "preflight_target_products": product_readback,
        "preflight_binding_count": len(before),
        "preflight_binding_status_counts": dict(collections.Counter(str(x.get("product_status_code")) for x in before)),
        "exact_missing_skus": missing,
        "request": {"endpoint": "/v1/product/certificate/bind", "body": {"certificate_id": CERT_ID, "skus": [x["sku"] for x in missing]}},
        "mutation_attempts": 0,
    }
    save(state)

    state.update({"phase": "mutation_started", "mutation_attempts": 1, "mutation_started_at": now()})
    save(state)
    try:
        response = client.call("ozon", "/v1/product/certificate/bind", {
            "certificate_id": CERT_ID, "skus": [x["sku"] for x in missing],
        }, mutation=True)
    except Exception as exc:
        state.update({"phase": "mutation_uncertain", "error_type": type(exc).__name__, "updated_at": now()})
        save(state)
        raise RuntimeError("Bind outcome is uncertain; reconcile live state and do not repeat this call") from None
    state.update({"mutation_response": response, "phase": "accepted" if response.get("result") is True else "rejected", "updated_at": now()})
    save(state)
    if response.get("result") is not True:
        raise RuntimeError("Ozon did not accept the binding request; do not retry before reconciliation")

    final_record = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result")
    final_bindings = read_bindings(client)
    final_by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in final_bindings:
        final_by_sku[str(item.get("sku"))].append(item)
    remaining = []
    identity_errors = []
    for offer, expected in TARGETS.items():
        entries = final_by_sku.get(expected["sku"], [])
        if not entries:
            remaining.append({"offer_id": offer, **expected})
        elif len(entries) != 1 or str(entries[0].get("product_id")) != expected["product_id"]:
            identity_errors.append({"offer_id": offer, "entries": entries})
    state.update({
        "phase": "readback_complete",
        "finished_at": now(),
        "final_record_status": final_record.get("status_code") if isinstance(final_record, dict) else None,
        "final_binding_count": len(final_bindings),
        "final_binding_status_counts": dict(collections.Counter(str(x.get("product_status_code")) for x in final_bindings)),
        "target_skus_visible": 254 - len(remaining),
        "target_skus_missing_after": remaining,
        "target_identity_errors_after": identity_errors,
        "target_three_bound": not remaining and not identity_errors,
    })
    state["phase"] = "verified_linked" if state["target_three_bound"] and state["final_record_status"] == "approved" else "linked_review_pending"
    save(state)
    print(json.dumps({k: state[k] for k in (
        "phase", "certificate_id", "final_record_status", "preflight_binding_count", "final_binding_count",
        "final_binding_status_counts", "target_skus_visible", "target_skus_missing_after", "target_identity_errors_after"
    )}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
