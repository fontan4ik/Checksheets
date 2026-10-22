"""Move Feron 02773/24 files to macOS Trash only after fresh Ozon/WB proof."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
FERON_ROOT = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
SOURCE = json.loads((BASE / "feron_02773_live_verification.json").read_text(encoding="utf-8"))
OZON = json.loads((BASE / "feron_02773_ozon_status_latest_20261013.json").read_text(encoding="utf-8"))
WB = json.loads((BASE / "feron_02773_wb_targets_verification_20261013.json").read_text(encoding="utf-8"))
INVENTORY = json.loads((BASE / "feron_02773_local_hash_inventory_20261013.json").read_text(encoding="utf-8"))

PLAN_PATH = BASE / "feron_02773_strict_cleanup_plan_20261013.json"
JOURNAL_PATH = BASE / "feron_02773_strict_cleanup_journal_20261013.jsonl"
RESULT_PATH = BASE / "feron_02773_strict_cleanup_result_20261013.json"

def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)

def age_minutes(value: str) -> float:
    return (dt.datetime.now(dt.timezone.utc) - parse_time(value)).total_seconds() / 60

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

if SOURCE["certificate"]["fsa_record_id"] != 3476514 or SOURCE["certificate"]["status"] != "Действует":
    raise RuntimeError("The reviewed FSA certificate identity/status proof is missing")
if SOURCE["certificate"]["expiry_date"] <= dt.date.today().isoformat():
    raise RuntimeError("The source certificate has expired")
if age_minutes(OZON["checked_at_utc"]) > 30 or age_minutes(WB["checked_at_utc"]) > 30:
    raise RuntimeError("One of the marketplace readbacks is older than 30 minutes")
if age_minutes(INVENTORY["checked_at_local"]) > 30:
    raise RuntimeError("The local SHA inventory is older than 30 minutes")
if not (OZON.get("certificate", {}).get("status") == "approved"
        and OZON.get("target_count") == 159 and OZON.get("binding_count") == 159
        and OZON.get("full_exact_set_bound") and OZON.get("all_bindings_approved")
        and OZON.get("all_bindings_final") and not OZON.get("missing_skus")
        and not OZON.get("unexpected_skus") and not OZON.get("product_id_mismatches")):
    raise RuntimeError("Current Ozon proof does not confirm exactly 159 approved bindings")
if not (WB.get("source_target_offer_count") == 159
        and WB.get("source_target_article_count") == 133
        and WB.get("baseline_exact_card_count") == 135
        and WB.get("current_exact_card_count") == 135
        and WB.get("all_current_exact_cards_finally_valid")
        and WB.get("all_133_target_articles_have_current_valid_wb_card")
        and WB.get("all_target_offers_resolved_by_exact_card_or_same_article_card")
        and WB.get("wb_rows_all_valid") and not WB.get("problems")
        and not WB.get("uncovered_target_articles")):
    raise RuntimeError("Current targeted WB proof does not confirm all applicable articles")

source_path = Path(SOURCE["source"]["path"]).resolve()
expected_hash = SOURCE["source"]["sha256"]
expected_size = int(SOURCE["source"]["size_bytes"])
workbook_copies = {str(Path(row["local_copy"]).resolve()) for row in SOURCE["workbook"]["targets"]}
matches = {str(Path(path).resolve()) for path in INVENTORY["matching_files"]}
expected_files = workbook_copies | {str(source_path)}
if (len(workbook_copies) != 159 or len(matches) != 160 or matches != expected_files
        or INVENTORY.get("expected_workbook_copies_missing_or_changed")
        or INVENTORY.get("matching_files_outside_workbook_copy_list")):
    raise RuntimeError("The complete local-file allowlist differs from the verified source matrix")
if len({str(row["offer_id"]) for row in SOURCE["workbook"]["targets"]}) != 159:
    raise RuntimeError("The source workbook offer identity set is duplicated or incomplete")

files = []
for value in sorted(matches):
    path = Path(value)
    if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
            or not path.is_relative_to(FERON_ROOT) or not path.is_file()
            or path.stat().st_size != expected_size or sha(path) != expected_hash):
        raise RuntimeError(f"Local file failed immediate preflight: {path}")
    files.append({"path": str(path), "relative_path": str(path.relative_to(FERON_ROOT)),
                  "kind": "original" if path == source_path else "offer_copy",
                  "size_bytes": expected_size, "sha256": expected_hash})

plan = {
    "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "certificate": {"number": SOURCE["certificate"]["canonical_number"],
                    "fsa_record_id": SOURCE["certificate"]["fsa_record_id"],
                    "status_last_verified": SOURCE["certificate"]["status"],
                    "issue_date": SOURCE["certificate"]["issue_date"],
                    "expiry_date": SOURCE["certificate"]["expiry_date"],
                    "source_sha256": expected_hash},
    "ozon_proof": {"checked_at_utc": OZON["checked_at_utc"],
                    "certificate_id": OZON["certificate"]["certificate_id"],
                    "approved_target_pairs": OZON["binding_count"],
                    "status_counts": OZON["binding_status_counts"]},
    "wb_proof": {"checked_at_utc": WB["checked_at_utc"],
                  "exact_valid_cards": WB["current_exact_card_count"],
                  "covered_articles": WB["articles_covered_by_current_valid_exact_cards"],
                  "no_exact_offer_codes_resolved_by_same_article": len(WB["offers_without_exact_wb_vendorCode"])},
    "all_local_matches": len(files),
    "offer_copies": len(workbook_copies),
    "files": files,
    "recovery": "Files are moved to a dated directory inside macOS Trash; journal maps every original path to its verified Trash path.",
}
if PLAN_PATH.exists() or JOURNAL_PATH.exists() or RESULT_PATH.exists():
    raise RuntimeError("Cleanup artifacts already exist; reconcile before repeating")
PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

trash_root = Path.home() / ".Trash" / ("Feron_02773_подтверждено_Ozon_WB_" +
                                        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
trash_root.mkdir(parents=True, exist_ok=False)
moved: list[tuple[Path, Path, dict]] = []
try:
    with JOURNAL_PATH.open("x", encoding="utf-8") as journal:
        for item in files:
            source = Path(item["path"])
            destination = trash_root / "Документы_качества_Feron" / item["relative_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (not source.is_file() or source.is_symlink() or source.resolve() != source
                    or source.stat().st_size != expected_size or sha(source) != expected_hash
                    or destination.exists()):
                raise RuntimeError(f"File changed immediately before move: {source}")
            event = {"source": str(source), "trash_path": str(destination),
                     "sha256": expected_hash, "size_bytes": expected_size}
            journal.write(json.dumps({**event, "phase": "prepared",
                                      "at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            os.rename(source, destination)
            if source.exists() or destination.stat().st_size != expected_size or sha(destination) != expected_hash:
                raise RuntimeError(f"Moved file failed destination verification: {destination}")
            moved.append((source, destination, event))
            journal.write(json.dumps({**event, "phase": "moved_and_verified",
                                      "at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
except Exception:
    rollback_errors = []
    for source, destination, event in reversed(moved):
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            if source.exists() or not destination.is_file() or sha(destination) != expected_hash:
                raise RuntimeError("Rollback source/destination check failed")
            os.rename(destination, source)
            if not source.is_file() or sha(source) != expected_hash:
                raise RuntimeError("Rollback verification failed")
        except Exception as exc:
            rollback_errors.append({"source": str(source), "trash_path": str(destination),
                                    "error": type(exc).__name__})
    if rollback_errors:
        (BASE / "feron_02773_strict_cleanup_rollback_errors_20261013.json").write_text(
            json.dumps(rollback_errors, ensure_ascii=False, indent=2), encoding="utf-8")
    raise

postcheck = [{"source": item["path"], "trash_path": str(trash_root / "Документы_качества_Feron" / item["relative_path"]),
             "source_absent": not Path(item["path"]).exists(),
             "trash_sha256": sha(trash_root / "Документы_качества_Feron" / item["relative_path"]),
             "trash_size_bytes": (trash_root / "Документы_качества_Feron" / item["relative_path"]).stat().st_size}
            for item in files]
if (len(postcheck) != 160 or any(not x["source_absent"] or x["trash_sha256"] != expected_hash
                                 or x["trash_size_bytes"] != expected_size for x in postcheck)):
    raise RuntimeError("Final local cleanup verification failed; check the write-ahead journal")
result = {"completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
          "trash_directory": str(trash_root), "number": SOURCE["certificate"]["canonical_number"],
          "verified_moved_files": len(postcheck), "offer_copies": 159, "originals": 1,
          "source_paths_absent": all(x["source_absent"] for x in postcheck),
          "all_trash_hashes_verified": all(x["trash_sha256"] == expected_hash for x in postcheck),
          "ozon_approved_pairs": OZON["binding_count"], "wb_exact_valid_cards": WB["current_exact_card_count"],
          "wb_target_articles_covered": WB["articles_covered_by_current_valid_exact_cards"],
          "files": postcheck}
RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False, indent=2))
