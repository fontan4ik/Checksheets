"""Recoverably archive Feron 53483/22 files only after exact cross-platform approval."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
FERON = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
AUDIT = BASE / "feron_53483_crossplatform_audit_20261013.json"
LIVE = BASE / "feron_53483_crossplatform_final_recheck_20261013.json"
PLAN = BASE / "feron_53483_cleanup_plan_20261013.json"
RESULT = BASE / "feron_53483_cleanup_result_20261013.json"
JOURNAL = BASE / "feron_53483_cleanup_journal_20261013.jsonl"
SHA256 = "391d9f3d7794628d268bbba5c60c4e09a238540c84a15ace1e6578e960408db7"
FSA_URL = "https://pub.fsa.gov.ru/rds/declaration/view/17025556/product"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_plan() -> dict:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    checked = dt.datetime.fromisoformat(live["checked_at_utc"].replace("Z", "+00:00"))
    age_minutes = (dt.datetime.now(dt.timezone.utc) - checked.astimezone(dt.timezone.utc)).total_seconds() / 60
    if age_minutes > 30:
        raise RuntimeError("Marketplace readback is older than 30 minutes")
    if not live.get("read_only") or live.get("number") != "ЕАЭС N RU Д-CN.РА06.В.53483/22":
        raise RuntimeError("Fresh exact-number marketplace proof is missing")
    if live.get("expected_target_count") != 40 or not live.get("ozon_all_exact_pairs_approved"):
        raise RuntimeError("Ozon does not have all 40 exact approved target pairs")
    if live.get("ozon_record", {}).get("status_code") != "approved":
        raise RuntimeError("Ozon record is not finally approved")
    if live.get("ozon_record", {}).get("issue_date", "")[:10] != "2022-09-15" or live.get("ozon_record", {}).get("expire_date", "")[:10] != "2027-09-14":
        raise RuntimeError("Ozon dates differ from the official record")
    if not live.get("wb_all_exact_rows_finally_valid") or len(live.get("wb_cards") or []) != 40:
        raise RuntimeError("WB does not have all 40 final valid exact-card rows")
    if audit.get("ozon_scope_eligible_targets") is None or len(audit["ozon_scope_eligible_targets"]) != 40:
        raise RuntimeError("The official-scope target set no longer has exactly 40 offers")
    if len(audit.get("ozon_scope_exclusions") or []) != 63:
        raise RuntimeError("The out-of-scope set changed; rebuild the cleanup allowlist")
    file_audit = audit.get("file_audit") or {}
    if (file_audit.get("source_sha256") != SHA256 or file_audit.get("source_bytes") != 775936
            or file_audit.get("copy_count") != 103 or not file_audit.get("all_copies_exist_and_match")):
        raise RuntimeError("The prior source-file audit is incomplete")

    source = Path(file_audit["source_path"])
    files = [{"path": str(source), "relative_path": str(source.relative_to(FERON)), "kind": "original"}]
    seen = {source.resolve()}
    for copy in file_audit["copies"]:
        path = Path(copy["path"])
        if not copy.get("exists") or copy.get("sha256") != SHA256 or path.resolve() in seen:
            raise RuntimeError("A workbook copy is missing, changed, or duplicated")
        seen.add(path.resolve())
        files.append({"path": str(path), "relative_path": str(path.relative_to(FERON)),
                      "kind": "offer_copy", "offer_id": copy["offer_id"]})
    if len(files) != 104 or len(seen) != 104:
        raise RuntimeError("Expected exactly one original and 103 offer copies")

    # Search the checked project/quality roots by size and hash so no local duplicate is omitted.
    roots = [FERON.parent, Path("/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/output_to_user/certificates"),
             Path("/Users/vladimirgrebennikov/Code/Checksheets_Project/Checksheets/test/certificate_api_pilot_20261012")]
    discovered = set()
    extensions = {".jpg", ".jpeg", ".png", ".pdf"}
    for root in roots:
        if not root.exists():
            continue
        for base, dirs, names in os.walk(root):
            dirs[:] = [name for name in dirs if name not in {".git", "node_modules", ".venv"}]
            for name in names:
                path = Path(base) / name
                try:
                    if path.suffix.lower() not in extensions or path.is_symlink() or path.stat().st_size != 775936:
                        continue
                    if sha(path) == SHA256:
                        discovered.add(path.resolve())
                except OSError:
                    continue
    if discovered != seen:
        raise RuntimeError(f"Local exact-hash file set differs: expected={len(seen)}, discovered={len(discovered)}")

    for file in files:
        path = Path(file["path"])
        if (path.is_symlink() or path.resolve() != path or not path.is_file()
                or path.stat().st_size != 775936 or sha(path) != SHA256):
            raise RuntimeError(f"File changed before cleanup planning: {path}")

    return {
        "prepared_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "number": live["number"], "source_sha256": SHA256, "source_bytes_each": 775936,
        "official_fsa": {"url": FSA_URL, "checked_in_registry_ui": True, "status": "Действует",
                         "registration_date": "2022-09-15", "expiry_date": "2027-09-14",
                         "technical_regulation": "ТР ЕАЭС 037/2016", "series": "Feron LB",
                         "tnved_codes": ["8504408300", "8504318007"]},
        "scope": {"workbook_offers": 103, "current_ozon_scope_eligible_offers": 40,
                  "out_of_scope_offers": 63, "out_of_scope_reason": "ТН ВЭД Ozon не входит в область записи ФСА; не считаются целями этой декларации."},
        "marketplace_readback": {"checked_at_utc": live["checked_at_utc"], "age_minutes_at_plan": round(age_minutes, 2),
                                 "ozon_certificate_id": live["certificate_id"], "ozon_record_status": live["ozon_record"]["status_code"],
                                 "ozon_exact_approved_pairs": live["expected_target_count"],
                                 "wb_exact_final_valid_rows": len(live["wb_cards"]),
                                 "wb_nmids": [row["cards"][0]["nmID"] for row in live["wb_cards"]]},
        "source_paths": files,
        "summary": {"documents": 1, "originals_and_copies": len(files),
                    "total_bytes": len(files) * 775936, "ozon_pairs": 40, "wb_cards": 40,
                    "all_source_hashes_verified": True, "all_matching_local_files_found": True},
        "restore_note": "Move is recoverable. Restore each file from trash_path to source_path in the journal; verify SHA-256 before and after.",
    }


def execute(plan: dict) -> dict:
    if JOURNAL.exists() or RESULT.exists():
        raise RuntimeError("Cleanup already has a journal/result; reconcile it before retrying")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trash = Path.home() / ".Trash" / f"Подтверждены_на_Ozon_WB_53483_20261013_{stamp}"
    trash.mkdir(parents=True, exist_ok=False)
    moved = []
    with JOURNAL.open("x", encoding="utf-8") as journal:
        for item in plan["source_paths"]:
            source = Path(item["path"])
            dest = trash / item["relative_path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            row = {"source_path": str(source), "trash_path": str(dest), "offer_id": item.get("offer_id"),
                   "kind": item["kind"], "sha256": SHA256, "size": 775936}
            if source.is_symlink() or source.resolve() != source or not source.is_file() or dest.exists() or sha(source) != SHA256:
                raise RuntimeError(f"Refusing changed/conflicting local file: {source}")
            journal.write(json.dumps({**row, "phase": "prepared", "at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
            journal.flush(); os.fsync(journal.fileno())
            os.rename(source, dest)
            if source.exists() or not dest.is_file() or dest.stat().st_size != 775936 or sha(dest) != SHA256:
                raise RuntimeError(f"Move verification failed; see journal: {dest}")
            journal.write(json.dumps({**row, "phase": "verified_moved", "at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
            journal.flush(); os.fsync(journal.fileno())
            moved.append(row)
    result = {"completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "trash_directory": str(trash),
              "verified_moved_files": len(moved), "summary": plan["summary"], "moved": moved}
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = build_plan()
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"plan": str(PLAN), **plan["summary"]}, ensure_ascii=False))
    if args.execute:
        print(json.dumps(execute(plan), ensure_ascii=False))


if __name__ == "__main__":
    main()
