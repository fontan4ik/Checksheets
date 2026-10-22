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
import shlex
import shutil
import stat
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
BACKUP_KEEP_ALL_DAYS = 30
BACKUP_KEEP_DAILY_DAYS = 90
STALE_INDEX_LOCK_SECONDS = max(3600, int(os.environ.get("CHECKSHEETS_SYNC_STALE_INDEX_LOCK_SECONDS", "3600")))
MAX_SOURCE_FILE_BYTES = 50 * 1024 * 1024
_exclusive_lock_held = False

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
    "test/runtime/",
    "tests/runtime/",
    "scratch/",
    "tmp/",
    ".runtime/",
    "outputs/",
    "output_to_user/",
    "graphify-out/cache/",
)
GENERATED_TEST_SUFFIXES = {
    ".json", ".jsonl", ".ndjson", ".gz", ".zip", ".pdf", ".png", ".jpg",
    ".jpeg", ".webp", ".gif", ".xlsx", ".xls", ".csv", ".tsv", ".log",
    ".err", ".out", ".txt", ".sqlite", ".db", ".bin", ".pkl", ".pickle",
    ".parquet", ".xml",
}
# Existing regression fixtures live beside their tests rather than in fixtures/.
TEST_SOURCE_DATA_FILES = {
    "test/package.json", "test/package-lock.json",
    "test/obor_canonical_formulas_fixture.json",
    "test/new_rs_cable_units_20261020.json",
}


class SyncDeferred(Exception):
    """The workspace is still being edited; retry on the next polling cycle."""


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


def _git_process_can_write(command: str) -> bool:
    """Unknown Git subcommands/aliases are writers; ordinary reads are not."""
    try:
        args = shlex.split(command)[1:]
    except ValueError:
        return True
    options_with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
    while args:
        value = args.pop(0)
        if value in options_with_value:
            if not args:
                return True
            args.pop(0)
        elif value.startswith("-"):
            continue
        else:
            return value not in {
                "status", "diff", "show", "log", "rev-parse", "ls-files", "ls-tree",
                "cat-file", "for-each-ref", "check-ignore", "check-attr", "merge-base",
                "name-rev", "describe", "grep", "version", "help",
            }
    return False


def git_writer_active() -> bool:
    """Fail closed if process inspection is unavailable or a Git writer exists.

    Checking all Git writers is deliberately conservative: a client may specify
    another cwd via -C or GIT_DIR, and ps cannot reliably expose its environment.
    """
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,comm=,args="], text=True, errors="replace", capture_output=True,
            timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if result.returncode:
        return True
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and Path(parts[1]).name == "git" and _git_process_can_write(parts[2]):
            return True
    return False


def index_lock_has_holder(path: Path, *, ignore_pid: int | None = None) -> bool:
    """No lsof permission/tool must never be interpreted as an unused lock."""
    binary = shutil.which("lsof")
    if not binary:
        return True
    try:
        result = subprocess.run(
            [binary, "-t", str(path)], text=True, errors="replace", capture_output=True,
            timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if result.stderr.strip():
        return True
    if result.returncode == 1 and not result.stdout.strip():
        return False
    if result.returncode == 0:
        holders = result.stdout.split()
        return not holders or any(not pid.isdigit() or int(pid) != ignore_pid for pid in holders)
    return True


def _lock_identity(value: os.stat_result) -> tuple:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def recover_stale_git_index_lock() -> bool:
    """Back up and remove only an old, empty, unowned, unchanged index.lock.

    Called under the deployment flock before a normal cycle. Nonempty locks may
    contain a recoverable index, so they always require manual investigation.
    The descriptor and repeated identity checks reject lock replacement/updates
    observed during recovery; no Git ref or working-tree data is changed.
    """
    if not _exclusive_lock_held:
        raise RuntimeError("Stale index lock recovery requires the Checksheets sync lock")
    result = run(("git", "rev-parse", "--git-path", "index.lock"), cwd=PROJECT_ROOT, check=False)
    if result.returncode:
        return False
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        before = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(before.st_mode) or before.st_size
            or time.time() - max(before.st_mtime, before.st_ctime) < STALE_INDEX_LOCK_SECONDS):
        return False
    if index_lock_has_holder(path) or git_writer_active():
        return False
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return False
    with os.fdopen(descriptor, "rb") as source:
        if _lock_identity(os.fstat(source.fileno())) != _lock_identity(before):
            return False
        backup_dir = BACKUP_ROOT / "git-index-locks"
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_fd, backup_name = tempfile.mkstemp(prefix="index-", suffix=".lock", dir=backup_dir)
        with os.fdopen(backup_fd, "wb") as destination:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        if index_lock_has_holder(path, ignore_pid=os.getpid()) or git_writer_active():
            return False
        try:
            unchanged = _lock_identity(path.lstat()) == _lock_identity(before)
        except FileNotFoundError:
            return False
        if not unchanged or _lock_identity(os.fstat(source.fileno())) != _lock_identity(before):
            return False
        path.unlink()
    log.warning("Убрана устаревшая пустая Git index.lock; резервная копия: %s", backup_name)
    return True


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
    # The editor and other Git clients do not share our deployment flock.
    # Leave their lock alone and retry briefly; contention is a deferred cycle.
    for attempt in range(3):
        result = run(("git", *args), check=False)
        detail = result.stderr or result.stdout
        locked = result.returncode != 0 and (
            "Another git process seems to be running" in detail
            or (".lock" in detail and "File exists" in detail)
        )
        if locked:
            if attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise SyncDeferred("Git занят другим процессом; повтор в следующем цикле")
        if check and result.returncode != 0:
            lines = detail.strip().splitlines()[-5:]
            raise RuntimeError(
                f"Команда завершилась с кодом {result.returncode}: "
                f"git {' '.join(args[:2])}; {' | '.join(lines)}"
            )
        return result


