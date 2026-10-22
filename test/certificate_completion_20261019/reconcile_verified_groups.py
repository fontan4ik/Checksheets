"""Apply only the pre-verified document groups against fresh live catalogs."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = Path(__file__).resolve().parents[2]
PILOT = PROJECT / "test" / "certificate_api_pilot_20261012"
sys.path.insert(0, str(PILOT))
import run_all_found_certificates_20261014 as runner_module  # noqa: E402
from api_client import Client  # noqa: E402

SNAPSHOT = HERE / "live_marketplaces_snapshot.json"
MANIFEST = PILOT / "all_source_certificates_verified_manifest_20261014.json"
JOURNAL = PILOT / "all_source_certificates_mutations_20261014.jsonl"
STATE_PATH = HERE / "verified_reconciliation_state.json"

snapshot = json.loads(SNAPSHOT.read_text())
if not all(snapshot.get(k, {}).get("complete") for k in (
        "ozon_products", "ozon_certificates", "wb_catalog", "wb_trash")):
    raise RuntimeError("Fresh complete Ozon/WB snapshot required")
manifest = json.loads(MANIFEST.read_text())
if len(manifest.get("groups") or []) != 27:
    raise RuntimeError("Unexpected verified-manifest size; stop for review")

# Keep generated product/card snapshots and run state inside this dated work folder.
runner_module.BASE = HERE
runner = runner_module.Runner(
    Client(), manifest, execute=True, journal=JOURNAL, state=STATE_PATH,
)
runner.products = snapshot["ozon_products"]["products"]
runner.certs = snapshot["ozon_certificates"]["certificates"]
runner.cards = snapshot["wb_catalog"]["cards"]
runner.state["live_snapshot"] = str(SNAPSHOT)
runner.state["live_snapshot_checked_at"] = snapshot.get("updated_at")
runner.state["wb_catalog_cards"] = len(runner.cards)
runner.state["ozon_product_rows"] = len(runner.products)
runner.state["ozon_certificate_records"] = len(runner.certs)
runner.checkpoint("using_fresh_live_snapshots")
runner.process_groups()
metadata = {str(c["certificate_id"]): c for c in runner.list_certificate_metadata()}
for cert in runner.certs:
    live = metadata.get(str(cert["certificate_id"]))
    if live:
        cert.update(live)
runner.wb_reconcile()
runner.state.update(
    finished_at=datetime.now(timezone.utc).isoformat(),
    completion_phase="finished_verified_groups_reconciliation",
    no_cleanup=True,
)
runner.checkpoint("finished_verified_groups_reconciliation")
print(json.dumps({
    "finished_at": runner.state["finished_at"],
    "groups": {"processed": sum(x.get("status") == "processed" for x in runner.state["groups"]),
               "skipped": sum(x.get("status") == "skipped" for x in runner.state["groups"])},
    "eligible_targets": sum(int(x.get("eligible", 0)) for x in runner.state["groups"]),
    "skips": len(runner.state["skips"]),
    "ozon_mutations": sum(x.get("platform") == "ozon" for x in runner.state["mutations"]),
    "wb_mutations": sum(x.get("platform") == "wb" for x in runner.state["mutations"]),
    "wb_accepted_cards": runner.state.get("wb_accepted_cards", 0),
    "wb_readback_counts": runner.state.get("wb_readback_counts", {}),
    "state": str(STATE_PATH),
}, ensure_ascii=False), flush=True)
