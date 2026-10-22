"""Read-only post-create verification for Ozon bindings of FERON EL documents."""
from __future__ import annotations

import collections
import argparse
import json
from pathlib import Path

from api_client import Client, digest, now
from audit_feron_01315_53551 import norm
from execute_feron_05934_53534_ozon import BASE, list_certificates, read_bindings


def verify(suffix: str) -> None:
    compact = suffix.replace("/", "")
    plan = json.loads((BASE / f"feron_{compact}_ozon_plan.json").read_text(encoding="utf-8"))
    execution_path = BASE / f"feron_{compact}_ozon_execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    if not execution.get("certificate_id"):
        raise RuntimeError("No confirmed Ozon certificate id; stop and inspect execution state")
    client = Client()
    records = list_certificates(client)
    matches = [x for x in records if str(x.get("certificate_id")) == str(execution["certificate_id"])]
    if len(matches) != 1:
        raise RuntimeError("Created Ozon record is not uniquely visible")
    record = matches[0]
    stored_number = str(record.get("certificate_number", ""))
    if norm(stored_number) != norm(plan["number"]):
        raise RuntimeError("Stored Ozon number differs from plan")
    info = client.call("ozon", "/v1/product/certificate/info", {"certificate_number": stored_number}).get("result")
    if not isinstance(info, dict) or str(info.get("certificate_id")) != str(execution["certificate_id"]):
        raise RuntimeError("Ozon certificate info does not match the created record")
    if info.get("type_code") != plan["ozon_type_code"]:
        raise RuntimeError("Ozon certificate type differs from plan")

    targets = {str(x["sku"]): str(x["product_id"]) for x in plan["targets"]}
    bindings = read_bindings(client, int(execution["certificate_id"]))
    by_sku: dict[str, list[dict]] = collections.defaultdict(list)
    for item in bindings:
        by_sku[str(item.get("sku", ""))].append(item)
    missing = sorted(set(targets) - set(by_sku))
    outside = sorted(set(by_sku) - set(targets))
    duplicates = sorted(sku for sku, group in by_sku.items() if len(group) != 1)
    mismatches = sorted(sku for sku, group in by_sku.items()
                        if sku in targets and str(group[0].get("product_id")) != targets[sku])
    statuses = collections.Counter(str(x.get("product_status_code")) for x in bindings)

    offers = [str(x["offer_id"]) for x in plan["targets"]]
    product_items = client.call("ozon", "/v3/product/info/list", {"offer_id": offers}).get("items")
    if not isinstance(product_items, list):
        raise RuntimeError("Invalid fresh Ozon product identity readback")
    live = {str(x.get("offer_id")): {"product_id": str(x.get("id", "")), "sku": str(x.get("sku", "")),
                                      "is_archived": bool(x.get("is_archived"))} for x in product_items}
    identity_mismatches = []
    for target in plan["targets"]:
        actual = live.get(str(target["offer_id"]))
        expected = {"product_id": str(target["product_id"]), "sku": str(target["sku"]), "is_archived": False}
        if actual != expected:
            identity_mismatches.append({"offer_id": target["offer_id"], "expected": expected, "live": actual})

    for item in [plan["source_file"], plan["upload_file"], *plan["local_offer_copies"]]:
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError("A planned source, upload, or local copy changed: " + str(path))

    verified = {
        "verified_at": now(), "number": plan["number"], "certificate_id": int(execution["certificate_id"]),
        "stored_number": stored_number, "type_code": info.get("type_code"),
        "record_status": record.get("status_code"), "info_status": info.get("status_code"),
        "issue_date": str(info.get("issue_date", ""))[:10], "expire_date": str(info.get("expire_date", ""))[:10],
        "target_count": len(targets), "live_binding_count": len(bindings),
        "missing_skus": missing, "outside_skus": outside, "duplicate_skus": duplicates,
        "product_id_mismatches": mismatches, "binding_statuses": dict(statuses),
        "all_target_skus_linked": not missing and not outside and not duplicates and not mismatches and len(bindings) == len(targets),
        "all_bindings_approved": len(bindings) == len(targets) and statuses == {"approved": len(targets)},
        "live_product_identity_count": len(live), "live_product_identity_mismatches": identity_mismatches,
        "all_product_identities_match": len(live) == len(targets) and not identity_mismatches,
        "source_sha256": plan["source_file"]["sha256"], "upload_sha256": plan["upload_file"]["sha256"],
        "local_copy_count": len(plan["local_offer_copies"]), "local_copies_hash_verified": True,
        "wb_cards_found": plan["wb_preflight"]["cards_found"],
        "wb_cards_missing": plan["wb_preflight"]["cards_missing"],
        "wb_finally_accepted": plan["wb_preflight"]["cards_with_final_exact_document"],
        "local_cleanup_allowed": False,
        "local_cleanup_reason": "Three target WB cards are absent; Ozon status is checked independently, so local copies remain until the two-platform condition is true for every target.",
        "bindings": [{"product_id": str(x.get("product_id")), "sku": str(x.get("sku")),
                      "status": x.get("product_status_code")} for x in bindings],
        "field_mapping_note": "Ozon certificate/products/list returns product_status_code; an earlier preliminary summary queried a nonexistent status field. This fresh read corrects that field mapping.",
    }
    out = BASE / f"feron_{compact}_ozon_verification.json"
    out.write_text(json.dumps(verified, ensure_ascii=False, indent=2), encoding="utf-8")
    execution.update({"phase": "verified_approved" if verified["all_bindings_approved"] and info.get("status_code") == "approved" else "verified_review_pending",
                      "reconciled_at": now(), "verification_path": str(out),
                      "binding_statuses": dict(statuses)})
    execution_path.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"number": suffix, "certificate_id": verified["certificate_id"],
                      "record_status": verified["record_status"], "binding_count": verified["live_binding_count"],
                      "binding_statuses": verified["binding_statuses"],
                      "all_bindings_approved": verified["all_bindings_approved"],
                      "all_target_skus_linked": verified["all_target_skus_linked"],
                      "local_cleanup_allowed": False}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("number_suffix", choices=("05934/22", "53534/22"), nargs="?", default="05934/22")
    verify(parser.parse_args().number_suffix)
