#!/usr/bin/env python3
"""Record fresh Navigator NFL coverage and remove verified local PDF copies."""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROOF = HERE / "navigator_nfl_90815_00107_final_live_crossplatform_readback_20261022.json"
STATE = HERE / "navigator_nfl_90815_00107_execution_20261022.json"
RETRY = HERE / "navigator_00107_ozon_certificate_retry_20261022.json"
PREFLIGHT = HERE / "navigator_nfl_90815_00107_fresh_v2_20261022.json"
ADDENDUM = HERE / "postwrite_coverage_addendum_20261022.json"
PDFS = [
    {"path": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14150_fb47c7e7dab0.pdf",
     "sha256": "fb47c7e7dab06d12e4560432589f86a8303cca3431ada97a4c0e00aea0763fc5",
     "number": "ЕАЭС N RU Д-RU.РА11.В.90815/24", "role": "declaration source"},
    {"path": "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf",
     "sha256": "f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e",
     "number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "role": "certificate source"},
    {"path": "test/certificate_completion_20261020/navigator_00107_certificate_ozon_upload_q75_20261022.pdf",
     "sha256": "1ae8fd5c65cc34c4ccdeaaa423f3d49a1a57c159cd803b3ddf07d90fe8acd416",
     "number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "role": "confirmed Ozon upload copy"},
    {"path": "test/certificate_completion_20261020/navigator_00107_certificate_ozon_upload_20261022.pdf",
     "sha256": "a6f39b03242ed26ffea871a3f392e27168124eda8797ca16d3457608ea511e8f",
     "number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "role": "unused upload rendition"},
    {"path": "test/certificate_completion_20261020/navigator_00107_certificate_ozon_compact_20261022.pdf",
     "sha256": "a3253fae01310c89f7e9506d0d813a3c7191396d452895a1efa66b83535ce136",
     "number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "role": "unused compact rendition"},
    {"path": "test/certificate_completion_20261020/navigator_00107_certificate_ozon_compact_q80_20261022.pdf",
     "sha256": "fada65db293f641960b0dbf2615e720ae01b77c53dc0b2f37647277d90bf6a05",
     "number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "role": "unused compact rendition"},
    {"path": "test/certificate_completion_20261020/navigator_00107_certificate_ozon_compact_q90_20261022.pdf",
     "sha256": "24dcf4affcb8c64e0b6af00947de980322d208e6c0e315bd4e22ee0a19a2364c",
     "number": "ЕАЭС RU С-RU.НВ28.В.00107/24", "role": "unused compact rendition"},
]


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def save(path: pathlib.Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def main() -> None:
    proof = load(PROOF)
    if (proof.get("read_only") is not True or proof.get("target_cards") != 11
            or proof.get("ozon_all_records_approved") is not True
            or proof.get("ozon_exact_approved_bindings_per_document") != 11
            or proof.get("wb_cards_with_both_exact_valid_documents") != 11
            or proof.get("wb_all_non_document_fields_unchanged") is not True
            or proof.get("wb_review_state_changed_by_agent") is not False):
        raise RuntimeError("fresh_cross_platform_proof_not_complete")
    addendum = load(ADDENDUM)
    records = {x.get("document_number"): x for x in addendum.get("post_snapshot_writes", [])}
    required_numbers = {"ЕАЭС N RU Д-RU.РА11.В.90815/24", "ЕАЭС RU С-RU.НВ28.В.00107/24"}
    if not required_numbers.issubset(records):
        raise RuntimeError("existing_coverage_entries_missing_before_cleanup")

    receipt = []
    for item in PDFS:
        path = (ROOT / item["path"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise RuntimeError("pdf_path_outside_repository")
        if path.exists():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise RuntimeError("pdf_sha256_mismatch_refusing_cleanup:" + item["path"])
            path.unlink()
        elif not any(x.get("path") == item["path"] and x.get("sha256") == item["sha256"]
                     for x in proof.get("deleted_local_pdfs", [])):
            raise RuntimeError("pdf_missing_without_cleanup_receipt:" + item["path"])
        if path.exists():
            raise RuntimeError("pdf_still_exists_after_cleanup:" + item["path"])
        receipt.append({**item, "path": item["path"], "deleted": True})

    checked = datetime.now(timezone.utc).isoformat()
    proof["local_source_files_deleted"] = True
    proof["deleted_local_pdfs"] = receipt
    proof["cleanup_checked_at_utc"] = checked
    save(PROOF, proof)
    state = load(STATE)
    state.update({"phase": "cross_marketplace_readback_verified_sources_cleaned",
        "local_source_files_deleted": True, "final_live_readback_artifact": PROOF.name,
        "deleted_local_pdfs": receipt, "cleanup_checked_at_utc": checked,
        "wb_delayed_final_verified_valid_cards": 11})
    save(STATE, state)
    retry = load(RETRY)
    retry.update({"local_source_files_deleted": True, "final_live_readback_artifact": PROOF.name,
        "deleted_local_pdfs": receipt, "cleanup_checked_at_utc": checked})
    save(RETRY, retry)
    pre = load(PREFLIGHT)
    pre["local_source_files_deleted"] = True
    pre["final_live_readback_artifact"] = PROOF.name
    save(PREFLIGHT, pre)

    for number in required_numbers:
        row = records.get(number)
        row["local_source_pdf_deleted"] = True
        row.setdefault("verification_artifacts", []).append(PROOF.name)
        row["final_live_readback_artifact"] = PROOF.name
    addendum.setdefault("local_source_cleanup", {})["navigator_nfl_90815_00107_20261022"] = {
        "deleted_files": receipt, "checked_at_utc": checked,
        "basis": "Ozon approved records and 11/11 approved exact bindings per document; WB exact document metadata and valid verdicts on 11/11 cards; other fields preserved.",
    }
    addendum["checked_at_utc"] = checked
    addendum["local_source_pdfs_deleted"] = False
    addendum["complete"] = False
    save(ADDENDUM, addendum)
    print(json.dumps({"deleted_pdfs": receipt, "ozon_approved_bindings_per_document": 11,
        "wb_exact_valid_cards_per_document": 11, "wb_review_state_changed_by_agent": False,
        "global_coverage_complete": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
