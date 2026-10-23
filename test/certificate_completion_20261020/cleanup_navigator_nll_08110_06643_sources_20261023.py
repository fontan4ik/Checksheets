#!/usr/bin/env python3
"""Move confirmed Navigator source PDFs to macOS Trash and record recovery details."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT = HERE / "navigator_nll_08110_06643_live_crossplatform_recheck_20261023.json"
RECEIPT = HERE / "navigator_nll_08110_06643_local_pdf_cleanup_20261023.json"

FILES = [
    (ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_declaration_14008_6281784d69c8.pdf",
     "6281784d69c80c6fb396c095d4fafef82fad9771694f8b74510a7fafc2846fd2"),
    (ROOT / "output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14008_c86b71122269.pdf",
     "c86b711222697c5131ad96022e0e9d91b5127c0ed60e68bd1995016de2289c38"),
    (ROOT / "output_to_user/certificates/additional_search/brand_research/navigator/followup_2026_10_02/documents/originals/NAV_93812_declaration_2024_original.pdf",
     "6281784d69c80c6fb396c095d4fafef82fad9771694f8b74510a7fafc2846fd2"),
]


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(value: dict) -> None:
    temp = RECEIPT.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(RECEIPT)


def main() -> None:
    if RECEIPT.exists():
        raise RuntimeError("cleanup_receipt_already_exists; reconcile before retry")
    report = json.loads(REPORT.read_text())
    checked = dt.datetime.fromisoformat(report["checked_at_utc"].replace("Z", "+00:00"))
    age = (dt.datetime.now(dt.timezone.utc) - checked).total_seconds()
    if age < 0 or age > 3600 or report.get("read_only") is not True:
        raise RuntimeError("live_readback_not_recent_or_not_read_only")
    if report.get("complete_for_verified_in_scope_targets") is not True:
        raise RuntimeError("crossplatform_coverage_not_complete")
    if report["scope"] != {"base_targets": 56, "extra_declaration_targets": 2,
                           "ozon_declaration_expected": 58, "ozon_certificate_expected": 56,
                           "wb_declaration_expected": 58, "wb_certificate_expected": 56,
                           "ozon_mismatched_tnved_targets_skipped": 97}:
        raise RuntimeError("unexpected_scope_in_live_readback")
    for platform in ("ozon", "wb"):
        for row in report[platform].values():
            if not row.get("complete"):
                raise RuntimeError("incomplete_live_readback:" + platform)
    for key, expected in (("declaration", (58, 58)), ("certificate", (56, 56))):
        oz = report["ozon"][key]
        wb = report["wb"][key]
        if (oz.get("expected_exact_pairs") != expected[0]
                or oz.get("binding_rows") != expected[0]
                or oz.get("status_counts") != {"approved": expected[0]}
                or wb.get("target_cards") != expected[1]
                or wb.get("verified_exact_valid_cards") != expected[1]
                or wb.get("status_counts") != {"valid": expected[1]}):
            raise RuntimeError("unexpected_live_counts:" + key)

    entries = []
    for path, expected_hash in FILES:
        if not path.is_file():
            raise RuntimeError("source_file_missing:" + str(path))
        actual_hash = digest(path)
        if actual_hash != expected_hash:
            raise RuntimeError("source_hash_mismatch:" + str(path))
        entries.append({"original_path": str(path), "sha256": actual_hash,
                        "size_bytes": path.stat().st_size, "moved_to_trash": False,
                        "recovery_path": None})

    prepared = {"prepared_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "status": "prepared", "verification_report": str(REPORT),
                "verification_checked_at_utc": report["checked_at_utc"],
                "verification_age_seconds": int(age), "files": entries,
                "trash_tool": "/usr/bin/trash", "trash_was_not_emptied": True}
    save(prepared)
    result = subprocess.run(["/usr/bin/trash", *[str(path) for path, _ in FILES]],
                            capture_output=True, text=True)
    prepared["trash_exit_code"] = result.returncode
    prepared["trash_stdout"] = result.stdout.strip()
    prepared["trash_stderr"] = result.stderr.strip()
    if result.returncode != 0:
        prepared["status"] = "trash_move_failed"
        save(prepared)
        raise RuntimeError("trash_move_failed; see cleanup receipt")
    for entry in entries:
        if pathlib.Path(entry["original_path"]).exists():
            prepared["status"] = "post_move_verification_failed"
            save(prepared)
            raise RuntimeError("source_still_exists_after_trash_move")

    uid = os.getuid()
    roots = [pathlib.Path(f"/Volumes/жесткач/.Trashes/{uid}"), pathlib.Path.home() / ".Trash"]
    for entry in entries:
        matches = []
        for trash_root in roots:
            if not trash_root.exists():
                continue
            for candidate in trash_root.rglob("*"):
                try:
                    if candidate.is_file() and digest(candidate) == entry["sha256"]:
                        matches.append(str(candidate))
                except (OSError, PermissionError):
                    continue
        entry["moved_to_trash"] = bool(matches)
        entry["recovery_path"] = matches[0] if len(matches) == 1 else None
        entry["matching_trash_copies"] = len(matches)

    prepared.update({"status": "moved_to_trash", "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "all_original_paths_absent": all(not pathlib.Path(x["original_path"]).exists() for x in entries),
                     "all_files_recoverable_in_trash": all(x["moved_to_trash"] and x["matching_trash_copies"] == 1 for x in entries)})
    save(prepared)
    print(json.dumps({"status": prepared["status"], "file_count": len(entries),
                      "all_original_paths_absent": prepared["all_original_paths_absent"],
                      "all_files_recoverable_in_trash": prepared["all_files_recoverable_in_trash"],
                      "receipt": str(RECEIPT),
                      "files": [{"name": pathlib.Path(x["original_path"]).name,
                                 "sha256": x["sha256"], "recovery_path": x["recovery_path"]} for x in entries]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
