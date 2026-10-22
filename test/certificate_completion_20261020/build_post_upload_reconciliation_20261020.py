"""Refresh post-upload Ozon readback and write a concise reconciliation report."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
import run_all_found_certificates_20261014 as runner_module  # noqa: E402
from api_client import Client  # noqa: E402

SNAPSHOT = HERE / "live_marketplaces_snapshot_complete_20261020.json"
COVERAGE = HERE / "current_coverage_report.json"
EAEU_MANIFEST = HERE / "iek_missing_new_docs_manifest_20261020.json"
EAEU_STATE = HERE / "iek_missing_new_docs_execute_state_20261020.json"
EAEU_CORRECTION = HERE / "iek_sample_date_binding_correction_20261020.json"
NATIONAL_STATES = {
    "RU С-RU.АЮ64.В.00560/25": HERE / "iek_national_fire_cert_00560_state_20261020.json",
    "RU С-RU.АЮ64.В.00631/26": HERE / "iek_national_fire_cert_state_20261020.json",
}
AUDIT = HERE / "iek_missing_official_docs_audit_20261020.json"
OUT_JSON = HERE / "post_upload_reconciliation_20261020.json"
OUT_MD = HERE / "post_upload_reconciliation_20261020.md"


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text())
    previous_coverage = json.loads(COVERAGE.read_text())
    eaeu_manifest = json.loads(EAEU_MANIFEST.read_text())
    eaeu_state = json.loads(EAEU_STATE.read_text())
    correction = json.loads(EAEU_CORRECTION.read_text())
    client = Client()
    helper = runner_module.Runner(client, {"groups": []}, execute=False,
                                  journal=HERE / "post_upload_verify_only.jsonl",
                                  state=HERE / "post_upload_verify_only_state.json")
    current_certs = helper.list_certificate_metadata()
    cert_by_id = {str(cert.get("certificate_id")): cert for cert in current_certs}
    exec_by_number = {row["number"]: row for row in eaeu_state["groups"]}
    new_groups = []
    total_statuses = Counter()
    current_new_approved_ids: set[str] = set()
    current_new_non_declined_ids: set[str] = set()
    bound_product_ids: set[str] = set()
    document_edge_count = 0

    source_audit = {row["number"]: row for row in json.loads(AUDIT.read_text())["documents"]}
    active_products = snapshot["ozon_products"]["products"]
    products_by_sku = {str(product.get("sku")): product for product in active_products if product.get("sku")}

    def collect(group: dict, certificate_id: str, expected_targets: list[dict], *, was_unbound: set[str] | None = None) -> None:
        cert = cert_by_id.get(str(certificate_id))
        if not cert or runner_module.norm_number(cert.get("certificate_number")) != runner_module.norm_number(group["number"]):
            raise RuntimeError(f"Document missing from current Ozon certificate list: {group['number']}")
        bindings = client.ozon_bindings(certificate_id)
        by_pid = {str(binding.get("product_id")): binding for binding in bindings}
        edge_rows = []
        for target in expected_targets:
            pid = str(target["product_id"])
            row = by_pid.get(pid)
            exact = bool(row and str(row.get("sku")) == str(target["sku"]))
            status = str(row.get("product_status_code") or "unknown") if exact else None
            if exact:
                total_statuses[status] += 1
                bound_product_ids.add(pid)
                if status != "declined":
                    current_new_non_declined_ids.add(pid)
                if cert.get("status_code") == "approved" and status == "approved":
                    current_new_approved_ids.add(pid)
            edge_rows.append({"offer_id": target["offer_id"], "product_id": pid,
                              "sku": str(target["sku"]), "exact_binding_visible": exact,
                              "product_status_code": status,
                              "expected_unbound": bool(was_unbound and pid in was_unbound)})
        new_groups.append({
            "number": group["number"], "certificate_id": str(certificate_id),
            "status_code": cert.get("status_code"), "type_code": cert.get("type_code"),
            "accordance_type_code": cert.get("accordance_type_code"),
            "issue_date": cert.get("issue_date"), "expire_date": cert.get("expire_date"),
            "live_binding_count": len(bindings),
            "verified_expected_links": sum(row["exact_binding_visible"] for row in edge_rows),
            "expected_targets": len(expected_targets), "targets": edge_rows,
        })
        nonlocal document_edge_count
        document_edge_count += sum(row["exact_binding_visible"] for row in edge_rows)

    unbound_pids = {str(row["product_id"]) for row in correction["verification"] if row.get("binding_absent_after")}
    for group in eaeu_manifest["groups"]:
        exec_row = exec_by_number[group["number"]]
        selected_unbound = {str(t["product_id"]) for t in group["targets"] if str(t["product_id"]) in unbound_pids}
        collect(group, str(exec_row["certificate_id"]), group["targets"], was_unbound=selected_unbound)

    for number, state_path in NATIONAL_STATES.items():
        state = json.loads(state_path.read_text())
        preflight_path = (HERE / "iek_national_fire_cert_00560_preflight_20261020.json"
                          if number.endswith("00560/25")
                          else HERE / "iek_national_fire_cert_preflight_20261020.json")
        preflight = json.loads(preflight_path.read_text())
        collect(preflight["manifest"], str(state["certificate_id"]), preflight["manifest"]["targets"])

    missing_unbound = []
    for group in eaeu_manifest["groups"]:
        cert = cert_by_id[next(row["certificate_id"] for row in new_groups if row["number"] == group["number"])]
        actual_ids = {str(binding.get("product_id")) for binding in client.ozon_bindings(cert["certificate_id"])}
        for target in group["targets"]:
            if str(target["product_id"]) in unbound_pids and str(target["product_id"]) in actual_ids:
                missing_unbound.append({"number": group["number"], "offer_id": target["offer_id"],
                                        "product_id": str(target["product_id"]), "binding_absent": False})

    # Match the complete-catalog coverage calculation and then add only live-approved new edges.
    baseline_approved_ids: set[str] = set()
    today = date.today().isoformat()
    for cert in snapshot["ozon_certificates"]["certificates"]:
        if cert.get("status_code") != "approved":
            continue
        if str(cert.get("issue_date") or "")[:10] > today or str(cert.get("expire_date") or "")[:10] < today:
            continue
        for binding in cert.get("live_bindings") or []:
            product = products_by_sku.get(str(binding.get("sku") or ""))
            if (binding.get("product_status_code") == "approved" and product and
                    str(product.get("product_id")) == str(binding.get("product_id"))):
                baseline_approved_ids.add(str(product["product_id"]))
    approved_after = baseline_approved_ids | current_new_approved_ids
    baseline_non_declined = set(baseline_approved_ids)
    for cert in snapshot["ozon_certificates"]["certificates"]:
        if cert.get("status_code") not in ("approved", "awaiting_verification", "pending", "checking", "in_review"):
            continue
        if str(cert.get("issue_date") or "")[:10] > today or str(cert.get("expire_date") or "")[:10] < today:
            continue
        for binding in cert.get("live_bindings") or []:
            product = products_by_sku.get(str(binding.get("sku") or ""))
            if (product and str(product.get("product_id")) == str(binding.get("product_id")) and
                    product.get("is_archived") is False and binding.get("product_status_code") != "declined"):
                baseline_non_declined.add(str(product["product_id"]))
    non_declined_after = baseline_non_declined | current_new_non_declined_ids

    wb_cards = snapshot["wb_catalog"]["cards"]
    wb_by_offer = {}
    for card in wb_cards:
        wb_by_offer.setdefault(str(card.get("vendorCode") or ""), []).append(card)
    target_sources = {}
    for group in eaeu_manifest["groups"]:
        source_group = source_audit[group["number"]]
        for offer in source_group["offers"]:
            target_sources[offer["offer_id"]] = offer
    for number, state_path in NATIONAL_STATES.items():
        source_group = source_audit[number]
        for offer in source_group["offers"]:
            target_sources[offer["offer_id"]] = offer
    exact_wb = sum(len(wb_by_offer.get(offer, [])) == 1 for offer in target_sources)
    article_hits = 0
    for source in target_sources.values():
        article = str(source.get("product_article") or "")
        if article and any(article in str(card.get("vendorCode") or "") or
                           str(card.get("vendorCode") or "") in article for card in wb_cards):
            article_hits += 1

    cert_status_counts = Counter(str(cert.get("status_code") or "unknown") for cert in current_certs)
    current_binding_count = sum(int(cert.get("products_count") or 0) for cert in current_certs)
    catalog = previous_coverage["catalog"]
    source = previous_coverage["source_assignments"]
    current_ozon_products = len(active_products)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_basis": {
            "complete_marketplace_snapshot_checked_at": snapshot.get("updated_at"),
            "ozon_products_checked_at": snapshot["ozon_products"].get("checked_at"),
            "ozon_certificate_baseline_checked_at": snapshot["ozon_certificates"].get("checked_at"),
            "wb_catalog_checked_at": snapshot["wb_catalog"].get("checked_at"),
            "full_catalog_counts_unchanged_by_this_run": True,
        },
        "ozon": {
            "current_certificate_records": len(current_certs),
            "current_certificate_status_counts": dict(cert_status_counts),
            "current_products_count_across_certificate_records": current_binding_count,
            "active_products": current_ozon_products,
            "products_with_current_approved_document_after_updates": len(approved_after),
            "products_without_current_approved_document_after_updates": current_ozon_products - len(approved_after),
            "products_with_at_least_one_current_non_declined_link_after_updates": len(non_declined_after),
            "products_without_any_current_non_declined_link_after_updates": current_ozon_products - len(non_declined_after),
            "new_documents_uploaded_and_visible": len(new_groups),
            "new_document_product_edges_expected_before_corrections": 48,
            "new_document_product_edges_visible_after_corrections": document_edge_count,
            "new_document_edge_status_counts_including_overlapping_docs": dict(total_statuses),
            "distinct_products_with_any_new_live_binding": len(bound_product_ids),
            "sample_date_unbindings_verified": correction.get("verified_absent_count"),
            "sample_date_unbinding_verification_errors": missing_unbound,
            "newly_approved_product_ids_not_in_baseline": len(current_new_approved_ids - baseline_approved_ids),
            "new_docs": new_groups,
        },
        "wildberries": {
            "complete_unique_cards": catalog["wb_unique_cards"],
            "cards_with_at_least_one_valid_document": catalog["wb_cards_with_at_least_one_valid_document"],
            "cards_pending_only": catalog["wb_cards_with_pending_documents_but_no_valid_document"],
            "cards_rejected_only": catalog["wb_cards_with_rejected_documents_but_no_valid_document"],
            "cards_without_any_current_valid_document": catalog["wb_unique_cards"] - catalog["wb_cards_with_at_least_one_valid_document"],
            "cards_with_no_document_records": catalog["wb_unique_cards"] - catalog["wb_cards_with_at_least_one_valid_document"] - catalog["wb_cards_with_pending_documents_but_no_valid_document"] - catalog["wb_cards_with_rejected_documents_but_no_valid_document"],
            "distinct_candidate_offers": len(target_sources),
            "exact_vendor_code_matches_for_candidates": exact_wb,
            "offer_article_substring_matches": article_hits,
            "writes_made": 0,
            "wb_review_left_pending": True,
        },
        "source_coverage": {
            "unique_offers_with_any_source_assignment": source["unique_offers"],
            "offers_with_at_least_one_confirmed_source_row": source["offers_with_at_least_one_confirmed_source_row"],
            "ozon_products_without_any_source_assignment_estimate": current_ozon_products - source["unique_offers"],
            "source_assigned_ozon_offers_without_current_approved_document_estimate":
                (current_ozon_products - len(approved_after)) - (current_ozon_products - source["unique_offers"]),
        },
        "local_source_files_deleted": False,
        "remaining_issues": {
            "declined_new_ozon_product_links": sum(row.get("product_status_code") == "declined"
                for doc in new_groups for row in doc["targets"] if row.get("exact_binding_visible")),
            "national_fire_links_still_in_background_check": total_statuses.get("background_check", 0),
            "product_first_sale_before_sample_date_links_removed": correction.get("verified_absent_count"),
            "wrong_model_light_declaration": "68171/26 lists DVO 6573/6578/6579/6577; crosswalk targets DVO 1611/1612/1613; Ozon declined all 12 product links.",
            "oversized_or_source_metadata_mismatch_docs": [
                "НСОПБ.RU.ЭО.ПР.384.Н.00517: 12,009,349-byte PDF exceeds the conservative Ozon request cap; no official registry URL verified.",
                "РОСС.RU.3070.04ПР00.10АЯ48.026: IEK page start date differs from the PDF date; skipped pending authoritative correction.",
            ],
        },
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    o = report["ozon"]
    w = report["wildberries"]
    md = f"""# Certificate reconciliation — 2026-10-20

