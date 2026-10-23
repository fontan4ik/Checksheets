"""Move the fully linked IEK 66430/26 source PDF to recoverable macOS Trash."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
READBACK = HERE / "iek_66430_full_live_reconciliation_20261023.json"
OUT = HERE / "iek_66430_local_cleanup_result_20261023.json"
JOURNAL = HERE / "iek_66430_local_cleanup_journal_20261023.jsonl"
EXPECTED_SHA256 = "a09742c42dba8a9066f8e7ba26ad624a9b9a7a0c3901b6ca1a5285bdd1b39caf"


def digest(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("cleanup_artifact_exists")
    audit = json.loads(READBACK.read_text(encoding="utf-8"))
    checks = audit["conditions"]
    required = ["assignment_and_expanded_target_count",
                "all_targets_exact_approved_ozon_binding",
                "all_targets_one_exact_wb_card",
                "all_wb_target_cards_have_exact_doc_metadata",
                "all_wb_targets_brand_and_tnved_safe"]
    if not all(checks.get(key) is True for key in required):
        raise RuntimeError("crossplatform_linkage_gate_failed")
    if audit.get("unique_reconciled_target_count") != 24:
        raise RuntimeError("target_count_gate_failed")
    source = pathlib.Path(audit["source_file"])
    if not source.is_file() or digest(source) != EXPECTED_SHA256:
        raise RuntimeError("source_hash_gate_failed")
    copies = []
    for path in (ROOT / "output_to_user/certificates").rglob("*.pdf"):
        if path.is_file() and path.stat().st_size == source.stat().st_size and digest(path) == EXPECTED_SHA256:
            copies.append(path)
    if len(copies) != 1 or copies[0].resolve() != source.resolve():
        raise RuntimeError(f"source_copy_count_changed:{len(copies)}")

    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    destination_dir = pathlib.Path.home() / ".Trash" / "Подтверждены_Ozon_WB_IEK_66430_20261023"
    destination_dir.mkdir(parents=True, exist_ok=False)
    destination = destination_dir / source.name
    shutil.move(str(source), str(destination))
    if source.exists() or not destination.is_file() or digest(destination) != EXPECTED_SHA256:
        raise RuntimeError("post_move_verification_failed")

    result = {
        "checked_at_utc": timestamp,
        "number": audit["number"],
        "source_original_path": str(source),
        "trash_path": str(destination),
        "sha256": EXPECTED_SHA256,
        "unique_reconciled_target_count": audit["unique_reconciled_target_count"],
        "ozon_approved_exact_binding_count": sum(
            x.get("ozon_exact_approved_binding") is True for x in audit["target_readbacks"]),
        "wb_exact_metadata_count": sum(
            len(x.get("wb_cards") or []) == 1 and x["wb_cards"][0].get("exact_metadata_present") is True
            for x in audit["target_readbacks"]),
        "ozon_tnved_mismatch_count": sum(
            not (x.get("tnved_codes") and set(x["tnved_codes"]) <= {"8536201007"})
            for x in audit["target_readbacks"]),
        "recoverable_trash_not_emptied": True,
        "bytes_hash_verified_after_move": True,
    }
    JOURNAL.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
