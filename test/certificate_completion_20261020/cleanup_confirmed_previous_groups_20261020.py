"""Remove cached source copies only after exact Ozon + WB readback succeeds."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FERON_ROOT = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
AUDIT = HERE / "previously_processed_groups_crossplatform_recheck_20261020.json"
SOURCE_MANIFEST = ROOT / "test/certificate_api_pilot_20261012/all_source_certificates_verified_manifest_20261014.json"
ASSIGNMENTS = ROOT / "output_to_user/certificates/document_assignments.csv"
CATALOG = ROOT / "output_to_user/certificates/document_catalog_master.csv"
MAIN_RECEIPT = HERE / "local_pdf_cleanup_receipt_20261020.json"
MAIN_REPORT = HERE / "post_upload_reconciliation_20261020.json"
MAIN_MARKDOWN = HERE / "post_upload_reconciliation_20261020.md"
RECEIPT = HERE / "previously_processed_groups_local_cleanup_receipt_20261020.json"
JOURNAL = HERE / "previously_processed_groups_local_cleanup_journal_20261020.jsonl"
EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
SCAN_ROOTS = [ROOT / "output_to_user/certificates", ROOT / "test/certificate_api_pilot_20261012", FERON_ROOT]


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def recompute_candidate(group: dict) -> bool:
    ozon = group.get("ozon") or {}
    wb = group.get("wb") or {}
    wb_counts = wb.get("offer_counts") or {}
    return bool(
        group.get("ozon_record_count") == 1
        and ozon.get("document_status") == "approved"
        and ozon.get("record_type") == group.get("type_code")
        and ozon.get("issue_date") == group.get("issue_date")
        and ozon.get("expire_date") == group.get("expire_date")
        and ozon.get("target_binding_status_counts") == {"approved": group.get("target_count")}
        and ozon.get("all_binding_status_counts") == {"approved": group.get("target_count")}
        and ozon.get("extra_binding_pairs") == 0
        and not ozon.get("target_binding_problems")
        and not ozon.get("current_product_identity_problems")
        and not wb.get("edge_problems")
        and wb_counts.get("valid", 0) + wb_counts.get("pending", 0)
        + wb_counts.get("no_card", 0) == group.get("target_count")
    )


def scan_for_hashes(hashes: set[str]) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = defaultdict(list)
    seen = set()
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".venv"}]
            for filename in filenames:
                candidate = Path(dirpath) / filename
                if candidate.suffix.lower() not in EXTENSIONS or candidate.is_symlink():
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                digest = sha256(resolved)
                if digest in hashes:
                    found[digest].append(resolved)
        print(json.dumps({"phase": "local_hash_scan", "root": str(root),
                          "matching_copies": sum(len(v) for v in found.values())}, ensure_ascii=False), flush=True)
    return found


def build_plan() -> dict:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    assignments = read_csv(ASSIGNMENTS)
    catalog = read_csv(CATALOG)
    manifest_by_number = {g["number"]: g for g in manifest.get("groups") or []}
    candidates = [g for g in audit.get("groups") or [] if recompute_candidate(g)]
    if len(candidates) != 15:
        raise RuntimeError(f"Expected 15 cross-platform groups, found {len(candidates)}")

    # A source file shared by additional assigned offer IDs is retained until those
    # assignments are separately confirmed. This blocks 05783/26 and 41382/26.
    accepted = []
    blocked = []
    for group in candidates:
        source = manifest_by_number.get(group["number"])
        if not source:
            blocked.append({"number": group["number"], "reason": "source manifest group is missing"})
            continue
        expected_offers = {str(t["offer_id"]) for t in source.get("targets") or []}
        same_hash_rows = [r for r in assignments if r.get("SHA256 фактический") == group["source_sha256"]]
        assigned_offers = {str(r.get("Артикул продавца") or "") for r in same_hash_rows if r.get("Артикул продавца")}
        if assigned_offers and assigned_offers != expected_offers:
            blocked.append({
                "number": group["number"],
                "reason": "source SHA is also assigned to offer IDs outside the verified group",
                "extra_offers": sorted(assigned_offers - expected_offers),
                "missing_assignment_offers": sorted(expected_offers - assigned_offers),
            })
            continue
        catalog_rows = [r for r in catalog if r.get("SHA256") == group["source_sha256"]]
        source_path = Path(group["source_file"])
        allowed = any(is_inside(source_path.resolve(), root.resolve()) for root in SCAN_ROOTS if root.exists())
        if not allowed or source_path.is_symlink() or not source_path.is_file():
            blocked.append({"number": group["number"], "reason": "source path missing, symlinked, or outside approved scan roots"})
            continue
        if source_path.stat().st_size != group["source_size"] or sha256(source_path) != group["source_sha256"]:
            blocked.append({"number": group["number"], "reason": "source path size/hash differs from verified manifest"})
            continue
        # A catalog path row that names unrelated document numbers is ambiguous.
        bad_catalog = []
        for row in catalog_rows:
            text = row.get("Номера/названия документов") or ""
            if group["number"].split("/")[-1].split("/")[0].split(" ")[0] and group["number"].split("/")[-1].split("/")[0].split(" ")[0] not in text:
                # Non-exact source aliases are allowed only where assignments match
                # the exact verified offer set; otherwise the source remains local.
                if assigned_offers != expected_offers:
                    bad_catalog.append(text)
        if bad_catalog:
            blocked.append({"number": group["number"], "reason": "source catalog has unresolved document aliases"})
            continue
        accepted.append({
            "number": group["number"],
            "certificate_id": group["ozon"]["certificate_id"],
            "source_sha256": group["source_sha256"],
            "source_size": group["source_size"],
            "source_path": str(source_path.resolve()),
            "target_count": group["target_count"],
            "ozon_binding_count": group["ozon"]["live_binding_count"],
            "ozon_binding_statuses": group["ozon"]["all_binding_status_counts"],
            "wb_status_counts": group["wb"]["offer_counts"],
            "wb_nmids": [edge["nmID"] for edge in group["wb"]["edges"]],
            "marketplace_audit_group": group,
            "assignment_rows_with_same_sha": len(same_hash_rows),
            "assignment_offers_with_same_sha": len(assigned_offers),
            "catalog_aliases": [r.get("Номера/названия документов") for r in catalog_rows],
        })

    if len(accepted) != 13 or len(blocked) != 2:
        raise RuntimeError(f"Expected 13 safe groups and 2 held groups; got {len(accepted)} and {len(blocked)}")
    hashes = {x["source_sha256"] for x in accepted}
    if len(hashes) != len(accepted):
        raise RuntimeError("Two accepted certificate groups share the same source SHA; manual review required")
    duplicates = scan_for_hashes(hashes)
    for item in accepted:
        copies = sorted(set(duplicates.get(item["source_sha256"], [])))
        if Path(item["source_path"]) not in copies:
            raise RuntimeError(f"Source file not found by full local hash scan: {item['number']}")
        item["duplicate_paths"] = [str(path) for path in copies]
        item["duplicate_copy_count"] = len(copies)
        item["bytes_to_reclaim"] = sum(path.stat().st_size for path in copies)
        for path in copies:
            if path.is_symlink() or not any(is_inside(path, root.resolve()) for root in SCAN_ROOTS if root.exists()):
                raise RuntimeError(f"Unsafe local duplicate path: {path}")
            if path.stat().st_size != item["source_size"] or sha256(path) != item["source_sha256"]:
                raise RuntimeError(f"Duplicate path failed exact size/hash check: {path}")
    return {
        "status": "verified_plan",
        "prepared_at": stamp(),
        "ozon_checked_at": audit.get("checked_at"),
        "wb_checked_at": audit.get("wb_checked_at"),
        "wb_catalog_snapshot": audit.get("wb_catalog_snapshot"),
        "verified_source_groups": accepted,
        "retained_groups": blocked,
        "summary": {
            "documents_to_delete": len(accepted),
            "copies_to_delete": sum(x["duplicate_copy_count"] for x in accepted),
            "bytes_to_reclaim": sum(x["bytes_to_reclaim"] for x in accepted),
            "groups_retained": len(blocked),
        },
    }


def save(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def execute(plan: dict) -> None:
    if JOURNAL.exists() or RECEIPT.exists():
        raise RuntimeError("Cleanup journal/receipt already exists; refusing a second execution")
    plan["status"] = "deleting_verified_copies"
    save(RECEIPT, plan)
    deleted = []
    with JOURNAL.open("x", encoding="utf-8") as journal:
        for group in plan["verified_source_groups"]:
            for name in group["duplicate_paths"]:
                path = Path(name)
                if (path.is_symlink() or not path.is_file()
                        or path.stat().st_size != group["source_size"]
                        or sha256(path) != group["source_sha256"]):
                    raise RuntimeError(f"Local copy changed before deletion: {path}")
                event = {"phase": "prepared", "at": stamp(), "number": group["number"],
                         "certificate_id": group["certificate_id"], "path": str(path),
                         "sha256": group["source_sha256"], "size": group["source_size"]}
                journal.write(json.dumps(event, ensure_ascii=False) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                path.unlink()
                if path.exists():
                    raise RuntimeError(f"Local certificate copy remains after unlink: {path}")
                event.update(phase="deleted_and_absent", at=stamp())
                journal.write(json.dumps(event, ensure_ascii=False) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                deleted.append(event)
                group.setdefault("deleted_paths", []).append(str(path))
                group["last_copy_deleted_at"] = event["at"]
                save(RECEIPT, plan)
    plan["status"] = "deleted_after_marketplace_confirmation"
    plan["completed_at"] = stamp()
    plan["deleted_copy_count"] = len(deleted)
    plan["bytes_reclaimed"] = sum(x["size"] for x in deleted)
    plan["deleted_paths_absent"] = all(not Path(x["path"]).exists() for x in deleted)
    if not plan["deleted_paths_absent"]:
        raise RuntimeError("Post-delete verification failed")
    save(RECEIPT, plan)

    main_receipt = json.loads(MAIN_RECEIPT.read_text(encoding="utf-8"))
    prior = {row.get("sha256"): row for row in main_receipt.get("source_files") or []}
    for group in plan["verified_source_groups"]:
        row = {
            "number": group["number"],
            "path": group["source_path"],
            "duplicate_paths": group["duplicate_paths"],
            "sha256": group["source_sha256"],
            "size_bytes": group["bytes_to_reclaim"],
            "single_copy_size_bytes": group["source_size"],
            "duplicate_copy_count": group["duplicate_copy_count"],
            "certificate_ids": [group["certificate_id"]],
            "ozon_live_binding_count": group["ozon_binding_count"],
            "ozon_live_binding_statuses": group["ozon_binding_statuses"],
            "ozon_expected_targets": group["target_count"],
            "wb_status_counts": group["wb_status_counts"],
            "wb_nmids": group["wb_nmids"],
            "deleted_after_marketplace_confirmation": True,
            "deleted_at": group["last_copy_deleted_at"],
            "cleanup_receipt": str(RECEIPT),
        }
        prior[group["source_sha256"]] = row
    main_receipt["source_files"] = list(prior.values())
    main_receipt["total_bytes_reclaimed"] = sum(int(row.get("size_bytes", 0)) for row in main_receipt["source_files"])
    main_receipt["additional_cleanup_receipts"] = list(dict.fromkeys(
        (main_receipt.get("additional_cleanup_receipts") or []) + [str(RECEIPT)]
    ))
    main_receipt["completed_at"] = plan["completed_at"]
    save(MAIN_RECEIPT, main_receipt)

    report = json.loads(MAIN_REPORT.read_text(encoding="utf-8"))
    report["local_source_files_deleted"] = True
    report["local_source_files_deleted_count"] = sum(int(row.get("duplicate_copy_count", len(row.get("duplicate_paths") or [row.get("path")]))) for row in main_receipt["source_files"])
    report["local_source_files_deleted_bytes"] = main_receipt["total_bytes_reclaimed"]
    report["local_source_files_deleted_documents"] = [row.get("number") for row in main_receipt["source_files"]]
    report["local_source_files_cleanup_receipt"] = str(MAIN_RECEIPT)
    report["additional_confirmed_group_cleanup"] = {
        "documents": len(plan["verified_source_groups"]),
        "copies": plan["deleted_copy_count"],
        "bytes": plan["bytes_reclaimed"],
        "receipt": str(RECEIPT),
        "checked_at": plan["completed_at"],
        "retained_groups": plan["retained_groups"],
    }
    save(MAIN_REPORT, report)

    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    safe_numbers = {x["number"] for x in plan["verified_source_groups"]}
    held_by_number = {x["number"]: x for x in plan["retained_groups"]}
    for group in source_manifest.get("groups") or []:
        if group.get("number") in safe_numbers:
            receipt_group = next(x for x in plan["verified_source_groups"] if x["number"] == group["number"])
            group["local_file_cleanup"] = {
                "status": "deleted_after_marketplace_confirmation",
                "receipt": str(RECEIPT),
                "sha256": receipt_group["source_sha256"],
                "copies_deleted": receipt_group["duplicate_copy_count"],
                "bytes_reclaimed": receipt_group["bytes_to_reclaim"],
            }
        elif group.get("number") in held_by_number:
            group["local_file_cleanup"] = {
                "status": "retained",
                "reason": held_by_number[group["number"]]["reason"],
                "details": held_by_number[group["number"]].get("extra_offers", []),
            }
    source_manifest["additional_local_cleanup_receipt"] = str(RECEIPT)
    source_manifest["additional_local_cleanup_completed_at"] = plan["completed_at"]
    save(SOURCE_MANIFEST, source_manifest)

    lines = MAIN_MARKDOWN.read_text(encoding="utf-8").splitlines()
    lines.extend([
        "",
        "## Previously processed cross-brand groups",
        "",
        f"- Fresh Ozon readback at `{plan['ozon_checked_at']}` and complete WB snapshot at `{plan['wb_checked_at']}` confirmed {len(plan['verified_source_groups'])} older source groups across Arlight, Feron, KVT, TDM and IEK. Their exact Ozon targets are approved; WB has the matching document on every existing target card (some remain pending review), and offers without a WB card were left as no-card cases.",
        f"- Deleted {plan['deleted_copy_count']} local copies across {len(plan['verified_source_groups'])} documents and reclaimed {plan['bytes_reclaimed']:,} bytes. Two groups remain local because their source hash is also assigned to extra offers outside the verified target manifest.",
        f"- Detailed evidence and per-file checks: `{RECEIPT.name}`; deletion journal: `{JOURNAL.name}`.",
    ])
    MAIN_MARKDOWN.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": plan["status"],
        "documents": len(plan["verified_source_groups"]),
        "copies_deleted": plan["deleted_copy_count"],
        "bytes_reclaimed": plan["bytes_reclaimed"],
        "retained_groups": plan["retained_groups"],
        "receipt": str(RECEIPT),
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = build_plan()
    if args.execute:
        execute(plan)
    else:
        print(json.dumps({
            "status": plan["status"],
            "summary": plan["summary"],
            "documents": [{"number": x["number"], "copies": x["duplicate_copy_count"],
                           "bytes": x["bytes_to_reclaim"], "wb": x["wb_status_counts"]}
                          for x in plan["verified_source_groups"]],
            "retained_groups": plan["retained_groups"],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
