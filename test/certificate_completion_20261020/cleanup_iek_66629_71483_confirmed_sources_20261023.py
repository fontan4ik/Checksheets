#!/usr/bin/env python3
"""Delete only source PDFs for the two live-confirmed IEK cross-market groups."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from reconcile_approved_ozon_docs_to_wb import norm_number  # noqa: E402

AUDIT = HERE / "iek_66629_71483_live_link_audit_20261023.json"
ALL_LINKS = HERE / "iek_66629_71483_all_live_record_bindings_20261023.json"
MANIFEST = HERE / "expanded_found_certificates_manifest_20261020.json"
LOCAL_MAP = ROOT / "test/certificate_cleanup_20261006/local_map.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
RESULT = HERE / "iek_66629_71483_confirmed_source_files_deleted_20261023.json"
JOURNAL = HERE / "confirmed_local_source_deletion_journal_20261023.jsonl"


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if RESULT.exists():
        raise RuntimeError("cleanup_result_already_exists_inspect_before_retry")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    detail = {norm_number(x["number"]): x for x in audit.get("results", [])}
    full = json.loads(ALL_LINKS.read_text(encoding="utf-8"))
    full_by_key = {norm_number(x["number"]): x for x in full.get("results", [])}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_by_key = {norm_number(g["number"]): g for g in manifest.get("groups", [])}
    required = {
        "ЕАЭС N RU Д-CN.РА02.В.66629/26": {
            "sha": "050b412e88b8a8ecaa5915bd46140eeac30667ed3a71f128025174a401bf0997",
            "targets": 7, "record_id": 5447922, "all_bindings": 10,
        },
        "ЕАЭС N RU Д-CN.РА02.В.71483/26": {
            "sha": "5319fae6219880ee8264225d4db1ce9c38e27c0b8d60b31e63bdec4e5cada349",
            "targets": 5, "record_id": 5448191, "all_bindings": 7,
        },
    }
    local = json.loads(LOCAL_MAP.read_text(encoding="utf-8"))
    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as f:
        assignment_rows = list(csv.DictReader(f))
    to_delete = []
    proofs = []
    allowed_root = (ROOT / "output_to_user/certificates").resolve()

    for number, spec in required.items():
        key = norm_number(number)
        target = detail.get(key)
        all_binding = full_by_key.get(key)
        source_group = manifest_by_key.get(key)
        if not target or not all_binding or not source_group:
            raise RuntimeError("live_proof_missing:" + number)
        if (target.get("record_matches") != 1 or target.get("record_id") != spec["record_id"]
                or target.get("record_status") != "approved"
                or target.get("ozon_target_identity_exact") != spec["targets"]
                or target.get("ozon_scope_exact") != spec["targets"]
                or target.get("ozon_binding_exact") != spec["targets"]
                or target.get("ozon_binding_status_counts") != {"approved": spec["targets"]}
                or target.get("wb_exact_metadata") != spec["targets"]
                or target.get("wb_verdict_counts") != {"valid": spec["targets"]}):
            raise RuntimeError("target_links_not_fully_confirmed:" + number)
        if (all_binding.get("record_status") != "approved"
                or all_binding.get("binding_count") != spec["all_bindings"]
                or all_binding.get("binding_status_counts") != {"approved": spec["all_bindings"]}
                or all_binding.get("active_bindings") != spec["all_bindings"]
                or all_binding.get("brand_iek_count") != spec["all_bindings"]
                or all_binding.get("scope_tnved_count") != spec["all_bindings"]
                or all_binding.get("wb_exact_count") != spec["all_bindings"]
                or all_binding.get("wb_verdict_counts") != {"valid": spec["all_bindings"]}):
            raise RuntimeError("all_existing_record_bindings_not_confirmed:" + number)

        groups = [g for g in local.get("groups", []) if g.get("sha256") == spec["sha"]]
        if len(groups) != 1:
            raise RuntimeError("local_source_hash_group_missing_or_duplicated:" + number)
        manifest_file = source_group.get("upload_file") or {}
        if (len(source_group.get("targets") or []) != spec["targets"]
                or manifest_file.get("sha256") != spec["sha"]):
            raise RuntimeError("verified_source_manifest_scope_mismatch:" + number)
        file_rows = [f for f in (groups[0].get("files") or []) if f.get("sha256") == spec["sha"]]
        paths = sorted({pathlib.Path(f["path"]).resolve() for f in file_rows if f.get("path")})
        if len(paths) != 1:
            raise RuntimeError("expected_one_source_file_copy:" + number)
        assignment_count = sum(r.get("SHA256 фактический") == spec["sha"] for r in assignment_rows)
        if assignment_count < 1:
            raise RuntimeError("assignment_rows_missing_for_source_hash:" + number)
        for path in paths:
            if path.suffix.casefold() != ".pdf" or not path.is_relative_to(allowed_root):
                raise RuntimeError("source_path_outside_certificate_library")
            if not path.is_file() or digest(path) != spec["sha"]:
                raise RuntimeError("source_missing_or_hash_changed:" + number)
            to_delete.append({"document_number": number, "path": str(path),
                              "sha256": spec["sha"], "bytes": path.stat().st_size})
        proofs.append({"document_number": number, "ozon_approved_target_links": spec["targets"],
                       "ozon_all_record_bindings_approved": spec["all_bindings"],
                       "wb_exact_target_docs_valid": spec["targets"],
                       "wb_all_record_binding_docs_valid": spec["all_bindings"],
                       "assignment_rows_for_source_hash": assignment_count})

    for row in to_delete:
        path = pathlib.Path(row["path"])
        if not path.is_file() or digest(path) != row["sha256"]:
            raise RuntimeError("source_changed_immediately_before_unlink")
    for row in to_delete:
        pathlib.Path(row["path"]).unlink()
    remaining = [x["path"] for x in to_delete if pathlib.Path(x["path"]).exists()]
    if remaining:
        raise RuntimeError("source_files_remain_after_unlink")

    result = {"deleted_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "crossplatform_live_verification_at_utc": full.get("checked_at_utc"),
              "documents": proofs, "removed_files": to_delete,
              "freed_bytes": sum(x["bytes"] for x in to_delete),
              "remaining_matching_source_paths": remaining,
              "wb_review_left_pending": True}
    tmp = RESULT.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(RESULT)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
        f.flush()
    print(json.dumps({k: v for k, v in result.items() if k != "removed_files"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
