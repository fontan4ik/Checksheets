"""Find every Feron local file whose bytes match certificate 02773/24."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
SOURCE = json.loads((BASE / "feron_02773_live_verification.json").read_text(encoding="utf-8"))
root = Path("/Users/vladimirgrebennikov/Downloads/Новая папка/Документы_качества_Feron")
source_path = Path(SOURCE["source"]["path"])
expected_hash = SOURCE["source"]["sha256"]
expected_size = int(SOURCE["source"]["size_bytes"])
expected_copies = {str(Path(x["local_copy"]).resolve()) for x in SOURCE["workbook"]["targets"]}
if not source_path.is_file() or source_path.stat().st_size != expected_size:
    raise RuntimeError("The verified original PDF is missing or changed")

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

matches = []
same_size = 0
symlinks = []
for path in root.rglob("*"):
    if path.is_symlink():
        symlinks.append(str(path))
        continue
    if not path.is_file() or path.stat().st_size != expected_size:
        continue
    same_size += 1
    if sha(path) == expected_hash:
        matches.append(str(path.resolve()))
if sha(source_path) != expected_hash:
    raise RuntimeError("The verified original PDF SHA-256 changed")
matched = set(matches)
result = {
    "checked_at_local": __import__("datetime").datetime.now().astimezone().isoformat(),
    "root": str(root),
    "expected_sha256": expected_hash,
    "expected_size_bytes": expected_size,
    "same_size_files_hashed": same_size,
    "matching_file_count": len(matches),
    "expected_workbook_copy_count": len(expected_copies),
    "expected_workbook_copies_missing_or_changed": sorted(expected_copies - matched),
    "matching_files_outside_workbook_copy_list": sorted(matched - expected_copies - {str(source_path.resolve())}),
    "matching_files": sorted(matches),
    "symlink_paths_skipped": symlinks,
}
out = BASE / "feron_02773_local_hash_inventory_20261013.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "matching_files" and k != "symlink_paths_skipped"},
                 ensure_ascii=False, indent=2))