def git_status() -> str:
    # Nested app worktrees are maintained independently. Their dirty files are
    # not root source edits; a changed gitlink commit is still reported.
    return git("status", "--porcelain=v1", "--ignore-submodules=dirty", "--untracked-files=all").stdout


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
    parts = Path(normalized).parts
    if any(part in {"node_modules", "__pycache__", ".cache", ".brvcache", ".wrangler",
                    ".pytest_cache", ".mypy_cache", ".ruff_cache"} for part in parts):
        return True
    if any(
        normalized == part.rstrip("/") or normalized.startswith(part)
        for part in RUNTIME_PARTS
    ) or normalized.endswith(".pyc"):
        return True
    if parts and parts[0] in {"test", "tests"}:
        name = Path(normalized).name.lower()
        fixture = (normalized in TEST_SOURCE_DATA_FILES
                   or any(part.lower() in {"fixtures", "mocks"} for part in parts[1:-1])
                   or "fixture" in name or name.startswith("mock_") or "_mock." in name)
        copied_directory = any(part.lower() in {"remote_main", "backups", "backup"}
                               for part in parts[1:-1])
        copied_name = not name.startswith("test_") and any(
            fnmatch.fnmatch(name, pattern) for pattern in (
                "*.before.*", "*.after.*", "*.before", "*.after", "*.backup", "*.bak",
                "*.before-*", "*.after-*",
            )
        )
        if not fixture and (copied_directory or copied_name):
            return True
        if Path(normalized).suffix.lower() in GENERATED_TEST_SUFFIXES:
            return not (fixture or name in {"package.json", "package-lock.json", "tsconfig.json"})
    return False


def oversized_source_file(path: str) -> bool:
    try:
        metadata = (PROJECT_ROOT / path).lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_size > MAX_SOURCE_FILE_BYTES


def gitlink_head_is_published(target: Path) -> bool:
    """Only publish child HEADs already known to be reachable on child origin.

    No network request is made by this check. A child without an origin or a
    locally known origin ref containing HEAD must be synchronized independently
    before the root repository can safely advertise its new commit reference.
    """
    remote = git("-C", str(target), "remote", "get-url", "origin", check=False)
    if remote.returncode:
        return False
    refs = git(
        "-C", str(target), "for-each-ref", "--contains=HEAD", "--format=%(refname)",
        "refs/remotes/origin/", check=False,
    )
    return refs.returncode == 0 and bool(refs.stdout.strip())


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
    entries = iter(git("status", "--porcelain=v1", "--ignore-submodules=dirty", "--untracked-files=all", "-z").stdout.split("\x00"))
    for entry in entries:
        if not entry:
            continue
        paths.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            original = next(entries, "")
            if original:
                paths.append(original)
    return paths


