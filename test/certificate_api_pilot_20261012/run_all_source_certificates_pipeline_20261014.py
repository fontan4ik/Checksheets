"""Persistent all-brand source-PDF OCR, admission, Ozon, and WB pipeline.

The coordinator runs the embedded-text pass and marketplace work immediately,
then OCRs every eligible original PDF, rebuilds the verified manifest, and runs
the marketplace pass again. A shared durable mutation journal prevents retries.
It never deletes local files.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
STATE = BASE / "all_source_certificates_pipeline_state_20261014.json"
LOCK = BASE / "all_source_certificates_pipeline_20261014.lock"
LOG_DIR = BASE / "all_source_certificates_pipeline_logs_20261014"
EXTRACTOR = BASE / "extract_found_document_text_20261014.py"
BUILDER = BASE / "expand_found_certificates_queue_20261014.py"
RUNNER = BASE / "run_all_found_certificates_20261014.py"
OCR_PYTHON = Path(
    "/Users/vladimirgrebennikov/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/python/bin/python3"
)
JOURNAL = BASE / "all_source_certificates_mutations_20261014.jsonl"
RUNNER_LOCK = BASE / "all_source_certificates_runner_20261014.lock"
NATIVE_MANIFEST = BASE / "all_source_certificates_native_manifest_20261014.json"
FINAL_MANIFEST = BASE / "all_source_certificates_verified_manifest_20261014.json"
EXTRACTION_PROGRESS = BASE / "found_document_text_extraction_progress_20261014.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def load(path: Path, default: object = None) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def brief_extraction_progress() -> dict:
    progress = load(EXTRACTION_PROGRESS, {})
    if not isinstance(progress, dict):
        return {}
    results = progress.get("results", [])
    return {
        "stage": progress.get("stage"),
        "files_processed": progress.get("files_processed", 0),
        "total_files": progress.get("total_files", 0),
        "complete_text_files": sum(bool(x.get("complete")) for x in results),
        "files_with_errors": sum(bool(x.get("error") or x.get("errors")) for x in results),
        "current_sha256": progress.get("current_sha256"),
    }


def brief_manifest(path: Path) -> dict:
    manifest = load(path, {})
    if not isinstance(manifest, dict):
        return {}
    coverage = manifest.get("coverage", {})
    return {
        "document_groups": len(manifest.get("groups", [])),
        "target_edges": sum(len(g.get("targets", [])) for g in manifest.get("groups", [])),
        "brands": coverage.get("ready_brands", {}),
        "admitted_source_hashes": coverage.get("admitted_source_hashes", 0),
        "expanded_target_edges": coverage.get("expanded_target_edges", 0),
        "skip_reasons": coverage.get("expansion_skip_reasons", {}),
        "manifest_file": str(path),
    }


def run_stage(state: dict, name: str, argv: list[str], stdout_path: Path,
              stderr_path: Path, progress_kind: str = "") -> int:
    entry = {
        "name": name,
        "status": "running",
        "started_at": now(),
        "command": argv,
        "stdout_file": str(stdout_path),
        "stderr_file": str(stderr_path),
    }
    state["active_stage"] = name
    state.setdefault("stages", []).append(entry)
    atomic(STATE, state)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("a") as stdout, stderr_path.open("a") as stderr:
        child = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr)
        entry["pid"] = child.pid
        state["child_pid"] = child.pid
        atomic(STATE, state)
        while (return_code := child.poll()) is None:
            if progress_kind == "extract":
                entry["progress"] = brief_extraction_progress()
            elif progress_kind == "runner":
                progress_lines = []
                try:
                    with stdout_path.open() as progress_file:
                        for line in progress_file:
                            try:
                                item = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(item, dict) and item.get("phase"):
                                progress_lines.append(item)
                    entry["last_runner_checkpoint"] = progress_lines[-1] if progress_lines else None
                except OSError:
                    pass
            atomic(STATE, state)
            time.sleep(5)
    entry.update(
        status="completed" if return_code == 0 else "failed",
        return_code=return_code,
        finished_at=now(),
    )
    if progress_kind == "extract":
        entry["progress"] = brief_extraction_progress()
    state["child_pid"] = None
    state["active_stage"] = None
    atomic(STATE, state)
    return return_code


def build_manifest(state: dict, name: str, destination: Path) -> bool:
    builder_log = LOG_DIR / f"{name}.log"
    builder_err = LOG_DIR / f"{name}.err.log"
    result = run_stage(state, name, [sys.executable, str(BUILDER)], builder_log, builder_err)
    generated = BASE / "expanded_found_certificates_manifest_20261014.json"
    if generated.is_file():
        destination.write_bytes(generated.read_bytes())
        state.setdefault("manifests", {})[name] = brief_manifest(destination)
        atomic(STATE, state)
    return result == 0 and destination.is_file()


def runner_command(manifest: Path, state_path: Path, poll_hours: float) -> list[str]:
    return [
        sys.executable, str(RUNNER), "--execute",
        "--manifest-file", str(manifest.resolve()),
        "--state-file", str(state_path.resolve()),
        "--journal-file", str(JOURNAL.resolve()),
        "--lock-file", str(RUNNER_LOCK.resolve()),
        "--wait-for-lock",
        "--poll-hours", str(poll_hours),
    ]


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("An all-source certificate pipeline is already active", flush=True)
            return 2

        state = {
            "started_at": now(),
            "pid": os.getpid(),
            "status": "running",
            "scope": "all 510 SHA-verified original PDFs, every source brand",
            "local_file_deletion": False,
            "stages": [],
            "manifests": {},
            "journal_file": str(JOURNAL),
            "ocr_progress_file": str(EXTRACTION_PROGRESS),
            "eta_note": "Elapsed time depends on PDF page count, marketplace response time, and Ozon review.",
        }
        atomic(STATE, state)
        print(f"All-source pipeline started pid={os.getpid()} at {state['started_at']}", flush=True)

        native_ok = run_stage(
            state, "extract_embedded_text_all_originals",
            [str(OCR_PYTHON), str(EXTRACTOR), "--no-ocr"],
            LOG_DIR / "extract_embedded_text.log", LOG_DIR / "extract_embedded_text.err.log", "extract",
        ) == 0
        state["native_extraction_stage_ok"] = native_ok
        atomic(STATE, state)

        native_manifest_ok = build_manifest(state, "build_native_manifest", NATIVE_MANIFEST)
        if native_manifest_ok:
            state["manifests"]["native"] = brief_manifest(NATIVE_MANIFEST)
            atomic(STATE, state)
            run_stage(
                state, "upload_native_verified_groups_all_brands",
                runner_command(NATIVE_MANIFEST, BASE / "all_source_certificates_native_state_20261014.json", 0),
                LOG_DIR / "upload_native_groups.log", LOG_DIR / "upload_native_groups.err.log", "runner",
            )
        else:
            state.setdefault("warnings", []).append("Native manifest build failed; continuing to full OCR and final build.")
            atomic(STATE, state)

        ocr_ok = run_stage(
            state, "ocr_all_remaining_original_pdf_pages",
            [str(OCR_PYTHON), str(EXTRACTOR)],
            LOG_DIR / "ocr_all_originals.log", LOG_DIR / "ocr_all_originals.err.log", "extract",
        ) == 0
        state["full_ocr_stage_ok"] = ocr_ok
        atomic(STATE, state)

        final_manifest_ok = build_manifest(state, "build_final_verified_manifest", FINAL_MANIFEST)
        if final_manifest_ok:
            state["manifests"]["final"] = brief_manifest(FINAL_MANIFEST)
            atomic(STATE, state)
            run_stage(
                state, "upload_all_final_verified_groups_both_marketplaces",
                runner_command(FINAL_MANIFEST, BASE / "all_source_certificates_final_state_20261014.json", 0.5),
                LOG_DIR / "upload_final_groups.log", LOG_DIR / "upload_final_groups.err.log", "runner",
            )
        else:
            state.setdefault("warnings", []).append("Final expanded manifest build failed; final marketplace pass was skipped.")
            atomic(STATE, state)

        finished = now()
        failures = [s["name"] for s in state["stages"] if s.get("status") != "completed"]
        state.update(
            status="finished_with_errors" if failures else "finished",
            finished_at=finished,
            failed_stages=failures,
            remaining_manual_review="Problematic, expired, ambiguous, lot-restricted, or out-of-scope files stay skipped for follow-up.",
        )
        atomic(STATE, state)
        print(f"All-source pipeline {state['status']} at {finished}; failed stages={failures}", flush=True)
        return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
