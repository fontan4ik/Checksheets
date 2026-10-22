#!/usr/bin/env python3
"""Finalize exact cross-marketplace proof and clean the one proven source PDF."""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCOPE = HERE / "navigator_94200_halogens_scope_proof_20261022.json"
PREFLIGHT = HERE / "navigator_94200_halogens_scope_preflight_20261022.json"
DELAYED = HERE / "navigator_94200_halogens_scope_delayed_readback_20261022.json"
STATE = HERE / "navigator_94200_halogens_scope_execution_20261022.json"
FINAL = HERE / "navigator_94200_final_crossplatform_readback_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
SOURCE_REL = "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_94200_d8d8454cac3f.pdf"
SOURCE_SHA256 = "d8d8454cac3fddbd3251262303f3ee1e82118e31c23525e1ddc3b57f82eeaef4"
NUMBER = "ЕАЭС N RU Д-CN.РА11.В.61378/25"
OZON_ID = 5950933


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: pathlib.Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    if FINAL.exists():
        raise RuntimeError("final_crossplatform_proof_exists_inspect_first")
    scope = load(SCOPE)
    pre = load(PREFLIGHT)
    delayed = load(DELAYED)
    state = load(STATE)
    if (scope.get("read_only") is not True or scope.get("target_count") != 45
            or scope.get("all_targets_exactly_map_to_model_in_declaration") is not True
            or scope.get("declaration_pdf_sha256") != SOURCE_SHA256):
        raise RuntimeError("exact_declaration_model_scope_not_proven")
    if (pre.get("read_only") is not True or pre.get("target_count") != 45
            or pre.get("ozon_eligible_targets") != 45 or pre.get("wb_eligible_targets") != 45):
        raise RuntimeError("live_preflight_not_complete")
    if (delayed.get("read_only") is not True or delayed.get("document_number") != NUMBER
            or delayed.get("ozon_certificate_id") != OZON_ID
            or delayed.get("ozon_record_status") != "approved"
            or delayed.get("ozon_expected_bindings") != 45
            or delayed.get("ozon_visible_bindings") != 45
            or delayed.get("ozon_all_expected_pairs_visible") is not True
            or delayed.get("ozon_product_binding_status_counts") != {"approved": 45}
            or delayed.get("wb_target_cards") != 45
            or delayed.get("wb_cards_with_exact_declaration") != 45
            or delayed.get("wb_document_verdict_counts") != {"valid": 45}
            or delayed.get("failures")
            or any(x.get("prior_documents_preserved") is not True
                   or x.get("unrelated_card_fields_preserved") is not True for x in delayed.get("cards", []))):
        raise RuntimeError("delayed_crossplatform_readback_not_complete")
    if state.get("wb_left_for_marketplace_review") is not True:
        raise RuntimeError("wb_marketplace_review_state_not_preserved")

    source = (ROOT / SOURCE_REL).resolve()
    if ROOT.resolve() not in source.parents:
        raise RuntimeError("source_path_outside_repository")
    if source.exists():
        actual_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_sha256 != SOURCE_SHA256:
            raise RuntimeError("source_sha256_mismatch_refusing_cleanup")
    else:
        raise RuntimeError("source_pdf_missing_without_prior_cleanup_receipt")

    checked = datetime.now(timezone.utc).isoformat()
    final = {
        "checked_at_utc": checked,
        "document_number": NUMBER,
        "document_type": "declaration",
        "registry_url": scope["registry_url"],
        "valid_dates": scope["declaration_valid_dates"],
        "declaration_tnved": scope["declaration_tnved"],
        "declaration_pdf_sha256": SOURCE_SHA256,
        "source_file": SOURCE_REL,
        "scope_evidence": {
            "explicit_model_list_in_declaration": True,
            "distinct_models_exactly_matched": scope["distinct_exact_manufacturer_model_codes"],
            "target_cards_in_scope": scope["target_count"],
            "all_targets_exactly_match_a_declared_model": True,
            "marketplace_tnved_discrepancy_retained_as_separate_issue": True,
            "ozon_tnved": pre["ozon_tnved_distribution"],
            "wb_tnved": pre["wb_tnved_distribution"],
            "target_models": scope["targets"],
        },
        "ozon": {
            "certificate_id": OZON_ID,
            "record_status": delayed["ozon_record_status"],
            "expected_exact_bindings": delayed["ozon_expected_bindings"],
            "visible_exact_bindings": delayed["ozon_visible_bindings"],
            "binding_status_counts": delayed["ozon_product_binding_status_counts"],
            "all_expected_pairs_visible": delayed["ozon_all_expected_pairs_visible"],
        },
        "wb": {
            "expected_cards": delayed["wb_target_cards"],
            "cards_with_exact_declaration": delayed["wb_cards_with_exact_declaration"],
            "valid_document_verdicts": delayed["wb_document_verdict_counts"],
            "previous_documents_preserved": True,
            "unrelated_card_fields_preserved": True,
            "review_state_changed_by_agent": False,
            "left_for_marketplace_review": True,
        },
        "source_cleanup": {"status": "ready_after_exact_readback", "file": SOURCE_REL,
                           "sha256": SOURCE_SHA256},
        "evidence_artifacts": [SCOPE.name, PREFLIGHT.name, DELAYED.name],
    }
    save(FINAL, final)

    source.unlink()
    if source.exists():
        raise RuntimeError("source_file_still_exists_after_cleanup")
    deleted = {"source_file": SOURCE_REL, "sha256": SOURCE_SHA256,
               "document_number": NUMBER, "deleted_after_verified_readback_at_utc": checked}
    final["source_cleanup"] = {"status": "deleted_after_exact_crossplatform_readback", **deleted}
    final["local_source_files_deleted"] = True
    save(FINAL, final)

    state.update({"phase": "cross_marketplace_readback_verified_sources_cleaned",
                  "local_source_files_deleted": True, "deleted_source_files": [deleted],
                  "final_readback_artifact": FINAL.name, "cleanup_checked_at_utc": checked,
                  "wb_left_for_marketplace_review": True})
    save(STATE, state)

    addendum = load(ADDENDUM)
    writes = addendum.setdefault("post_snapshot_writes", [])
    if not any(x.get("document_number") == NUMBER for x in writes):
        writes.append({
            "brand": "Navigator", "document_number": NUMBER, "type": "declaration",
            "source_sha256": SOURCE_SHA256, "ozon_certificate_id": OZON_ID,
            "ozon_record_status": "approved", "ozon_exact_bindings": 45,
            "ozon_binding_status_counts": {"approved": 45},
            "wb_exact_cards": 45, "wb_valid_cards": 45,
            "wb_review_metadata_manually_changed": False,
            "wb_review_state_changed_by_agent": False,
            "wb_left_for_marketplace_review": True, "local_source_pdf_deleted": True,
            "verification_artifacts": [SCOPE.name, PREFLIGHT.name, DELAYED.name, FINAL.name],
        })
    addendum.setdefault("local_source_cleanup", {})["navigator_94200_scope_20261022"] = {
        "deleted_files": [deleted], "checked_at_utc": checked,
        "basis": "Ozon record approved with 45/45 exact bindings approved; WB 45/45 exact declarations had valid verdicts and all unrelated card fields were preserved.",
    }
    addendum["checked_at_utc"] = checked
    addendum["local_source_pdfs_deleted"] = False
    addendum["complete"] = False
    save(ADDENDUM, addendum)
    print(json.dumps({"document_number": NUMBER, "ozon_approved_bindings": 45,
                      "wb_exact_valid_cards": 45, "local_source_pdf_deleted": True,
                      "final_readback": FINAL.name, "global_coverage_complete": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
