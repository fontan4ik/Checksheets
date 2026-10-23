#!/usr/bin/env python3
"""Move the exact Gauss source PDF to recoverable Trash after both-platform proof."""
from __future__ import annotations
import csv, hashlib, json, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE_REL = "output_to_user/certificates/group_1/documents/gauss/22073e3d9c4580581bbf9d92.pdf"
SHA = "81173faa80fa3b88c9ddf83ccc980fbb2448bce7e370df17424991f19e3ab9d7"
NUMBER = "ЕАЭС N RU Д-CN.РА08.В.48971/24"
OZON_PROOF = HERE / "gauss_48971_execution_20261023.json"
WB_PROOF = HERE / "gauss_48971_wb_final_verification_20261023.json"
PREFLIGHT = HERE / "gauss_48971_crossplatform_preflight_20261023.json"
JOURNAL = HERE / "gauss_48971_cleanup_journal_20261023.jsonl"
RESULT = HERE / "gauss_48971_cleanup_result_20261023.json"
TRASH_DIR = Path.home() / ".Trash" / "Подтверждены_Ozon_WB_Gauss_48971_20261023"


def main():
    if JOURNAL.exists() or RESULT.exists():
        raise RuntimeError("cleanup_artifact_exists_inspect_before_retry")
    source = ROOT / SOURCE_REL
    if not source.is_file():
        raise RuntimeError("source_missing")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    ozon = json.loads(OZON_PROOF.read_text(encoding="utf-8"))
    wb = json.loads(WB_PROOF.read_text(encoding="utf-8"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != SHA:
        raise RuntimeError("source_hash_mismatch")
    targets = {x["offer_id"] for x in pre["targets"]}
    if len(targets) != 26 or pre.get("summary", {}).get("eligible_both_platforms") != 26:
        raise RuntimeError("target_count_or_eligibility_conflict")
    rows = [x for x in ozon.get("ozon_result", {}).get("bindings", [])]
    if (ozon.get("ozon_result", {}).get("record", {}).get("certificate_number") != NUMBER
            or ozon.get("ozon_result", {}).get("record", {}).get("status_code") != "approved"
            or {x.get("offer_id") for x in rows} != targets
            or any(x.get("exact_binding_count") != 1 or x.get("binding_status") != "approved" for x in rows)):
        raise RuntimeError("ozon_exact_approved_binding_proof_incomplete")
    if (wb.get("document_number") != NUMBER or wb.get("cards_expected") != 26
            or wb.get("exact_metadata_visible") != 26
            or wb.get("wb_verdict_reasons") != {"valid": 26}
            or wb.get("cards_with_prior_characteristics_preserved") != 26
            or wb.get("cards_with_added_declaration_characteristics") != 26
            or wb.get("cards_with_other_fields_unchanged") != 26
            or wb.get("cards_with_prior_documents_preserved") != 26
            or {x.get("offer_id") for x in wb.get("rows", [])} != targets):
        raise RuntimeError("wb_exact_valid_metadata_or_preservation_proof_incomplete")
    with (ROOT / "output_to_user/certificates/document_assignments.csv").open(
            encoding="utf-8-sig", newline="") as stream:
        assignments = list(csv.DictReader(stream))
    matching = [r for r in assignments if r.get("SHA256 фактический") == SHA]
    if (len(matching) != 26 or {r.get("Артикул продавца") for r in matching} != targets
            or {r.get("Локальный файл") for r in matching} != {SOURCE_REL}):
        raise RuntimeError("source_assignment_coverage_conflict")
    dest = TRASH_DIR / source.name
    if dest.exists():
        raise RuntimeError("trash_destination_already_exists")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"source": str(source), "trash_path": str(dest), "document_number": NUMBER,
             "source_sha256": SHA, "source_size_bytes": source.stat().st_size,
             "confirmed_ozon_bindings": 26, "confirmed_wb_cards": 26,
             "wb_verdict": "valid", "ozon_document_status": "approved",
             "phase": "prepared"}
    JOURNAL.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.move(str(source), str(dest))
    if source.exists() or not dest.is_file():
        raise RuntimeError("move_postcondition_failed")
    moved_sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    if moved_sha != SHA or dest.stat().st_size != entry["source_size_bytes"]:
        raise RuntimeError("trash_copy_hash_or_size_mismatch")
    entry["phase"] = "verified_moved"
    entry["trash_sha256"] = moved_sha
    JOURNAL.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    RESULT.write_text(json.dumps({"completed": True, "recoverable_trash": True, **entry},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in entry.items() if k != "source"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
