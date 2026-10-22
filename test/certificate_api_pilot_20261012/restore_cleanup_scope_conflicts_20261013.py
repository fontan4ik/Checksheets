"""Restore four document groups whose cleanup allowlists were later found to conflict with scope audit."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE_RESULT = BASE / "cleanup_newly_bound_local_certificates_20261012_result.json"
JOURNAL = BASE / "restore_cleanup_scope_conflicts_20261013_journal.jsonl"
RESULT = BASE / "restore_cleanup_scope_conflicts_20261013_result.json"
EXPECTED = {
    "ЕАЭС N RU Д-CN.РА03.В.12843/22",
    "ЕАЭС N RU Д-CN.РА02.В.68803/26",
    "ЕАЭС RU С-CN.АЯ46.В.49875/26",
    "ЕАЭС RU С-CN.АЯ46.В.36710/24",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


if JOURNAL.exists() or RESULT.exists():
    raise RuntimeError("Restore already attempted; inspect the existing journal/result before retrying")
prior = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))
files = [x for x in prior.get("moved", []) if x.get("number") in EXPECTED]
if len(prior.get("moved", [])) != 16 or len(files) != 16 or {x["number"] for x in files} != EXPECTED:
    raise RuntimeError("Prior cleanup result does not exactly match the four reviewed groups")

# Complete preflight before moving any file.
for item in files:
    source, trash = Path(item["source"]), Path(item["trash_path"])
    if (not source.is_absolute() or not trash.is_absolute() or source.exists()
            or not source.parent.is_dir() or not trash.is_file() or trash.is_symlink()
            or trash.stat().st_size != item["size"] or sha(trash) != item["sha256"]):
        raise RuntimeError(f"Restore preflight failed for {source}")

with JOURNAL.open("x", encoding="utf-8") as stream:
    for item in files:
        source, trash = Path(item["source"]), Path(item["trash_path"])
        entry = {"number": item["number"], "source": str(source), "trash_path": str(trash),
                 "sha256": item["sha256"], "size": item["size"]}
        stream.write(json.dumps({**entry, "phase": "prepared", "at": now()}, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        if source.exists() or not trash.is_file() or sha(trash) != item["sha256"]:
            raise RuntimeError(f"File changed after restore preflight: {trash}")
        os.rename(trash, source)
        if (trash.exists() or not source.is_file() or source.stat().st_size != item["size"]
                or sha(source) != item["sha256"]):
            raise RuntimeError(f"Restored file verification failed: {source}")
        stream.write(json.dumps({**entry, "phase": "verified_restored", "at": now()}, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

postcheck = []
for item in files:
    source, trash = Path(item["source"]), Path(item["trash_path"])
    postcheck.append({"number": item["number"], "source": str(source), "trash_path": str(trash),
                      "source_exists": source.is_file(), "trash_absent": not trash.exists(),
                      "source_size": source.stat().st_size if source.is_file() else None,
                      "source_sha256": sha(source) if source.is_file() else None,
                      "expected_sha256": item["sha256"]})
if (len(postcheck) != 16 or any(not x["source_exists"] or not x["trash_absent"]
                                or x["source_size"] != next(i["size"] for i in files if i["source"] == x["source"])
                                or x["source_sha256"] != x["expected_sha256"] for x in postcheck)):
    raise RuntimeError("Post-restore verification did not match all 16 original files")

result = {"restored_at": now(), "reason": "Later source/audit review found unresolved applicability allowlist conflicts; retain originals until resolved.",
          "source_cleanup_result": str(SOURCE_RESULT), "files_restored": len(postcheck),
          "documents": sorted(EXPECTED), "postcheck": postcheck,
          "original_cleanup_trash_directory": prior["trash_directory"]}
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"files_restored": len(postcheck), "documents": sorted(EXPECTED),
                  "all_hashes_verified": all(x["source_sha256"] == x["expected_sha256"] for x in postcheck)},
                 ensure_ascii=False, indent=2))