Fresh Ozon API readback at {report['checked_at']}. Marketplace catalog counts are from the last complete snapshot at {snapshot.get('updated_at')}.

## Ozon

- {o['active_products']:,} active products.
- {o['products_with_current_approved_document_after_updates']:,} have at least one current approved certificate or declaration; {o['products_without_current_approved_document_after_updates']:,} do not.
- {o['products_with_at_least_one_current_non_declined_link_after_updates']:,} have at least one current link that is not declined; {o['products_without_any_current_non_declined_link_after_updates']:,} have none.
- Added {o['new_documents_uploaded_and_visible']} current document records; their product links show {o['new_document_edge_status_counts_including_overlapping_docs']} statuses across overlapping documents. {o['sample_date_unbindings_verified']} ambiguous links were removed and verified absent.
- Current document record counts: {o['current_certificate_status_counts']}; total product links: {o['current_products_count_across_certificate_records']:,}.

## Wildberries

- {w['complete_unique_cards']:,} unique cards: {w['cards_with_at_least_one_valid_document']:,} have a valid document, {w['cards_pending_only']} are pending only, {w['cards_rejected_only']} rejected only, and {w['cards_without_any_current_valid_document']:,} have no valid document.
- For the {w['distinct_candidate_offers']} distinct new IEK/ITK offers, the complete WB snapshot has {w['exact_vendor_code_matches_for_candidates']} exact vendor-code matches and {w['offer_article_substring_matches']} article-substring matches. No WB write was made; no exact card was available for these offers.

