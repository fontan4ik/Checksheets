"""Execute the remaining live-verified Feron EAEU certificate groups.

Only five current source-verified documents are included. The shared Runner
rechecks exact Ozon identity, brand and TN VED, uploads/binds missing Ozon
records, then updates and reads back matching WB cards. It never deletes PDFs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = ROOT / "test/certificate_api_pilot_20261012"
sys.path.insert(0, str(API))
from api_client import Client, now  # noqa: E402
import run_all_found_certificates_20261014 as runner_module  # noqa: E402

SUFFIXES = ("00767", "01377", "54291", "54301", "58098")
STATE = HERE / "feron_remaining_found_valid_execution_state_20261020.json"
JOURNAL = HERE / "feron_remaining_found_valid_mutation_journal_20261020.jsonl"
COMBINED = HERE / "feron_remaining_found_valid_manifest_20261020.json"


def main() -> None:
    if STATE.exists() or JOURNAL.exists():
        raise RuntimeError("Prior execution journal exists; reconcile before another run")
    groups = []
    for suffix in SUFFIXES:
        path = HERE / f"feron_{suffix}_manifest_20261020.json"
        data = json.loads(path.read_text())
        if len(data.get("groups") or []) != 1 or data.get("local_file_cleanup") is not False:
            raise RuntimeError(f"Unexpected manifest structure: {path.name}")
        group = data["groups"][0]
        if group.get("source_evidence_verified") is not True or group.get("accordance_type") != "EAEU":
            raise RuntimeError(f"Source evidence is not explicitly verified: {group.get('number')}")
        groups.append(group)
    numbers = [str(g.get("number")) for g in groups]
    if len(set(numbers)) != len(numbers):
        raise RuntimeError("Duplicate document number in selected groups")
    manifest = {"built_at": now(), "groups": groups, "blocked_document_keys": [],
                "blocked_binding_brands": {}, "skips": [], "no_cleanup": True,
                "source_manifests": [str(HERE / f"feron_{s}_manifest_20261020.json") for s in SUFFIXES]}
    tmp = COMBINED.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    tmp.replace(COMBINED)

    runner_module.BASE = HERE
    client = Client()
    runner = runner_module.Runner(client, manifest, execute=True, journal=JOURNAL, state=STATE)
    # Runner performs exact offer, brand, TN VED, validity and file-hash checks
    # before Ozon writes, and repeats source/card checks immediately before WB.
    runner.process_groups()

    targets_by_offer = {}
    for group in groups:
        for target in group.get("targets") or []:
            targets_by_offer.setdefault(str(target["offer_id"]), target)
    offers = list(targets_by_offer)
    products_by_offer = {}
    for start in range(0, len(offers), 100):
        rows = client.call("ozon", "/v3/product/info/list", {"offer_id": offers[start:start + 100]}).get("items") or []
        for row in rows:
            products_by_offer.setdefault(str(row.get("offer_id") or ""), []).append(row)
    products = []
    for offer, target in targets_by_offer.items():
        rows = products_by_offer.get(offer, [])
        if len(rows) != 1:
            continue
        row = rows[0]
        if (row.get("is_archived") is False and
                str(row.get("product_id") or row.get("id") or "") == str(target["product_id"]) and
                str(row.get("sku") or "") == str(target["sku"])):
            products.append({**row, "product_id": str(target["product_id"]), "sku": str(target["sku"])})
    runner.products = products

    cards = []
    for index, (offer, target) in enumerate(targets_by_offer.items(), 1):
        try:
            rows = client.wb_cards(offer)
        except Exception as exc:
            runner.skip("wb_exact_target_read_failed", offer_id=offer, error_type=type(exc).__name__)
            continue
        exact = [c for c in rows if c.get("vendorCode") == offer and str(c.get("nmID")) == str(target.get("wb_nmID"))]
        if len(exact) == 1:
            cards.append(exact[0])
        else:
            runner.skip("wb_exact_target_missing_or_ambiguous", offer_id=offer)
        if index % 25 == 0:
            print(f"WB exact-target preflight {index}/{len(targets_by_offer)}", flush=True)
    runner.cards = cards
    runner.checkpoint("using_exact_live_target_cards")
    runner.wb_reconcile()
    runner.state.update({"finished_at": now(), "completion_phase": "remaining_found_valid_groups_complete",
                         "no_cleanup": True, "local_files_deleted": False})
    runner.checkpoint("remaining_found_valid_groups_complete")
    print(json.dumps({
        "phase": runner.state.get("phase"),
        "groups": runner.state.get("groups"),
        "ozon_mutations": sum(x.get("platform") == "ozon" for x in runner.state.get("mutations", [])),
        "wb_mutations": sum(x.get("platform") == "wb" for x in runner.state.get("mutations", [])),
        "wb_accepted_cards": runner.state.get("wb_accepted_cards", 0),
        "wb_readback_counts": runner.state.get("wb_readback_counts", {}),
        "skips": runner.state.get("skips", []),
        "local_files_deleted": False,
        "state": str(STATE),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
