"""Hold the existing watcher lock while preparing and verifying a direct push."""
import fcntl
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('checksheets_sync', root / 'scripts/checksheets_github_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
ready = Path(sys.argv[1])
sync.STATE_ROOT.mkdir(parents=True, exist_ok=True)
with sync.LOCK_PATH.open("a") as handle:
    print("WAITING_FOR_WATCHER_LOCK", flush=True)
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    print('WATCHER_LOCK_HELD', flush=True)
    deadline = time.monotonic() + 1200
    while not ready.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('Deployment was not released within 20 minutes')
        time.sleep(1)
    # Preserve the previous cloud version, not only the edited local checkout.
    baseline = Path(tempfile.mkdtemp(prefix="apps-script-before-legacy-", dir=root / "test" / "tmp"))
    for name in (".clasp.json", ".claspignore"):
        shutil.copy2(root / name, baseline / name)
    sync.run(sync.clasp_command("pull"), cwd=baseline)
    print("CLOUD_BACKUP=" + str(baseline), flush=True)
    print(json.dumps(sync.push_apps_script(False), ensure_ascii=False), flush=True)
