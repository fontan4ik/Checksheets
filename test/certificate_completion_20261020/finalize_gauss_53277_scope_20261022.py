#!/usr/bin/env python3
"""Record Gauss partial cross-platform success without cleaning its source PDF."""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCOPE = HERE / "gauss_53277_scope_proof_20261022.json"
PREFLIGHT = HERE / "gauss_53277_scope_preflight_20261022.json"
DELAYED = HERE / "gauss_53277_scope_delayed_readback_20261022.json"
STATE = HERE / "gauss_53277_scope_execution_20261022.json"
FINAL = HERE / "gauss_53277_final_crossplatform_readback_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
NUMBER = "ЕАЭС N RU Д-CN.PA01.В.53277/22"
SOURCE_SHA256 = "3f1197e48a91cae3c774c20547ae4bd2f93bac1ae4443d66d4de14f662990fbf"
OZON_ID = 5951098


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: pathlib.Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if FINAL.exists():
        raise RuntimeError("final_readback_exists_inspect_first")
    scope, pre, readback, state = map(load, (SCOPE, PREFLIGHT, DELAYED, STATE))
    if (scope.get("read_only") is not True or scope.get("declaration_pdf_sha256") != SOURCE_SHA256
            or scope.get("all_90_article_codes_present_in_declaration") is not True):
        raise RuntimeError("declaration_scope_proof_invalid")
    if (pre.get("read_only") is not True or pre.get("target_count") != 90
            or pre.get("ozon_eligible_targets") != 90 or pre.get("wb_eligible_targets") != 90):
        raise RuntimeError("fresh_live_preflight_invalid")
    if (readback.get("read_only") is not True or readback.get("document_number") != NUMBER
            or readback.get("ozon_certificate_id") != OZON_ID
            or readback.get("ozon_record_status") != "approved"
            or readback.get("ozon_expected_bindings") != 90
            or readback.get("ozon_visible_bindings") != 90
            or readback.get("ozon_all_expected_pairs_visible") is not True
            or readback.get("ozon_binding_status_counts") != {"approved": 86, "declined": 4}
            or readback.get("wb_target_cards") != 90
            or readback.get("wb_cards_with_exact_declaration") != 90
            or readback.get("wb_document_verdict_counts") != {"valid": 90}
            or readback.get("wb_previous_documents_preserved") is not True
            or readback.get("wb_unrelated_card_fields_preserved") is not True
            or readback.get("failures")):
        raise RuntimeError("delayed_crossplatform_evidence_invalid")

    source = pathlib.Path(pre["source_pdf"]).resolve()
    if ROOT.resolve() not in source.parents or not source.is_file():
        raise RuntimeError("source_pdf_missing_or_outside_workspace")
    actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual_hash != SOURCE_SHA256:
        raise RuntimeError("source_pdf_hash_changed")
    checked = datetime.now(timezone.utc).isoformat()
    final = {
        "checked_at_utc": checked, "document_number": NUMBER, "document_type": "declaration",
        "registry_url": scope["registry_url"], "issue_date": scope["issue_date"],
        "expire_date": scope["expire_date"], "declaration_tnved": scope["declaration_tnved"],
        "source_pdf_sha256": SOURCE_SHA256, "source_file": str(source.relative_to(ROOT.resolve())),
        "scope_evidence": {k: scope[k] for k in (
            "product_scope", "distinct_articles", "ozon_live_targets", "wb_live_targets",
            "all_90_article_codes_present_in_declaration", "manual_visual_check_for_ocr_confusable_codes")},
        "ozon": {"certificate_id": OZON_ID, "record_status": "approved",
                 "expected_bindings": 90, "visible_bindings": 90,
                 "binding_status_counts": readback["ozon_binding_status_counts"],
                 "approved_bindings": 86, "declined_bindings": 4,
                 "declined_offers": readback["ozon_declined_offers"],
                 "outside_bindings": 0, "duplicate_bindings": 0},
        "wb": {"target_cards": 90, "exact_document_cards": 90,
               "valid_verdicts": 90, "previous_documents_preserved": True,
               "unrelated_card_fields_preserved": True,
               "review_state_changed_by_agent": False, "left_for_marketplace_review": True},
        "local_source_file_deleted": False,
        "local_source_cleanup_held_reason": "Four Ozon product bindings are declined; keep the original PDF until those targets are resolved.",
        "evidence_artifacts": [SCOPE.name, PREFLIGHT.name, DELAYED.name],
    }
    save(FINAL, final)
    state.update({"phase": "cross_marketplace_readback_complete_with_ozon_declined_bindings",
                  "finished_at_utc": checked, "final_readback_artifact": FINAL.name,
                  "ozon_documents": {"declaration": final["ozon"]},
                  "wb_readback": final["wb"], "local_source_files_deleted": False,
                  "wb_left_for_marketplace_review": True,
                  "ozon_certificate_info_endpoint_error": "404 on supplementary lookup; exact record and bindings were confirmed via certificate list and products/list."})
    save(STATE, state)

    addendum = load(ADDENDUM)
    writes = addendum.setdefault("post_snapshot_writes", [])
    entry = {
        "brand": "Gauss", "document_number": NUMBER, "type": "declaration",
        "source_sha256": SOURCE_SHA256, "ozon_certificate_id": OZON_ID,
        "ozon_record_status": "approved", "ozon_exact_bindings": 90,
        "ozon_binding_status_counts": {"approved": 86, "declined": 4},
        "ozon_declined_offers": [x["offer_id"] for x in readback["ozon_declined_offers"]],
        "wb_exact_cards": 90, "wb_valid_cards": 90,
        "wb_review_metadata_manually_changed": False, "wb_review_state_changed_by_agent": False,
        "wb_left_for_marketplace_review": True, "local_source_pdf_deleted": False,
        "limitation": "Four Ozon product bindings were declined; source PDF retained for follow-up.",
        "verification_artifacts": [SCOPE.name, PREFLIGHT.name, DELAYED.name, FINAL.name],
    }
    existing = next((x for x in writes if x.get("document_number") == NUMBER), None)
    if existing is None:
        writes.append(entry)
    else:
        existing.update(entry)
    deferred = addendum.setdefault("deferred_groups", [])
    deferred_entry = next((x for x in deferred if x.get("document_number") == NUMBER), None)
    if deferred_entry is None:
        deferred_entry = {"brand": "Gauss", "document_number": NUMBER}
        deferred.append(deferred_entry)
    deferred_entry.update({
        "source_file": str(source.relative_to(ROOT.resolve())), "source_sha256": SOURCE_SHA256,
        "source_assignment_rows": 90, "decision": "partial_write_four_ozon_bindings_declined",
        "reason": "The scanned declaration lists all 90 target article codes and TN VED 8539519009; WB is valid on 90/90 cards; Ozon has 86 approved and 4 declined bindings.",
        "unresolved_ozon_offers": [x["offer_id"] for x in readback["ozon_declined_offers"]],
        "preflight_artifact": PREFLIGHT.name, "final_readback_artifact": FINAL.name,
        "source_pdf_retained": True,
    })
    addendum["checked_at_utc"] = checked
    addendum["local_source_pdfs_deleted"] = False
    addendum["complete"] = False
    save(ADDENDUM, addendum)
    print(json.dumps({"document_number": NUMBER, "ozon_approved": 86, "ozon_declined": 4,
                      "wb_valid": 90, "source_pdf_deleted": False,
                      "unresolved_offers": entry["ozon_declined_offers"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