## Uploaded Ozon documents

""" + "\n".join(
        f"- `{doc['number']}` — Ozon ID {doc['certificate_id']}; document status `{doc['status_code']}`; "
        f"{doc['verified_expected_links']}/{doc['expected_targets']} target links visible "
        f"({dict(Counter(row['product_status_code'] for row in doc['targets'] if row['exact_binding_visible']))})."
        for doc in new_groups
    ) + """

The 12 DVO links for declaration 68171/26 were declined because the PDF's DVO model list does not include the 1611/1612/1613 products. One listed PDU target link was also declined; Ozon's binding-list API exposes no per-product rejection reason. The national cable-fire links are visible but remain in `background_check`.

Local certificate PDFs have not been deleted. WB review remains pending wherever a card is found; these new offers had no exact WB card in the complete snapshot.
"""
    OUT_MD.write_text(md)
    print(json.dumps({
        "report_json": str(OUT_JSON), "report_markdown": str(OUT_MD),
        "ozon_records": o["current_certificate_records"], "ozon_record_statuses": o["current_certificate_status_counts"],
        "ozon_binding_count": o["current_products_count_across_certificate_records"],
        "ozon_approved_coverage": o["products_with_current_approved_document_after_updates"],
        "ozon_without_approved_coverage": o["products_without_current_approved_document_after_updates"],
        "new_document_edges": o["new_document_edge_status_counts_including_overlapping_docs"],
        "wb_counts": {key: value for key, value in w.items() if key.endswith("document") or key in ("complete_unique_cards", "cards_with_at_least_one_valid_document", "cards_pending_only", "cards_rejected_only", "cards_without_any_current_valid_document")},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
