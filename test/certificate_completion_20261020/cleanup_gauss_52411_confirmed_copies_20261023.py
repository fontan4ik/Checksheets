#!/usr/bin/env python3
"""Permanently remove only the verified 52411/23 duplicate PDFs from Trash."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OZON = HERE / "gauss_52411_ozon_and_local_copy_recheck_20261023.json"
WB = HERE / "wb_delayed_recheck_remaining_20261023.json"
PREFLIGHT = HERE / "gauss_52411_crossplatform_preflight_20261023.json"
OUT = HERE / "gauss_52411_confirmed_files_permanently_removed_20261023.json"
JOURNAL = HERE / "gauss_52411_confirmed_files_permanently_removed_20261023.jsonl"
EXPECTED_SHA256 = "b9503157b344ec2ed68fe168f8b7c9f7046d28a1e7734b8a9949589c5b12ad3d"
EXPECTED_PATHS = {
    pathlib.Path("/Volumes/жесткач/.Trashes/501/25aeb2f93ed587f14b19dc21.pdf"),
    pathlib.Path("/Volumes/жесткач/.Trashes/501/gfl_rechargeable_037.pdf"),
}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("cleanup_artifact_exists")
    ozon = json.loads(OZON.read_text(encoding="utf-8"))
    wb = json.loads(WB.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    wb_group = wb.get("groups", {}).get("gauss_52411") or {}
    binding_states = ozon.get("ozon_binding_status_counts") or {}
    fsa = preflight.get("fsa") or {}
    if (ozon.get("document_number") != "ЕАЭС N RU Д-CN.РА04.В.52411/23"
            or ozon.get("ozon_record_id") != "5966062"
            or ozon.get("ozon_record_status") != "approved"
            or ozon.get("ozon_binding_count") != 26
            or binding_states != {"approved": 26}):
        raise RuntimeError("fresh_ozon_approval_gate_failed")
    if (wb_group.get("target_count") != 29
            or wb_group.get("exact_card_count") != 29
            or wb_group.get("exact_metadata_count") != 29
            or wb_group.get("verdict_counts") != {"valid": 29}):
        raise RuntimeError("fresh_wb_validity_gate_failed")
    if (preflight.get("ozon_safe_count") != 26 or preflight.get("wb_safe_count") != 29
            or preflight.get("wb_blocker_counts") != {}
            or set(x.get("offer_id") for x in preflight.get("targets", [])
                   if x.get("ozon_blockers") == ["ozon_tnved_mismatch_or_ambiguous"])
               != {"GF001-1", "GF002-1", "GF801-1"}
            or fsa.get("record_id") != "17768504"
            or fsa.get("status") != "Действует"):
        raise RuntimeError("scope_and_fsa_gate_failed")
    if OUT.exists() or JOURNAL.exists():
        raise RuntimeError("cleanup_artifact_race")

    trash_root = pathlib.Path("/Volumes/жесткач/.Trashes/501")
    found = set()
    for path in trash_root.rglob("*.pdf"):
        if path.is_file() and path.stat().st_size == 3_874_385 and sha256(path) == EXPECTED_SHA256:
            found.add(path.resolve())
    if found != {p.resolve() for p in EXPECTED_PATHS}:
        raise RuntimeError("unexpected_verified_trash_copy_set:" + json.dumps(sorted(map(str, found)), ensure_ascii=False))
    if any((ROOT / rel).exists() for rel in (
        "output_to_user/certificates/group_1/documents/gauss/25aeb2f93ed587f14b19dc21.pdf",
        "output_to_user/certificates/additional_search/brand_research/gauss/docs/gfl_rechargeable_037.pdf")):
        raise RuntimeError("original_source_path_reappeared")

    results = []
    total_bytes = 0
    for path in sorted(EXPECTED_PATHS):
        before_size = path.stat().st_size
        path.unlink()
        if path.exists():
            raise RuntimeError("source_copy_still_exists:" + str(path))
        total_bytes += before_size
        results.append({"path": str(path), "sha256": EXPECTED_SHA256,
                        "size_bytes": before_size, "permanently_removed": True})
    result = {
        "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "document_number": "ЕАЭС N RU Д-CN.РА04.В.52411/23",
        "fsa_status": fsa.get("status"),
        "ozon_record_status": ozon.get("ozon_record_status"),
        "ozon_approved_exact_bindings": ozon.get("ozon_binding_count"),
        "wb_valid_exact_cards": wb_group.get("exact_metadata_count"),
        "ozon_tnved_out_of_scope_skips": ["GF001-1", "GF002-1", "GF801-1"],
        "files": results,
        "permanently_freed_bytes": total_bytes,
        "full_trash_not_emptied": True,
    }
    JOURNAL.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
