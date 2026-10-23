"""Restore IEK declaration source while 14 Ozon TN VED mismatches are unresolved."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
READBACK = HERE / "iek_66430_full_live_reconciliation_20261023.json"
CLEANUP = HERE / "iek_66430_local_cleanup_result_20261023.json"
OUT = HERE / "iek_66430_source_restored_for_scope_review_20261023.json"
EXPECTED_SHA256 = "a09742c42dba8a9066f8e7ba26ad624a9b9a7a0c3901b6ca1a5285bdd1b39caf"


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if OUT.exists():
        raise RuntimeError("restore_artifact_exists")
    audit = json.loads(READBACK.read_text(encoding="utf-8"))
    moved = json.loads(CLEANUP.read_text(encoding="utf-8"))
    mismatch_count = sum(x.get("tnved_codes") != ["8536201007"] for x in audit["target_readbacks"])
    if (audit.get("unique_reconciled_target_count") != 24
            or not all(x.get("ozon_exact_approved_binding") for x in audit["target_readbacks"])
            or not all(len(x.get("wb_cards") or []) == 1
                       and x["wb_cards"][0].get("exact_metadata_present") is True
                       for x in audit["target_readbacks"])
            or mismatch_count != 14):
        raise RuntimeError("unexpected_reconciliation_state")
    source = pathlib.Path(moved["trash_path"])
    if not source.is_file() or digest(source) != EXPECTED_SHA256:
        raise RuntimeError("trash_source_missing_or_hash_changed")
    trash_dir = source.parent
    original = ROOT / "output_to_user/certificates/group_2/IEK_GENERICA/documents" / source.name
    if original.exists():
        raise RuntimeError("original_path_already_exists")
    shutil.move(str(source), str(original))
    if not original.is_file() or digest(original) != EXPECTED_SHA256 or source.exists():
        raise RuntimeError("restore_verification_failed")
    try:
        trash_dir.rmdir()
    except OSError:
        pass
    result = {
        "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "number": audit["number"], "original_restored_path": str(original),
        "sha256": EXPECTED_SHA256, "ozon_tnved_mismatch_count": mismatch_count,
        "ozon_approved_exact_bindings": 24, "wb_exact_document_metadata": 24,
        "reason": "14 current Ozon TN VED codes differ from the active FSA scope; retain source for scope review.",
        "trash_file_removed_by_restore": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
