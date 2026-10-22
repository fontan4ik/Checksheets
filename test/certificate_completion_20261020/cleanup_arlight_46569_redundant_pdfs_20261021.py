"""Remove redundant 46569/26 PDF copies after fresh exact cross-platform confirmation."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "test/certificate_api_pilot_20261012"))
from api_client import now  # noqa: E402

PREFLIGHT = json.loads((HERE / "arlight_46569_preflight_live_20261021.json").read_text())
OZON = json.loads((HERE / "arlight_46569_ozon_final_readback_20261021.json").read_text())
WB = json.loads((HERE / "arlight_46569_wb_fresh_readback_20261021.json").read_text())
RECEIPT = HERE / "arlight_46569_local_pdf_cleanup_receipt_20261021.json"
JOURNAL = HERE / "arlight_46569_local_pdf_cleanup_journal_20261021.jsonl"
SOURCE_HASH = "f5129cee3e2e0db750042781ca096411d1186d6cbdfe6f6603a10219e5ec7038"
RETAIN = ROOT / "output_to_user/certificates/additional_search/brand_research/arlight/followup_2026_10_02_suppliers/docs/f5129cee3e2e0db7.pdf"
PRIMARY = ROOT / "output_to_user/certificates/group_1/documents/arlight/97331E1740F80745A33F67528E33A9AB.pdf"

if RECEIPT.exists() or JOURNAL.exists():
    raise RuntimeError("cleanup_artifact_exists_inspect_before_retry")
if not (OZON.get("complete") is True and OZON.get("document_metadata_exact") is True
        and OZON.get("verified_target_bindings") == 905
        and OZON.get("binding_status_counts") == {"approved": 905}):
    raise RuntimeError("fresh_ozon_confirmation_incomplete")
if not (WB.get("complete") is True and WB.get("read_only") is True
        and WB.get("verified_target_cards") == 905 and WB.get("status_counts") == {"valid": 905}
        and not WB.get("failures")):
    raise RuntimeError("fresh_wb_confirmation_incomplete")
targets = {str(row["offer_id"]) for row in PREFLIGHT.get("ozon_targets") or []}
if len(targets) != 905 or len({str(row["offer_id"]) for row in PREFLIGHT.get("wb_targets") or []}) != 905:
    raise RuntimeError("preflight_target_manifest_incomplete")
if not PRIMARY.is_file() or not RETAIN.is_file():
    raise RuntimeError("primary_or_unresolved_candidate_copy_missing")
if hashlib.sha256(PRIMARY.read_bytes()).hexdigest() != SOURCE_HASH:
    raise RuntimeError("primary_source_hash_mismatch")

# Preserve one verified identical copy for separate source-map rows that remain
# unresolved because their manufacturing batch/manufacturer is not established.
roots = [ROOT / "output_to_user/certificates", ROOT / "test/certificate_completion_20261020"]
copies: list[pathlib.Path] = []
for scan_root in roots:
    for path in scan_root.rglob("*.pdf"):
        try:
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == SOURCE_HASH:
                copies.append(path)
        except OSError as exc:
            raise RuntimeError(f"cannot_audit_pdf_copy:{path}:{type(exc).__name__}") from None
copies = sorted(set(copies))
if len(copies) < 2 or RETAIN not in copies or PRIMARY not in copies:
    raise RuntimeError("expected_duplicate_hash_copies_not_found")
to_delete = [path for path in copies if path != RETAIN]
if not to_delete:
    raise RuntimeError("no_redundant_copies_found")
for path in to_delete:
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_HASH:
        raise RuntimeError(f"copy_hash_changed_before_delete:{path}")

entry = {
    "phase": "prepared_for_delete",
    "at": now(),
    "number": "ЕАЭС N RU Д-CN.РА01.В.46569/26",
    "sha256": SOURCE_HASH,
    "target_offers_confirmed": 905,
    "ozon_approved_bindings": 905,
    "wb_valid_cards": 905,
    "confirmed_ozon_at": OZON.get("checked_at"),
    "confirmed_wb_at": WB.get("checked_at"),
    "same_hash_copy_count_before": len(copies),
    "retained_for_unresolved_candidates": str(RETAIN),
    "retained_for_unresolved_candidate_assignments": 20,
    "files_to_delete": [{"path": str(path), "bytes": path.stat().st_size} for path in to_delete],
}
JOURNAL.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
bytes_reclaimed = 0
for path in to_delete:
    path.unlink()
    if path.exists():
        raise RuntimeError(f"path_still_exists_after_unlink:{path}")
    bytes_reclaimed += int(next(item["bytes"] for item in entry["files_to_delete"] if item["path"] == str(path)))
remaining = []
for scan_root in roots:
    for path in scan_root.rglob("*.pdf"):
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == SOURCE_HASH:
            remaining.append(path)
if remaining != [RETAIN]:
    raise RuntimeError("post_delete_copy_inventory_mismatch")
receipt = {
    **entry,
    "phase": "redundant_copies_deleted_verified_one_retained",
    "verified_at": now(),
    "deleted_copy_count": len(to_delete),
    "bytes_reclaimed": bytes_reclaimed,
    "same_hash_copies_left": len(remaining),
    "retained_file_sha256": hashlib.sha256(RETAIN.read_bytes()).hexdigest(),
    "local_redundant_pdfs_deleted": True,
    "crossplatform_confirmation": {"ozon": OZON.get("complete"), "wb": WB.get("complete")},
}
tmp = RECEIPT.with_suffix(".tmp")
tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(RECEIPT)
with JOURNAL.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
print(json.dumps(receipt, ensure_ascii=False, indent=2))
