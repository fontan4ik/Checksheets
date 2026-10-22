"""Fresh all-brand pass over source-verified certificate candidates; no file cleanup."""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from bulk_found_manifest_20261014 import build_manifest  # noqa: E402
import run_all_found_certificates_20261014 as runner_module  # noqa: E402

MANIFEST = HERE / "all_found_coverage_manifest_20261021.json"
STATE = HERE / "all_found_coverage_state_20261021.json"
JOURNAL = HERE / "all_found_coverage_mutation_journal_20261021.jsonl"


def atomic(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if STATE.exists() or JOURNAL.exists():
        raise RuntimeError("prior_run_artifact_exists_reconcile_before_restart")
    manifest = build_manifest()
    manifest["no_cleanup"] = True
    atomic(MANIFEST, manifest)
    runner_module.BASE = HERE
    runner = runner_module.Runner(Client(), manifest, execute=True,
                                  journal=JOURNAL, state=STATE)
    runner.state["manifest_file"] = str(MANIFEST)
    runner.run(poll_hours=0, resume_from_snapshots=False)
    groups = runner.state.get("groups") or []
    result = {
        "phase": runner.state.get("phase"),
        "finished_at": runner.state.get("finished_at"),
        "manifest_groups": len(manifest.get("groups") or []),
        "manifest_target_edges": sum(len(g.get("targets") or []) for g in manifest.get("groups") or []),
        "group_results": groups,
        "group_status_counts": dict(Counter(x.get("status") for x in groups)),
        "mutation_count": len(runner.state.get("mutations") or []),
        "ozon_mutation_count": sum(x.get("platform") == "ozon" for x in runner.state.get("mutations") or []),
        "wb_mutation_count": sum(x.get("platform") == "wb" for x in runner.state.get("mutations") or []),
        "wb_accepted_cards": runner.state.get("wb_accepted_cards", 0),
        "wb_readback_counts": runner.state.get("wb_readback_counts", {}),
        "wb_counts": runner.state.get("wb_counts", {}),
        "pending_ozon_records": runner.state.get("pending_ozon_records", 0),
        "pending_ozon_bindings": runner.state.get("pending_ozon_bindings", 0),
        "skip_reasons": dict(Counter(x.get("reason") for x in runner.state.get("skips") or [])),
        "source_files_deleted": False,
        "local_source_cleanup": False,
        "state_file": str(STATE),
        "manifest_file": str(MANIFEST),
    }
    summary = HERE / "all_found_coverage_summary_20261021.json"
    atomic(summary, result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
