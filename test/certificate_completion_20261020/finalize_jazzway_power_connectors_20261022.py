#!/usr/bin/env python3
"""Record verified Jazzway coverage and remove only the two confirmed source PDFs."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCS = [
    {
        "key": "certificate_04539", "number": "ЕАЭС RU С-HK.СП28.В.04539/26",
        "type": "certificate_of_conformity", "source_file": "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_ac8cb1fa1d.pdf",
        "sha256": "2b727485f9e87b0a78492d4afec02b80d5e2741f98740b8c81f810dfb4d602c9",
    },
    {
        "key": "declaration_00949", "number": "ЕАЭС N RU Д-HK.РА03.В.00949/26",
        "type": "declaration", "source_file": "output_to_user/certificates/group_2/JAZZWAY/documents/certificate_e936b8e8f7.pdf",
        "sha256": "588aa99508418e00fbfb93dbca31ff5dbbe7da40d298a0d5231a946037366c28",
    },
]


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def save(path: pathlib.Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def main() -> None:
    proof_path = HERE / "jazzway_power_connectors_final_crossplatform_readback_20261022.json"
    state_path = HERE / "jazzway_power_connectors_execution_20261022.json"
    addendum_path = HERE / "postwrite_coverage_addendum_20261022.json"
    proof = load(proof_path)
    if (proof.get("read_only") is not True
            or proof.get("ozon", {}).get("all_records_approved") is not True
            or proof.get("ozon", {}).get("all_bindings_exact") is not True
            or proof.get("ozon", {}).get("exact_approved_documents") != 2
            or proof.get("wb", {}).get("cards_with_both_exact_documents") != 36
            or proof.get("wb", {}).get("all_non_document_fields_unchanged") is not True
            or proof.get("wb", {}).get("review_left_pending") is not True):
        raise RuntimeError("cross_platform_exact_readback_not_complete")

    state = load(state_path)
    removed = []
    for document in DOCS:
        source = (ROOT / document["source_file"]).resolve()
        if ROOT.resolve() not in source.parents:
            raise RuntimeError("source_path_outside_repository")
        if source.exists():
            import hashlib
            if hashlib.sha256(source.read_bytes()).hexdigest() != document["sha256"]:
                raise RuntimeError("source_hash_changed_refusing_cleanup:" + document["number"])
            source.unlink()
            removed.append(document)
        elif not any(x.get("source_file") == document["source_file"]
                     and x.get("sha256") == document["sha256"]
                     for x in proof.get("deleted_source_files", [])):
            raise RuntimeError("source_missing_without_prior_cleanup_record:" + document["number"])
    for document in DOCS:
        if (ROOT / document["source_file"]).exists():
            raise RuntimeError("source_cleanup_readback_failed:" + document["number"])

    checked = datetime.now(timezone.utc).isoformat()
    deleted = [{"source_file": x["source_file"], "sha256": x["sha256"], "document_number": x["number"]}
               for x in DOCS]
    proof["local_source_files_deleted"] = True
    proof["deleted_source_files"] = deleted
    proof["cleanup_checked_at_utc"] = checked
    save(proof_path, proof)
    state["local_source_files_deleted"] = True
    state["deleted_source_files"] = deleted
    state["phase"] = "cross_marketplace_readback_complete_sources_cleaned"
    state["cleanup_checked_at_utc"] = checked
    save(state_path, state)

    addendum = load(addendum_path)
    writes = addendum.setdefault("post_snapshot_writes", [])
    recorded = {x.get("document_number") for x in writes}
    final_docs = proof["ozon"]["documents"]
    for document in DOCS:
        if document["number"] in recorded:
            continue
        ozon = final_docs[document["key"]]
        writes.append({
            "brand": "Jazzway", "document_number": document["number"], "type": document["type"],
            "source_sha256": document["sha256"], "ozon_certificate_id": ozon["certificate_id"],
            "ozon_record_status": ozon["record_status"], "ozon_exact_bindings": ozon["visible_exact_bindings"],
            "ozon_binding_status_counts": ozon["binding_status_counts"],
            "wb_exact_cards": 36, "wb_verdict_reason_counts": proof["wb"]["verdict_reason_counts"],
            "wb_review_pending_cards": 36, "wb_review_metadata_manually_changed": False,
            "local_source_pdf_deleted": True,
            "verification_artifacts": ["jazzway_power_connectors_preflight_20261022.json",
                "jazzway_power_connectors_execution_20261022.json",
                "jazzway_power_connectors_final_crossplatform_readback_20261022.json"],
        })
        recorded.add(document["number"])
    addendum.setdefault("local_source_cleanup", {})["jazzway_power_connectors_20261022"] = {
        "deleted_files": deleted, "checked_at_utc": checked,
        "basis": "Ozon record approved with exact 36/36 links per document; WB exact type/date metadata read back on all 36 cards; WB verdicts remain pending.",
    }
    addendum["checked_at_utc"] = checked
    addendum["local_source_pdfs_deleted"] = False
    addendum["complete"] = False
    save(addendum_path, addendum)
    print(json.dumps({"deleted_local_pdfs": deleted, "ozon_exact_bindings_per_document": 36,
        "wb_exact_cards_per_document": 36, "wb_review_left_pending": True,
        "global_coverage_complete": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
