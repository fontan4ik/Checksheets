"""Bind only fresh, exact in-scope Jazzway products to the existing Ozon record."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
from pathlib import Path

from api_client import Client, now

BASE_DIR = Path(__file__).resolve().parent
PREFLIGHT_SOURCE = BASE_DIR / "jazzway_37909_ozon_fresh_preflight_20261014.json"
PREFLIGHT = BASE_DIR / "jazzway_37909_in_scope_ozon_mutation_preflight_20261014.json"
RUN = BASE_DIR / "jazzway_37909_in_scope_ozon_bind_run_20261014.json"
READBACK = BASE_DIR / "jazzway_37909_in_scope_ozon_bind_readback_20261014.json"
CERTIFICATE_ID = 5458891
CERTIFICATE_NUMBER = "ЕАЭС N RU Д-HK.РА08.В.37909/22"
TNVED_CODE = "8539520009"


def attr_values(item: dict, attr_id: str) -> list[str]:
    for attr in item.get("attributes") or []:
        if str(attr.get("id")) == attr_id:
            return [str(v.get("value")) for v in attr.get("values") or []
                    if v.get("value") not in (None, "")]
    return []


def find_record(client: Client) -> dict:
    found = []
    page = 1
    while True:
        data = client.call("ozon", "/v1/product/certificate/list", {"page": page, "page_size": 100})["result"]
        found.extend(c for c in data.get("certificates") or []
                     if str(c.get("certificate_id")) == str(CERTIFICATE_ID))
        if page >= int(data.get("page_count") or 0):
            break
        page += 1
    if len(found) != 1:
        raise RuntimeError(f"Expected one current Ozon record; got {len(found)}")
    record = found[0]
    if (record.get("status_code") != "approved"
            or record.get("certificate_number") != CERTIFICATE_NUMBER
            or record.get("type_code") != "declaration"
            or record.get("accordance_type_code") != "EAEU"
            or str(record.get("expire_date", ""))[:10] < dt.datetime.now(dt.timezone.utc).date().isoformat()):
        raise RuntimeError("The current Ozon record is no longer the same approved, current declaration")
    return record


def get_bindings(client: Client) -> list[dict]:
    return client.ozon_bindings(CERTIFICATE_ID)


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Unique write marker already exists; reconcile current state before any further write")
    source = json.loads(PREFLIGHT_SOURCE.read_text())
    candidates = [x for x in source["fresh_ozon_readback"]["per_target"]
                  if x.get("tnved_codes") == [TNVED_CODE]]
    if len(candidates) != 158:
        raise RuntimeError(f"Source audit no longer yields exactly 158 in-scope targets: {len(candidates)}")
    expected_by_offer = {x["offer_id"]: x for x in candidates}
    if len(expected_by_offer) != 158:
        raise RuntimeError("Source audit contains duplicate offers")

    client = Client()
    record = find_record(client)
    product_ids = [int(x["product_id"]) for x in candidates]
    current_products = client.call("ozon", "/v3/product/info/list", {"product_id": product_ids}).get("items")
    if not isinstance(current_products, list) or len(current_products) != len(candidates):
        raise RuntimeError("Fresh Ozon product detail read is incomplete")
    info_by_id = {str(x.get("product_id") or x.get("id") or ""): x for x in current_products}
    if len(info_by_id) != len(current_products):
        raise RuntimeError("Fresh Ozon product detail read has duplicate/missing IDs")
    offer_ids = [x["offer_id"] for x in candidates]
    attrs_response = client.call("ozon", "/v4/product/info/attributes", {
        "filter": {"offer_id": offer_ids}, "limit": len(offer_ids)})
    attrs = attrs_response.get("result")
    if not isinstance(attrs, list) or len(attrs) != len(candidates):
        raise RuntimeError("Fresh Ozon attribute read is incomplete")
    attrs_by_offer = {str(x.get("offer_id") or ""): x for x in attrs}
    if set(attrs_by_offer) != set(offer_ids):
        raise RuntimeError("Fresh Ozon attributes have missing or unexpected offers")

    proof_rows = []
    for offer, prior in expected_by_offer.items():
        product = info_by_id.get(str(prior["product_id"]))
        attr = attrs_by_offer[offer]
        if not product or str(product.get("offer_id") or "") != offer:
            raise RuntimeError(f"Fresh product identity mismatch for offer {offer}")
        if str(product.get("sku") or "") != str(prior["sku"]):
            raise RuntimeError(f"Fresh SKU mismatch for offer {offer}")
        if product.get("is_archived") is not False:
            raise RuntimeError(f"Offer {offer} is archived or archive status is missing")
        if str(attr.get("id") or attr.get("product_id") or "") != str(prior["product_id"]):
            raise RuntimeError(f"Fresh attribute Product ID mismatch for offer {offer}")
        brands = attr_values(attr, "85")
        tnved = attr_values(attr, "22232")
        codes = sorted({v.split(" - ", 1)[0].strip() for v in tnved})
        if brands != ["Jazzway"] or codes != [TNVED_CODE]:
            raise RuntimeError(f"Fresh brand/TNVED scope mismatch for offer {offer}")
        proof_rows.append({"offer_id": offer, "product_id": str(prior["product_id"]),
                           "sku": str(prior["sku"]), "brand": brands[0], "tnved_code": TNVED_CODE,
                           "is_archived": False})

    bindings_before = get_bindings(client)
    by_product = {str(b.get("product_id")): b for b in bindings_before}
    target_ids = {str(x["product_id"]) for x in proof_rows}
    blocked_statuses = {pid: by_product[pid].get("product_status_code") for pid in target_ids & set(by_product)
                        if by_product[pid].get("product_status_code") != "approved"}
    if blocked_statuses:
        raise RuntimeError(f"Some target product IDs already have non-approved bindings; inspect instead of rebinding: {len(blocked_statuses)}")
    already_approved = target_ids & set(by_product)
    missing = sorted((x for x in proof_rows if x["product_id"] not in already_approved),
                     key=lambda x: x["offer_id"])
    pre = {
        "checked_at": now(), "record": record, "record_id": CERTIFICATE_ID,
        "record_number": CERTIFICATE_NUMBER, "record_status": record.get("status_code"),
        "document_source_audit": PREFLIGHT_SOURCE.name,
        "source_document_sha256": source["official_document"]["local_files"][1]["actual_sha256"],
        "official_pdf_scope_codes": source["official_document"]["declared_tnved_codes"],
        "candidate_count": len(candidates), "fresh_verified_in_scope_count": len(proof_rows),
        "approved_bindings_before": len(bindings_before), "already_approved_target_count": len(already_approved),
        "missing_target_count": len(missing), "targets": proof_rows,
        "bindings_before": bindings_before,
    }
    PREFLIGHT.write_text(json.dumps(pre, ensure_ascii=False, indent=2))
    if not missing:
        print(json.dumps({"state": "no_write_needed", "preflight": PREFLIGHT.name,
                          "already_approved_targets": len(already_approved)}, ensure_ascii=False))
        return
    skus = sorted({int(x["sku"]) for x in missing})
    if len(skus) != len(missing):
        raise RuntimeError("Target SKU list contains duplicates")
    payload = {"certificate_id": CERTIFICATE_ID, "skus": skus}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    run = {"started_at": now(), "state": "prepared", "certificate_id": CERTIFICATE_ID,
           "certificate_number": CERTIFICATE_NUMBER, "target_count": len(missing),
           "target_skus": [str(x) for x in skus], "target_product_ids": sorted(x["product_id"] for x in missing),
           "request_sha256": hashlib.sha256(encoded).hexdigest(), "request_bytes": len(encoded)}
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    run["state"] = "submitting_once"
    run["submitted_at"] = now()
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    try:
        response = client.call("ozon", "/v1/product/certificate/bind", payload, mutation=True)
    except Exception as exc:
        run["state"] = "write_outcome_uncertain_reconcile_only"
        run["error_type"] = type(exc).__name__
        run["finished_at"] = now()
        RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
        raise
    run["response"] = response
    run["state"] = "accepted_readback_pending" if response.get("result") is True else "response_needs_reconcile"
    run["finished_at"] = now()
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))

    bindings_after = get_bindings(client)
    after_by_product = {str(b.get("product_id")): b for b in bindings_after}
    results = []
    for target in missing:
        binding = after_by_product.get(target["product_id"])
        results.append({**target,
                        "binding_found": binding is not None,
                        "binding_status": (binding or {}).get("product_status_code"),
                        "binding_sku": str((binding or {}).get("sku") or "")})
    counts = dict(collections.Counter(x["binding_status"] or "missing" for x in results))
    after_record = find_record(client)
    readback = {
        "checked_at": now(), "record": after_record,
        "record_approved": after_record.get("status_code") == "approved",
        "target_count": len(missing), "binding_status_counts": counts,
        "all_target_bindings_found": all(x["binding_found"] for x in results),
        "all_target_bindings_approved": all(x["binding_status"] == "approved" for x in results),
        "all_target_skus_match": all(x["binding_sku"] == x["sku"] for x in results),
        "results": results,
    }
    READBACK.write_text(json.dumps(readback, ensure_ascii=False, indent=2))
    run["readback"] = {k: v for k, v in readback.items() if k != "results"}
    run["state"] = ("readback_complete" if response.get("result") is True
                    and readback["record_approved"] and readback["all_target_bindings_approved"]
                    and readback["all_target_skus_match"] else "readback_needs_review")
    RUN.write_text(json.dumps(run, ensure_ascii=False, indent=2))
    print(json.dumps({"state": run["state"], "target_count": len(missing),
                      "binding_status_counts": counts, "record_approved": readback["record_approved"],
                      "output": READBACK.name}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