def stash_runtime_changes() -> str | None:
    changed = status_paths()
    non_runtime = [path for path in changed if not is_runtime_path(path) and not oversized_source_file(path)]
    if non_runtime:
        raise SyncDeferred("source-файлы ещё меняются: " + ", ".join(non_runtime[:10]))
    candidates = [path for path in changed if is_runtime_path(path) or oversized_source_file(path)]
    if not candidates:
        return None
    # Untracked runtime files stay in place: stash without --include-untracked
    # rejects their pathspecs, and removing live cache files is unnecessary.
    tracked = set(git("ls-files", "-z", "--", *candidates).stdout.split("\x00"))
    paths = [path for path in candidates if path in tracked]
    if not paths:
        return None
    previous = git("rev-parse", "--verify", "refs/stash", check=False).stdout.strip()
    result = git("stash", "push", "-m", "checksheets-sync-runtime", "--", *paths, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        raise RuntimeError("Не удалось временно убрать runtime-изменения в stash: " + " | ".join(detail))
    current = git("rev-parse", "--verify", "refs/stash", check=False).stdout.strip()
    if not current or current == previous:
        return None
    log.info("Runtime-изменения сохранены в stash %s", current[:12])
    return current


def restore_runtime_changes(stash_ref: str | None) -> None:
    if not stash_ref:
        return
    # Restore our exact object even if another Git client created a newer stash.
    result = git("stash", "apply", "--index", stash_ref, check=False)
    if result.returncode != 0:
        log.error("Runtime stash %s не удалось восстановить; объект сохранён", stash_ref[:12])
        return
    entries = git("stash", "list", "--format=%gd %H").stdout.splitlines()
    for entry in entries:
        ref, oid = entry.split(" ", 1)
        if oid == stash_ref:
            if git_sha(ref) == stash_ref:
                git("stash", "drop", ref)
            break
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


def source_snapshot() -> dict[str, tuple]:
    snapshot = {}
    oversized_sizes = []
    unpublished_gitlinks = 0
    for path in status_paths():
        target = PROJECT_ROOT / path
        if is_runtime_path(path) or (is_sensitive_path(path) and target.exists()):
            continue
        try:
            if target.is_symlink():
                signature = ("symlink", os.readlink(target))
            elif target.is_file():
                size = target.stat().st_size
                if size > MAX_SOURCE_FILE_BYTES:
                    oversized_sizes.append(size)
                    continue
                signature = ("file", sha256(target))
            elif target.is_dir():
                # With --untracked-files=all, directories here are gitlinks.
                if not gitlink_head_is_published(target):
                    unpublished_gitlinks += 1
                    continue
                signature = ("gitlink", git("-C", str(target), "rev-parse", "HEAD").stdout.strip())
            else:
                signature = ("deleted",)
        except FileNotFoundError:
            # A writer changed the file while it was being observed.
            continue
        snapshot[path] = signature
    if oversized_sizes:
        log.warning(
            "Не включаю в GitHub sync source-файлы крупнее %.0f MiB: %s файлов, %.1f MiB; "
            "локальные данные сохранены",
            MAX_SOURCE_FILE_BYTES / (1024 * 1024), len(oversized_sizes),
            sum(oversized_sizes) / (1024 * 1024),
        )
    if unpublished_gitlinks:
        log.warning(
            "Не публикую gitlink без подтверждённого child origin HEAD: %s; "
            "вложенные проекты нужно синхронизировать отдельно",
            unpublished_gitlinks,
        )
    return snapshot


def commit_stable_local_changes(dry_run: bool) -> str | None:
    before = source_snapshot()
    if not before:
        return None
    log.info("Проверяю стабильность %s source-файлов за %s секунд", len(before), SETTLE_SECONDS)
    if SETTLE_SECONDS:
        time.sleep(SETTLE_SECONDS)
    after = source_snapshot()
    stable = [path for path, signature in before.items() if after.get(path) == signature]
    if not stable:
        log.info("Source-файлы ещё меняются; готовые коммиты можно отправить отдельно")
        return None
    if dry_run:
        log.info("dry-run: было бы сохранено %s стабильных source-файлов", len(stable))
        return None
    git("add", "-A", "--", *stable)
    # Check content again after staging. Never commit an unrelated user's index
    # entries, and leave generated/sensitive staging untouched.
    latest = source_snapshot()
    stable = [path for path in stable if latest.get(path) == before[path]]
    if not stable:
        raise SyncDeferred("Source-файлы изменились во время подготовки commit")
    changed = git("diff", "--cached", "--name-only", "-z", "--", *stable).stdout
    if not changed:
        return None
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    git("commit", "--only", "-m", f"chore: sync local Checksheets changes ({timestamp})", "--", *stable)
    commit = git_sha()
    log.info("Создан локальный commit %s", commit[:12])
    return commit


def reconcile_git(dry_run: bool) -> tuple[str, str]:
    fetch_origin()
    commit_stable_local_changes(dry_run)
    if dry_run:
        return git_sha(), git_sha(f"origin/{BRANCH}")

    fetch_origin()
    local = git_sha()
    remote = git_sha(f"origin/{BRANCH}")
    if local == remote:
        return local, remote
    if git_is_ancestor(remote, local):
        # Push does not modify the checkout. Live cache files and unfinished
        # edits must not block commits which are already ready for GitHub.
        log.info("Локалка впереди; отправляю commit %s в GitHub", local[:12])
        git("push", "origin", f"HEAD:{BRANCH}")
    else:
        # Only operations changing the checkout require a clean source tree.
        runtime_stash = stash_runtime_changes()
        try:
            if git_is_ancestor(local, remote):
                log.info("GitHub впереди; fast-forward до %s", remote[:12])
                git("merge", "--ff-only", f"origin/{BRANCH}")
            else:
                log.warning("Ветки разошлись; выполняю rebase на origin/%s", BRANCH)
                try:
                    git("rebase", f"origin/{BRANCH}")
                    git("push", "origin", f"HEAD:{BRANCH}")
                except Exception:
                    git("rebase", "--abort", check=False)
                    raise RuntimeError("Автоматический rebase остановлен; нужна проверка конфликта.")
        finally:
            restore_runtime_changes(runtime_stash)
    # Fetch instead of assuming the push updated the tracking ref.
    fetch_origin()
    local = git_sha()
    remote = git_sha(f"origin/{BRANCH}")
    if local != remote:
        raise RuntimeError("После git-синхронизации HEAD и origin/main не совпали")
    return local, remote


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
    # npm exec --offline still needs registry metadata, even when the package
    # was once downloaded. Prefer the persistent deployment installation.
    installed = Path(os.environ.get(
        "CHECKSHEETS_SYNC_CLASP",
        str(STATE_ROOT / "tools" / "node_modules" / ".bin" / "clasp"),
    ))
    if installed.is_file():
        return (str(installed), *args)
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


def prune_backup_dirs(now: dt.datetime | None = None) -> tuple[int, int]:
    """Keep detailed recent snapshots and one rollback snapshot per older day."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)
    keep_all_after = now - dt.timedelta(days=BACKUP_KEEP_ALL_DAYS)
    keep_daily_after = now - dt.timedelta(days=BACKUP_KEEP_DAILY_DAYS)

    snapshots: list[tuple[dt.datetime, Path]] = []
    for path in BACKUP_ROOT.iterdir() if BACKUP_ROOT.exists() else ():
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            timestamp = dt.datetime.strptime(path.name, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=dt.timezone.utc
            )
        except ValueError:
            continue
        snapshots.append((timestamp, path))

    keep: set[Path] = set()
    latest_per_day: dict[dt.date, tuple[dt.datetime, Path]] = {}
    for timestamp, path in snapshots:
        if timestamp >= keep_all_after:
            keep.add(path)
        elif timestamp >= keep_daily_after:
            day = timestamp.date()
            if day not in latest_per_day or timestamp > latest_per_day[day][0]:
                latest_per_day[day] = (timestamp, path)
    keep.update(path for _, path in latest_per_day.values())

    removed_count = 0
    removed_bytes = 0
    for _, path in snapshots:
        if path in keep:
            continue
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    removed_bytes += item.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(path)
        removed_count += 1
    return removed_count, removed_bytes


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
    global _exclusive_lock_held
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncDeferred("Другой Checksheets sync или обслуживание уже выполняется")
        _exclusive_lock_held = True
        try:
            yield
        finally:
            _exclusive_lock_held = False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="выполнить один цикл; используется launchd")
    parser.add_argument("--dry-run", action="store_true", help="не коммитить, не push и не изменять Apps Script")
    args = parser.parse_args()
    configure_logging()

    try:
        with exclusive_lock():
            if not args.dry_run:
                recover_stale_git_index_lock()
            state = read_state()
            local, remote = reconcile_git(args.dry_run)
            if args.dry_run:
                log.info("dry-run завершён: local=%s origin=%s", local[:12], remote[:12])
                return 0

            apps_script_synced_sha = state.get("apps_script_synced_sha")
            apps_script_changed = git_changed_paths(apps_script_synced_sha, local)
            should_push = apps_script_synced_sha is None or apps_script_change(apps_script_changed)
            result = {"pushed": False, "verified": False, "file_count": 0}
            if should_push:
                upload_files = set(clasp_status())
                unfinished = [path for path in status_paths() if path in upload_files]
                if unfinished:
                    raise SyncDeferred("Apps Script source-файлы ещё меняются: " + ", ".join(unfinished[:10]))
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
            removed_backups, removed_bytes = prune_backup_dirs()
            if removed_backups:
                log.info(
                    "Очистил старые Apps Script backups: %s папок, %.1f MiB; "
                    "храню все за %s дней и по одному в день за %s дней",
                    removed_backups,
                    removed_bytes / (1024 * 1024),
                    BACKUP_KEEP_ALL_DAYS,
                    BACKUP_KEEP_DAILY_DAYS,
                )
            log.info("Цикл завершён: GitHub=%s, Apps Script push=%s", local[:12], result["pushed"])
        return 0
    except SyncDeferred as exc:
        log.info("Синхронизация отложена до следующего цикла: %s", exc)
        return 0
    except Exception as exc:
        log.error("Синхронизация остановлена: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
