#!/usr/bin/env python3
"""Autonomous Checksheets sync: local workspace <-> GitHub -> Apps Script.

The local Mac is the deployment worker. GitHub main is the collaboration source
of truth. The worker polls origin, commits stable local changes, reconciles main,
and uploads Apps Script files with clasp only when the Git history contains an
Apps Script change.

No credentials are read or printed by this script. Git and clasp use their
already configured credential stores.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRANCH = os.environ.get("CHECKSHEETS_SYNC_BRANCH", "main")
HOME = Path(os.environ.get("HOME", str(Path.home())))
STATE_ROOT = Path(
    os.environ.get(
        "CHECKSHEETS_SYNC_STATE_DIR",
        str(HOME / "Library" / "Application Support" / "Voltmir" / "ChecksheetsSync"),
    )
)
STATE_PATH = STATE_ROOT / "state.json"
LOCK_PATH = STATE_ROOT / "sync.lock"
BACKUP_ROOT = STATE_ROOT / "backups"
LOG_ROOT = Path(
    os.environ.get(
        "CHECKSHEETS_SYNC_LOG_DIR",
        str(HOME / "Library" / "Logs" / "Voltmir"),
    )
)
LOG_PATH = LOG_ROOT / "checksheets-github-sync.log"
SETTLE_SECONDS = int(os.environ.get("CHECKSHEETS_SYNC_SETTLE_SECONDS", "20"))
COMMAND_TIMEOUT = int(os.environ.get("CHECKSHEETS_SYNC_COMMAND_TIMEOUT", "300"))
NPM = os.environ.get("CHECKSHEETS_SYNC_NPM", str(HOME / ".local" / "bin" / "npm"))

SENSITIVE_NAMES = (
    ".env",
    ".env.",
    "service-account",
    "credentials",
    "google_token.json",
    "google_client_secret.json",
    "nomadic-bedrock-485314-b0-d7624dedd83c.json",
)
RUNTIME_PARTS = (
    ".brv/",
    ".venv",
    "__pycache__/",
    "node_modules/",
    "test/node_modules/",
    "logs/",
    "test/tmp/",
    "tests/tmp/",
    "scratch/",
    "output_to_user/",
)


def configure_logging() -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


log = logging.getLogger("checksheets-sync")


def run(
    command: Sequence[str],
    *,
    cwd: Path = PROJECT_ROOT,
    timeout: int = COMMAND_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("HOME", str(HOME))
    env.setdefault("NPM_CONFIG_UPDATE_NOTIFIER", "false")
    env.setdefault("NPM_CONFIG_FUND", "false")
    env.setdefault("NPM_CONFIG_AUDIT", "false")
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        raise RuntimeError(
            f"Команда завершилась с кодом {result.returncode}: "
            f"{' '.join(command[:3])}; {' | '.join(detail)}"
        )
    return result


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(("git", *args), check=check)


def git_status() -> str:
    return git("status", "--porcelain=v1").stdout


def git_sha(ref: str = "HEAD") -> str:
    return git("rev-parse", ref).stdout.strip()


def git_is_ancestor(older: str, newer: str) -> bool:
    return git("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0


def git_changed_paths(base: str | None, head: str) -> list[str] | None:
    if not base:
        return None
    if base == head:
        return []
    if not git_is_ancestor(base, head):
        return None
    result = git(
        "-c",
        "core.quotepath=false",
        "diff",
        "--name-only",
        "-z",
        f"{base}..{head}",
    )
    return [path for path in result.stdout.split("\x00") if path]


def is_sensitive_path(path: str) -> bool:
    lowered = path.lower()
    name = Path(path).name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or any(marker in lowered for marker in SENSITIVE_NAMES[2:])
        or name.endswith((".pem", ".key"))
    )


def is_runtime_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(
        normalized == part.rstrip("/") or normalized.startswith(part)
        for part in RUNTIME_PARTS
    ) or normalized.endswith(".pyc")


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(payload: dict) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def status_paths() -> list[str]:
    paths: list[str] = []
    for line in git_status().splitlines():
        if not line:
            continue
        value = line[3:] if len(line) > 3 else ""
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(value.strip('"'))
    return paths


def stash_runtime_changes() -> str | None:
    paths = [path for path in status_paths() if is_runtime_path(path)]
    non_runtime = [path for path in status_paths() if not is_runtime_path(path)]
    if non_runtime:
        raise RuntimeError(
            "После commit остались незакоммиченные source-файлы: " + ", ".join(non_runtime[:10])
        )
    if not paths:
        return None
    result = git("stash", "push", "-m", "checksheets-sync-runtime", "--", *paths, check=False)
    if result.returncode != 0:
        raise RuntimeError("Не удалось временно убрать runtime-изменения в stash")
    stash_ref = git("stash", "list", "-1", "--format=%gd", check=False).stdout.strip() or None
    log.info("Runtime-изменения временно убраны в stash на время git sync")
    return stash_ref


def restore_runtime_changes(stash_ref: str | None) -> None:
    if not stash_ref:
        return
    result = git("stash", "pop", stash_ref, check=False)
    if result.returncode != 0:
        log.error("Runtime stash не удалось автоматически восстановить; он сохранён в git stash")
    else:
        log.info("Runtime-изменения восстановлены")


def fetch_origin() -> None:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            git("fetch", "origin", BRANCH, "--quiet")
            return
        except Exception as exc:  # pragma: no cover - network-dependent branch
            last_error = exc
            log.warning("git fetch: попытка %s/3 неуспешна", attempt)
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Не удалось получить origin/{BRANCH}: {last_error}")


def commit_stable_local_changes(dry_run: bool) -> str | None:
    before = git_status()
    if not before:
        return None
    if all(is_runtime_path(path) for path in status_paths()):
        log.info("Изменены только runtime-файлы; commit не требуется")
        return None

    log.info("Найдены локальные изменения; жду %s секунд для завершения записи", SETTLE_SECONDS)
    if SETTLE_SECONDS:
        time.sleep(SETTLE_SECONDS)
    after = git_status()
    if after != before:
        log.info("Файлы ещё меняются; этот цикл пропущен")
        return None

    if dry_run:
        log.info("dry-run: были бы добавлены все безопасные изменения локалки")
        return None

    git("add", "-A")
    staged = [line.strip() for line in git("diff", "--cached", "--name-only").stdout.splitlines() if line.strip()]
    deletions = {
        line.strip()
        for line in git("diff", "--cached", "--diff-filter=D", "--name-only").stdout.splitlines()
        if line.strip()
    }
    blocked: list[str] = []
    for path in staged:
        if is_runtime_path(path):
            git("reset", "--", path)
            continue
        if is_sensitive_path(path) and path not in deletions and Path(path).exists():
            git("reset", "--", path)
            blocked.append(path)
    if blocked:
        log.warning("Секретные локальные файлы не добавлены в Git: %s", ", ".join(blocked))

    staged = [line.strip() for line in git("diff", "--cached", "--name-only").stdout.splitlines() if line.strip()]
    if not staged:
        return None

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    git("commit", "-m", f"chore: sync local Checksheets changes ({timestamp})")
    commit = git_sha()
    log.info("Создан локальный commit %s", commit[:12])
    return commit


def reconcile_git(dry_run: bool) -> tuple[str, str]:
    fetch_origin()
    commit_stable_local_changes(dry_run)
    if dry_run:
        return git_sha(), git_sha(f"origin/{BRANCH}")

    runtime_stash = stash_runtime_changes()
    try:
        fetch_origin()
        local = git_sha()
        remote = git_sha(f"origin/{BRANCH}")
        if local == remote:
            return local, remote

        if git_is_ancestor(local, remote):
            log.info("GitHub впереди; fast-forward локальной ветки до %s", remote[:12])
            git("merge", "--ff-only", f"origin/{BRANCH}")
        elif git_is_ancestor(remote, local):
            log.info("Локалка впереди; отправляю commit %s в GitHub", local[:12])
            git("push", "origin", f"HEAD:{BRANCH}")
        else:
            log.warning("Ветки разошлись; выполняю безопасный rebase на origin/%s", BRANCH)
            try:
                git("rebase", f"origin/{BRANCH}")
                git("push", "origin", f"HEAD:{BRANCH}")
            except Exception:
                git("rebase", "--abort", check=False)
                raise RuntimeError(
                    "Ветки GitHub и локалки разошлись, автоматический rebase остановлен. "
                    "Нужна ручная проверка конфликта."
                )

        local = git_sha()
        remote = git_sha(f"origin/{BRANCH}")
        if local != remote:
            raise RuntimeError("После git-синхронизации локальный HEAD и origin/main не совпали")
        return local, remote
    finally:
        restore_runtime_changes(runtime_stash)


def read_claspignore() -> list[str]:
    path = PROJECT_ROOT / ".claspignore"
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def clasp_ignored(path: str) -> bool:
    ignored = False
    for pattern in read_claspignore():
        negated = pattern.startswith("!")
        pattern = pattern[1:] if negated else pattern
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern):
            ignored = not negated
    return ignored


def apps_script_change(paths: Iterable[str] | None) -> bool:
    if paths is None:
        return True
    for path in paths:
        if path in {".claspignore", "appsscript.json"}:
            return True
        if path.endswith(".js") and not clasp_ignored(path):
            return True
    return False


def clasp_command(*args: str) -> tuple[str, ...]:
    npm = NPM if Path(NPM).exists() else "npm"
    return (
        npm,
        "exec",
        "--offline",
        "--yes",
        "--package=@google/clasp",
        "--",
        "clasp",
        *args,
    )


def clasp_status() -> list[str]:
    result = run(clasp_command("status"))
    tracked: list[str] = []
    active = False
    for line in result.stdout.splitlines():
        if "Tracked files:" in line:
            active = True
            continue
        if "Untracked files:" in line:
            active = False
        if active and "└─ " in line:
            tracked.append(line.split("└─ ", 1)[1].strip())
    return tracked


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_apps_script(timestamp: str) -> Path:
    destination = BACKUP_ROOT / timestamp
    destination.mkdir(parents=True, exist_ok=True)
    for path in PROJECT_ROOT.glob("*.js"):
        shutil.copy2(path, destination / path.name)
    for name in ("appsscript.json", ".clasp.json", ".claspignore"):
        path = PROJECT_ROOT / name
        if path.exists():
            shutil.copy2(path, destination / name)
    return destination


def verify_cloud_against_local(tracked: list[str]) -> tuple[int, list[str]]:
    with tempfile.TemporaryDirectory(prefix="checksheets-clasp-verify-") as temporary:
        temp_root = Path(temporary)
        shutil.copy2(PROJECT_ROOT / ".clasp.json", temp_root / ".clasp.json")
        if (PROJECT_ROOT / ".claspignore").exists():
            shutil.copy2(PROJECT_ROOT / ".claspignore", temp_root / ".claspignore")
        run(clasp_command("pull"), cwd=temp_root)
        mismatches: list[str] = []
        for relative in tracked:
            local = PROJECT_ROOT / relative
            cloud = temp_root / relative
            if not local.exists() or not cloud.exists() or sha256(local) != sha256(cloud):
                mismatches.append(relative)
        return len(tracked), mismatches


def push_apps_script(dry_run: bool) -> dict:
    if dry_run:
        log.info("dry-run: был бы выполнен clasp push --force")
        return {"pushed": False, "verified": False, "file_count": 0}

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_apps_script(timestamp)
    log.info("Перед Apps Script push создан backup: %s", backup)
    tracked_before = clasp_status()
    if not tracked_before:
        raise RuntimeError("clasp status не вернул ни одного tracked Apps Script-файла")
    run(clasp_command("push", "--force"))
    tracked_after = clasp_status()
    count, mismatches = verify_cloud_against_local(tracked_after)
    if mismatches:
        raise RuntimeError("Apps Script read-back не совпал: " + ", ".join(mismatches[:10]))
    log.info("Apps Script push подтверждён read-back: %s файлов", count)
    return {"pushed": True, "verified": True, "file_count": count, "backup": str(backup)}


@contextlib.contextmanager
def exclusive_lock():
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Другой Checksheets sync уже выполняется")
        yield


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="выполнить один цикл; используется launchd")
    parser.add_argument("--dry-run", action="store_true", help="не коммитить, не push и не изменять Apps Script")
    args = parser.parse_args()
    configure_logging()

    try:
        with exclusive_lock():
            state = read_state()
            local, remote = reconcile_git(args.dry_run)
            if args.dry_run:
                log.info("dry-run завершён: local=%s origin=%s", local[:12], remote[:12])
                return 0

            changed = git_changed_paths(before_processed, local)
            apps_script_synced_sha = state.get("apps_script_synced_sha")
            apps_script_changed = git_changed_paths(apps_script_synced_sha, local)
            should_push = apps_script_synced_sha is None or apps_script_change(apps_script_changed)
            result = {"pushed": False, "verified": False, "file_count": 0}
            if should_push:
                log.info("Есть Apps Script-изменения; запускаю clasp push")
                result = push_apps_script(False)
            else:
                log.info("Apps Script-файлы не менялись; clasp push не требуется")

            if result["pushed"]:
                apps_script_synced_sha = local
            write_state(
                {
                    "last_synced_sha": local,
                    "apps_script_synced_sha": apps_script_synced_sha,
                    "branch": BRANCH,
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "apps_script": result if result["pushed"] else state.get("apps_script", result),
                    "last_cycle_apps_script": result,
                }
            )
            log.info("Цикл завершён: GitHub=%s, Apps Script push=%s", local[:12], result["pushed"])
        return 0
    except Exception as exc:
        log.error("Синхронизация остановлена: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
