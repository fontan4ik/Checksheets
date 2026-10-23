#!/usr/bin/env python3
"""Fresh no-cleanup pass over verified document groups and approved Ozon links."""
from __future__ import annotations

import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
sys.path.insert(0, str(HERE))
from api_client import Client, now  # noqa: E402
from bulk_found_manifest_20261014 import build_manifest  # noqa: E402
import run_all_found_certificates_20261014 as runner_module  # noqa: E402

MANIFEST = HERE / "approved_crossplatform_reconcile_manifest_20261023.json"
STATE = HERE / "approved_crossplatform_reconcile_state_20261023.json"
JOURNAL = HERE / "approved_crossplatform_reconcile_journal_20261023.jsonl"
SUMMARY = HERE / "approved_crossplatform_reconcile_summary_20261023.json"


def atomic(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if any(p.exists() for p in (MANIFEST, STATE, JOURNAL, SUMMARY)):
        raise RuntimeError("resume_artifact_exists_inspect_before_start")
    manifest = build_manifest()
    manifest["no_cleanup"] = True
    atomic(MANIFEST, manifest)
    runner_module.BASE = HERE
    runner = runner_module.Runner(Client(), manifest, execute=True,
                                  journal=JOURNAL, state=STATE)
    runner.state["manifest_file"] = str(MANIFEST)
    print(json.dumps({"phase": "starting", "groups": len(manifest.get("groups") or []),
                      "edges": sum(len(g.get("targets") or []) for g in manifest.get("groups") or []),
                      "coverage": manifest.get("coverage")}, ensure_ascii=False), flush=True)
    runner.run(poll_hours=0, resume_from_snapshots=False)
    groups = runner.state.get("groups") or []
    summary = {
        "phase": runner.state.get("phase"), "finished_at": runner.state.get("finished_at"),
        "manifest_groups": len(manifest.get("groups") or []),
        "manifest_target_edges": sum(len(g.get("targets") or []) for g in manifest.get("groups") or []),
        "group_results": groups,
        "group_status_counts": dict(collections.Counter(x.get("status") for x in groups)),
        "mutation_count": len(runner.state.get("mutations") or []),
        "ozon_mutation_count": sum(x.get("platform") == "ozon" for x in runner.state.get("mutations") or []),
        "wb_mutation_count": sum(x.get("platform") == "wb" for x in runner.state.get("mutations") or []),
        "wb_accepted_cards": runner.state.get("wb_accepted_cards", 0),
        "wb_readback_counts": runner.state.get("wb_readback_counts", {}),
        "wb_counts": runner.state.get("wb_counts", {}),
        "pending_ozon_records": runner.state.get("pending_ozon_records", 0),
        "pending_ozon_bindings": runner.state.get("pending_ozon_bindings", 0),
        "skip_reasons": dict(collections.Counter(x.get("reason") for x in runner.state.get("skips") or [])),
        "source_files_deleted": False, "local_cleanup": False,
        "state_file": str(STATE), "manifest_file": str(MANIFEST),
        "journal_file": str(JOURNAL),
    }
    atomic(SUMMARY, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
