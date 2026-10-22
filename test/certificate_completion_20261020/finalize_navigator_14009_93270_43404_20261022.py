#!/usr/bin/env python3
"""Record fresh Navigator coverage and remove only the two confirmed source PDFs."""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROOF = HERE / "navigator_14009_93270_43404_final_live_crossplatform_readback_20261022.json"
STATE = HERE / "navigator_14009_93270_43404_execution_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
DOCS = [
    {"number": "ЕАЭС N RU Д-CN.РА08.В.93270/25", "type": "declaration", "id": 5945811,
     "sha256": "86835da14f5932204a619819c7c9b35ec3cdea377c332b3362682be433c3d55b",
     "file": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14009_86835da14f59.pdf"},
    {"number": "ЕАЭС RU С-CN.АЯ46.В.43404/25", "type": "certificate_of_conformity", "id": 5945813,
     "sha256": "af44bd7c8eb370286d5722206f3a95a3c1734209f582c6d97d1fcc5b8daf7974",
     "file": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14009_af44bd7c8eb3.pdf"},
]


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def save(path: pathlib.Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def main() -> None:
    proof = load(PROOF)
    if (proof.get("read_only") is not True or proof.get("target_cards") != 74
            or proof.get("ozon_all_records_approved") is not True
            or proof.get("ozon_exact_bindings_per_document") != 74
            or len(proof.get("ozon_documents") or {}) != 2
            or proof.get("wb_cards_with_both_exact_documents") != 74
            or proof.get("wb_all_non_document_fields_unchanged") is not True
            or proof.get("wb_review_state_changed_by_agent") is not False):
        raise RuntimeError("fresh_cross_platform_proof_not_complete")

    deleted = []
    for doc in DOCS:
        path = (ROOT / doc["file"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise RuntimeError("source_path_outside_repository")
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
                raise RuntimeError("source_sha256_mismatch_refusing_cleanup:" + doc["number"])
            path.unlink()
        elif not any(x.get("source_file") == doc["file"] and x.get("sha256") == doc["sha256"]
                     for x in proof.get("deleted_source_files", [])):
            raise RuntimeError("source_missing_without_cleanup_receipt:" + doc["number"])
        if path.exists():
            raise RuntimeError("source_file_still_exists_after_cleanup:" + doc["number"])
        deleted.append({"source_file": doc["file"], "sha256": doc["sha256"],
                        "document_number": doc["number"]})

    checked = datetime.now(timezone.utc).isoformat()
    proof["local_source_files_deleted"] = True
    proof["deleted_source_files"] = deleted
    proof["cleanup_checked_at_utc"] = checked
    save(PROOF, proof)
    state = load(STATE)
    state.update({"phase": "cross_marketplace_readback_complete_sources_cleaned",
        "local_source_files_deleted": True, "deleted_source_files": deleted,
        "final_readback_artifact": PROOF.name, "cleanup_checked_at_utc": checked})
    save(STATE, state)

    addendum = load(ADDENDUM)
    writes = addendum.setdefault("post_snapshot_writes", [])
    recorded = {x.get("document_number") for x in writes}
    for doc in DOCS:
        if doc["number"] in recorded:
            continue
        ozon = proof["ozon_documents"][doc["number"]]
        writes.append({
            "brand": "Navigator", "document_number": doc["number"], "type": doc["type"],
            "source_sha256": doc["sha256"], "ozon_certificate_id": doc["id"],
            "ozon_record_status": "approved", "ozon_exact_bindings": 74,
            "ozon_binding_status_counts": ozon["binding_status_counts"],
            "wb_exact_cards": 74, "wb_review_metadata_manually_changed": False,
            "wb_review_state_changed_by_agent": False, "local_source_pdf_deleted": True,
            "verification_artifacts": ["navigator_14009_93270_43404_preflight_20261022.json",
                "navigator_14009_93270_43404_final_live_crossplatform_readback_20261022.json"],
        })
        recorded.add(doc["number"])
    addendum.setdefault("local_source_cleanup", {})["navigator_14009_93270_43404_20261022"] = {
        "deleted_files": deleted, "checked_at_utc": checked,
        "basis": "Ozon records approved and 74/74 bindings approved per document; exact metadata present on 74/74 WB cards with non-document fields preserved.",
    }
    addendum["checked_at_utc"] = checked
    addendum["local_source_pdfs_deleted"] = False
    addendum["complete"] = False
    save(ADDENDUM, addendum)
    print(json.dumps({"deleted_local_pdfs": deleted,
        "ozon_approved_bindings_per_document": 74,
        "wb_exact_cards_per_document": 74,
        "wb_review_state_manually_changed": False,
        "global_coverage_complete": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
