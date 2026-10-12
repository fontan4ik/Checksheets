"""Deploy the buyout fix without uploading unrelated edits in the shared checkout."""
import importlib.util
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync", root / "scripts/checksheets_github_sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
work = root / "test/tmp/telegram-error-fixes-20261012/verified-retry-update"
baseline = work / "cloud-before"
stage = work / "deploy"
readback = work / "cloud-after"
for directory in (baseline, stage, readback):
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / ".clasp.json", directory / ".clasp.json")
    shutil.copy2(root / ".claspignore", directory / ".claspignore")
tracked = sync.clasp_status()
assert "ozon_stock_results.js" not in tracked
assert "List_UNIT_API__УПД__Ozon.js" in tracked
print("UPLOAD_BOUNDARY_OK", len(tracked), flush=True)
sync.run(sync.clasp_command("pull"), cwd=baseline)
for file in baseline.iterdir():
    if file.is_file():
        shutil.copy2(file, stage / file.name)
name = "List_UNIT_API__УПД__Ozon.js"
assert (baseline / name).exists()
shutil.copy2(root / name, stage / name)
print("CLOUD_BACKUP_SAVED", str(baseline), flush=True)
sync.run(sync.clasp_command("push", "--force"), cwd=stage)
print("PUSH_DONE", flush=True)
sync.run(sync.clasp_command("pull"), cwd=readback)
files = [f.name for f in stage.iterdir() if f.suffix in (".js", ".json") and not f.name.startswith(".")]
mismatches = [name for name in files if not (readback / name).exists() or sync.sha256(stage / name) != sync.sha256(readback / name)]
summary = {"pushed": True, "verified": not mismatches, "fileCount": len(files), "mismatches": mismatches, "changed": [name], "backup": str(baseline)}
(work / "deployment.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps(summary, ensure_ascii=False), flush=True)
assert not mismatches
