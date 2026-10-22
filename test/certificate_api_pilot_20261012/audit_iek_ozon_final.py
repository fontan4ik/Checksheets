"""Read-only live audit of every IEK/Generica assignment in the current Ozon plan."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from api_client import Client, now, save
from execute_iek_ozon_reconciliation import exact_key, iso_date, list_certificates
from group4_ozon import doc_identity

BASE = Path(__file__).resolve().parent
PLAN = BASE / "iek_new_offer_document_plan.json"
OUTPUT = BASE / "iek_ozon_live_final_audit.json"


def main() -> None:
    plan = json.loads(PLAN.read_text())
    assignments = plan["document_assignments"]
    offers = sorted({str(row["offer_id"]) for row in assignments})
    client = Client()

    live_products: dict[str, dict] = {}
    for offset in range(0, len(offers), 100):
        batch = offers[offset : offset + 100]
        result = client.call("ozon", "/v3/product/info/list", {"offer_id": batch})
        for item in result.get("items", []):
            if item.get("offer_id"):
                live_products[str(item["offer_id"])] = item

    certs = list_certificates(client)
    by_identity: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_id = {str(c["certificate_id"]): c for c in certs}
    for cert in certs:
        by_identity[exact_key(cert)].append(cert)

    groups: dict[str, dict] = {}
    rows_by_group: dict[str, list[dict]] = defaultdict(list)
    resolution_errors: list[dict] = []
    for row in assignments:
        outcome = row.get("ozon_outcome")
        proof = row.get("ozon_record_proof") or {}
        if outcome in {"already_approved_and_bound", "bind_existing_approved_record",
                       "blocked_existing_product_pair_not_approved"}:
            cert_id = str(proof.get("certificate_id") or "")
            cert = by_id.get(cert_id)
            if not cert:
                resolution_errors.append({"offer_id": row["offer_id"], "number": row["number"],
                                          "error": "proof_certificate_missing_from_live_list", "certificate_id": cert_id})
                continue
        elif outcome == "new_upload_requires_pdf_validation":
            key = (str(row["ozon_type_code"]), doc_identity(row["number"]))
            candidates = by_identity.get(key, [])
            exact = [c for c in candidates if c.get("certificate_number") == row["number"]]
            if len(exact) == 1:
                cert = exact[0]
            elif len(candidates) == 1:
                cert = candidates[0]
            else:
                resolution_errors.append({"offer_id": row["offer_id"], "number": row["number"],
                                          "error": "new_certificate_not_unique_in_live_list",
                                          "candidate_ids": [str(c.get("certificate_id")) for c in candidates]})
                continue
            cert_id = str(cert["certificate_id"])
        else:
            resolution_errors.append({"offer_id": row["offer_id"], "number": row["number"],
                                      "error": "unexpected_plan_outcome", "outcome": outcome})
            continue

        if cert_id not in groups:
            groups[cert_id] = {"certificate_id": cert_id, "certificate": cert,
                               "type_code": row["ozon_type_code"], "number": row["number"],
                               "issue_date": iso_date(row.get("issue_date")),
                               "expire_date": iso_date(row.get("expire_date")),
                               "source_outcomes": set(), "expected_pairs": {}}
        group = groups[cert_id]
        group["source_outcomes"].add(outcome)
        pair = (str(row["sku"]), str(row["product_id"]))
        group["expected_pairs"][pair] = str(row["offer_id"])
        rows_by_group[cert_id].append(row)

    cert_results = []
    total_expected_pairs = 0
    total_exact_pairs = 0
    total_approved_pairs = 0
    for cert_id, group in groups.items():
        cert = group["certificate"]
        metadata_matches = (
            cert.get("type_code") == group["type_code"]
            and doc_identity(cert.get("certificate_number", "")) == doc_identity(group["number"])
            and iso_date(cert.get("issue_date")) == group["issue_date"]
            and iso_date(cert.get("expire_date")) == group["expire_date"]
            and cert.get("accordance_type_code") == "EAEU"
        )
        current_bindings = client.ozon_bindings(int(cert_id))
        live_pairs = {(str(item.get("sku")), str(item.get("product_id"))): item for item in current_bindings}
        expected = group["expected_pairs"]
        missing = [pair for pair in expected if pair not in live_pairs]
        statuses = defaultdict(int)
        for pair in expected:
            item = live_pairs.get(pair)
            if item is not None:
                statuses[str(item.get("product_status_code") or "unknown")] += 1
        total_expected_pairs += len(expected)
        total_exact_pairs += len(expected) - len(missing)
        total_approved_pairs += statuses.get("approved", 0)

        product_identity_errors = []
        for pair, offer in expected.items():
            item = live_products.get(offer)
            if not item or str(item.get("id") or item.get("product_id") or "") != pair[1] or str(item.get("sku")) != pair[0]:
                product_identity_errors.append({"offer_id": offer, "expected_sku": pair[0], "expected_product_id": pair[1],
                                                "live_product_id": str((item or {}).get("id") or (item or {}).get("product_id") or ""),
                                                "live_sku": str((item or {}).get("sku") or "")})

        blocked_pairs = []
        for row in rows_by_group[cert_id]:
            if row.get("ozon_outcome") == "blocked_existing_product_pair_not_approved":
                blocked_pairs.append({"offer_id": row["offer_id"], "sku": str(row["sku"]),
                                      "product_id": str(row["product_id"]),
                                      "live_status": (live_pairs.get((str(row["sku"]), str(row["product_id"]))) or {}).get("product_status_code")})

        cert_results.append({
            "certificate_id": cert_id,
            "number": cert.get("certificate_number"),
            "type_code": cert.get("type_code"),
            "status_code": cert.get("status_code"),
            "issue_date": iso_date(cert.get("issue_date")),
            "expected_issue_date": group["issue_date"],
            "expire_date": iso_date(cert.get("expire_date")),
            "expected_expire_date": group["expire_date"],
            "metadata_matches_source": metadata_matches,
            "expected_pairs": len(expected),
            "exact_live_pairs": len(expected) - len(missing),
            "missing_pairs": [{"sku": pair[0], "product_id": pair[1], "offer_id": expected[pair]} for pair in missing],
            "binding_status_counts": dict(statuses),
            "product_identity_errors": product_identity_errors,
            "blocked_source_pairs": blocked_pairs,
            "source_outcomes": sorted(group["source_outcomes"]),
        })

    output = {
        "checked_at": now(),
        "plan_file": PLAN.name,
        "plan_official_feed_sha256": plan.get("official_iek_feed_sha256"),
        "assignment_count": len(assignments),
        "unique_target_offers": len(offers),
        "fresh_product_info_offers": len(live_products),
        "live_certificate_count": len(certs),
        "planned_certificate_groups": len(groups),
        "expected_product_document_pairs": total_expected_pairs,
        "exact_live_pairs": total_exact_pairs,
        "approved_live_pairs": total_approved_pairs,
        "certificate_metadata_conflicts": sum(not x["metadata_matches_source"] for x in cert_results),
        "certificate_not_approved": sum(x["status_code"] != "approved" for x in cert_results),
        "missing_live_pairs": sum(len(x["missing_pairs"]) for x in cert_results),
        "nonapproved_live_pairs": sum(sum(v for k, v in x["binding_status_counts"].items() if k != "approved") for x in cert_results),
        "product_identity_errors": sum(len(x["product_identity_errors"]) for x in cert_results),
        "plan_resolution_errors": resolution_errors,
        "certificates": sorted(cert_results, key=lambda x: x["number"]),
        "complete": not resolution_errors and len(live_products) == len(offers),
    }
    tmp = OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    tmp.replace(OUTPUT)
    print(json.dumps({k: v for k, v in output.items() if k not in {"certificates", "plan_resolution_errors"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
