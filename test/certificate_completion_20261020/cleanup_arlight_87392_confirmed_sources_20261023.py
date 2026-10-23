#!/usr/bin/env python3
"""Delete only exact 87392/22 PDF copies after live dual-marketplace proof."""
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

SHA = "cb52ca8a72f07018e22ecf6861cfcf48aad25963c11ab6937efb97a921d99267"
NUMBER_KEY = norm_number("ЕАЭС N RU Д-CN.PA08.B.87392/22")
READBACK = HERE / "arlight_87392_live_all_links_verification_20261023.json"
LOCAL_MAP = ROOT / "test/certificate_cleanup_20261006/local_map.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
RESULT = HERE / "arlight_87392_confirmed_files_deleted_20261023.json"
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
    proof = json.loads(READBACK.read_text(encoding="utf-8"))
    if (proof.get("read_only") is not True
            or norm_number(proof.get("number")) != NUMBER_KEY
            or proof.get("certificate_id") != 5944403
            or proof.get("ozon_record_status") != "approved"
            or proof.get("ozon_total_record_bindings") != 156
            or proof.get("ozon_exact_visible") != 156
            or proof.get("ozon_binding_status_counts") != {"approved": 156}
            or proof.get("wb_exact_metadata") != 156
            or proof.get("wb_verdict_counts") != {"valid": 156}
            or proof.get("cleanup_safe") is not True):
        raise RuntimeError("live_crossplatform_proof_does_not_authorize_cleanup")

    local = json.loads(LOCAL_MAP.read_text(encoding="utf-8"))
    groups = [g for g in local.get("groups", []) if g.get("sha256") == SHA]
    if len(groups) != 1:
        raise RuntimeError("local_hash_group_missing_or_duplicated")
    source_files = groups[0].get("files") or []
    paths = sorted({pathlib.Path(x["path"]).resolve() for x in source_files
                    if x.get("sha256") == SHA and x.get("path")})
    if len(paths) != 4:
        raise RuntimeError("expected_four_identical_local_pdf_copies")
    allowed_root = (ROOT / "output_to_user/certificates").resolve()
    checked = []
    for path in paths:
        if path.suffix.casefold() != ".pdf" or not path.is_relative_to(allowed_root):
            raise RuntimeError("source_path_outside_certificate_library")
        if not path.is_file() or digest(path) != SHA:
            raise RuntimeError("source_file_missing_or_hash_changed")
        checked.append({"path": str(path), "sha256": SHA, "bytes": path.stat().st_size})

    with ASSIGNMENTS.open(encoding="utf-8-sig", newline="") as f:
        assignment_rows = [r for r in csv.DictReader(f)
                           if r.get("SHA256 фактический") == SHA]
    if len(assignment_rows) != 156:
        raise RuntimeError("assignment_scope_does_not_match_156_live_links")

    # Recheck all paths and hashes immediately before unlinking.
    for row in checked:
        path = pathlib.Path(row["path"])
        if not path.is_file() or digest(path) != SHA:
            raise RuntimeError("source_file_changed_before_unlink")
    for row in checked:
        pathlib.Path(row["path"]).unlink()

    remaining = [row["path"] for row in checked if pathlib.Path(row["path"]).exists()]
    if remaining:
        raise RuntimeError("some_source_paths_remain_after_unlink")
    result = {
        "deleted_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "document_number": "ЕАЭС N RU Д-CN.PA08.B.87392/22",
        "certificate_id": 5944403,
        "source_sha256": SHA,
        "ozon_approved_exact_links": 156,
        "wb_exact_metadata": 156,
        "wb_verdicts": {"valid": 156},
        "assignment_rows_for_source_hash": len(assignment_rows),
        "removed_files": checked,
        "freed_bytes": sum(x["bytes"] for x in checked),
        "remaining_matching_source_paths": remaining,
        "wb_review_left_pending": True,
    }
    temp = RESULT.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(RESULT)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
        f.flush()
    print(json.dumps({k: v for k, v in result.items() if k != "removed_files"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
