import contextlib
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "checksheets_github_sync.py"
SPEC = importlib.util.spec_from_file_location("checksheets_github_sync", SCRIPT_PATH)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class GithubSyncDeferralTests(unittest.TestCase):
    def test_git_contention_retries_and_defers_without_removing_lock(self):
        failure = subprocess.CompletedProcess(['git'], 128, '', "index.lock: File exists; Another git process seems to be running")
        with patch.object(sync, 'run', return_value=failure) as runner, patch.object(sync.time, 'sleep'):
            with self.assertRaises(sync.SyncDeferred):
                sync.git('add', '-A')
            self.assertEqual(runner.call_count, 3)

    def test_git_transient_contention_recovers(self):
        failure = subprocess.CompletedProcess(['git'], 128, '', 'index.lock: File exists')
        success = subprocess.CompletedProcess(['git'], 0, '', '')
        with patch.object(sync, 'run', side_effect=[failure, success]), patch.object(sync.time, 'sleep'):
            self.assertIs(sync.git('add', '-A'), success)

    def test_git_other_failure_is_not_hidden(self):
        failure = subprocess.CompletedProcess(['git'], 128, '', 'authentication failed')
        with patch.object(sync, 'run', return_value=failure):
            with self.assertRaises(RuntimeError):
                sync.git('fetch')

    def test_clasp_uses_persistent_install_without_npm_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'tools/node_modules/.bin/clasp'
            binary.parent.mkdir(parents=True)
            binary.write_text('test binary')
            with patch.object(sync, 'STATE_ROOT', Path(temporary)):
                self.assertEqual(sync.clasp_command('status'), (str(binary), 'status'))

    def test_status_ignores_nested_worktree_but_not_gitlink_changes(self):
        success = subprocess.CompletedProcess(['git'], 0, '', '')
        with patch.object(sync, 'git', return_value=success) as git:
            sync.git_status()
            self.assertIn('--ignore-submodules=dirty', git.call_args.args)
            sync.status_paths()
            self.assertIn('--ignore-submodules=dirty', git.call_args.args)

    def test_commit_excludes_cache_and_handles_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.run(['git', *args], cwd=root, text=True, capture_output=True, check=True)
            git('init', '-q')
            git('config', 'user.email', 'test@example.invalid')
            git('config', 'user.name', 'Sync Test')
            (root / 'initial').write_text('base')
            git('add', '.')
            git('commit', '-qm', 'base')
            cache = root / 'graphify-out/cache'
            cache.mkdir(parents=True)
            for index in range(100):
                (cache / f'{index}.json').write_text('{}')
            (root / 'Тест файл.js').write_text('const value = 1;')
            git('add', 'graphify-out')  # leftover staged cache from older worker
            real_run = sync.run
            def run_here(command, **kwargs):
                return real_run(command, cwd=root, **kwargs)
            with patch.object(sync, 'PROJECT_ROOT', root), patch.object(sync, 'run', side_effect=run_here), patch.object(sync, 'SETTLE_SECONDS', 0):
                self.assertIsNotNone(sync.commit_stable_local_changes(False))
            names = git('show', '--pretty=', '--name-only', '-z', 'HEAD').stdout
            self.assertEqual(names.strip('\x00'), 'Тест файл.js')
            self.assertEqual(len(list(cache.glob('*.json'))), 100)

    def test_generated_graphify_cache_is_runtime(self):
        self.assertTrue(sync.is_runtime_path("graphify-out/cache/last_query_stamp"))
        self.assertFalse(sync.is_runtime_path("sync-cdek-ozon-stocks.js"))

    def test_concurrent_source_edit_defers_without_failing_cycle(self):
        with patch.object(sync, "status_paths", return_value=["Shared_Telegram.js"]):
            with self.assertRaises(sync.SyncDeferred):
                sync.stash_runtime_changes()

        with (
            patch.object(sys, "argv", ["checksheets_github_sync.py", "--once"]),
            patch.object(sync, "configure_logging"),
            patch.object(sync, "exclusive_lock", return_value=contextlib.nullcontext()),
            patch.object(sync, "read_state", return_value={}),
            patch.object(sync, "reconcile_git", side_effect=sync.SyncDeferred("source-файлы ещё меняются")),
        ):
            self.assertEqual(sync.main(), 0)


class GithubSyncRepositoryTests(unittest.TestCase):
    """Exercise reconciliation against isolated repositories, without network."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        parent = Path(self.temporary.name)
        self.root = parent / 'workspace'
        self.root.mkdir()
        self.remote = parent / 'remote.git'
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Sync Test')
        self.write('source.js', 'base source\n')
        self.write('logs/runtime.txt', 'base runtime\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        subprocess.run(['git', 'init', '--bare', '-q', str(self.remote)], check=True)
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-q', '-u', 'origin', 'main')
        real_run = sync.run

        def run_here(command, **kwargs):
            kwargs.setdefault('cwd', self.root)
            return real_run(command, **kwargs)

        for patcher in (
            patch.object(sync, 'PROJECT_ROOT', self.root),
            patch.object(sync, 'BRANCH', 'main'),
            patch.object(sync, 'run', side_effect=run_here),
            patch.object(sync, 'SETTLE_SECONDS', 1),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, text=True,
                              capture_output=True, check=True).stdout.strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def remote_head(self):
        return subprocess.run(['git', '--git-dir', str(self.remote), 'rev-parse',
                               'refs/heads/main'], text=True, capture_output=True,
                              check=True).stdout.strip()

    def test_untracked_runtime_does_not_reuse_or_remove_existing_stash(self):
        self.write('source.js', 'previous stash\n')
        self.git('stash', 'push', '-qm', 'existing unrelated work')
        previous = self.git('rev-parse', 'refs/stash')
        self.write('graphify-out/cache/query.json', '{}')

        stash = sync.stash_runtime_changes()
        self.assertIsNone(stash)
        sync.restore_runtime_changes(stash)

        self.assertEqual(self.git('rev-parse', 'refs/stash'), previous)
        self.assertEqual((self.root / 'source.js').read_text(), 'base source\n')
        self.assertTrue((self.root / 'graphify-out/cache/query.json').exists())

    def test_tracked_runtime_stash_restores_exact_entry_if_new_stash_appears(self):
        self.write('logs/runtime.txt', 'pending runtime\n')
        self.write('graphify-out/cache/query.json', '{}')
        runtime_stash = sync.stash_runtime_changes()
        self.assertIsNotNone(runtime_stash)
        self.assertEqual((self.root / 'logs/runtime.txt').read_text(), 'base runtime\n')
        self.write('source.js', 'other client stash\n')
        self.git('stash', 'push', '-qm', 'other client')
        other_stash = self.git('rev-parse', 'refs/stash')

        sync.restore_runtime_changes(runtime_stash)

        self.assertEqual((self.root / 'logs/runtime.txt').read_text(), 'pending runtime\n')
        self.assertEqual((self.root / 'source.js').read_text(), 'base source\n')
        self.assertEqual(self.git('rev-parse', 'refs/stash'), other_stash)
        self.assertEqual(len(self.git('stash', 'list').splitlines()), 1)
        self.assertTrue((self.root / 'graphify-out/cache/query.json').exists())

    def test_local_ahead_pushes_despite_runtime_and_active_source_edit(self):
        self.write('source.js', 'committed source\n')
        self.git('add', 'source.js')
        self.git('commit', '-qm', 'ready for GitHub')
        committed = self.git('rev-parse', 'HEAD')
        self.write('source.js', 'active edit one\n')
        self.write('logs/runtime.txt', 'active runtime\n')
        self.write('graphify-out/cache/query.json', '{}')

        with patch.object(sync.time, 'sleep', side_effect=lambda _: self.write(
                'source.js', 'active edit two\n')):
            local, remote = sync.reconcile_git(False)

        self.assertEqual((local, remote), (committed, committed))
        self.assertEqual(self.remote_head(), committed)
        self.assertEqual((self.root / 'source.js').read_text(), 'active edit two\n')
        self.assertEqual((self.root / 'logs/runtime.txt').read_text(), 'active runtime\n')
        self.assertEqual(self.git('stash', 'list'), '')

    def test_changing_runtime_does_not_block_stable_source_commit(self):
        self.write('source.js', 'stable new source\n')
        self.write('logs/runtime.txt', 'runtime before\n')
        def runtime_updates(_):
            self.write('logs/runtime.txt', 'runtime after\n')
            self.write('graphify-out/cache/new-query.json', '{}')

        with patch.object(sync.time, 'sleep', side_effect=runtime_updates):
            commit = sync.commit_stable_local_changes(False)

        self.assertIsNotNone(commit)
        self.assertEqual(self.git('show', '--pretty=', '--name-only', 'HEAD'), 'source.js')
        self.assertEqual((self.root / 'logs/runtime.txt').read_text(), 'runtime after\n')

    def test_remote_ahead_defers_while_source_is_actively_changing(self):
        base = self.git('rev-parse', 'HEAD')
        self.write('remote.js', 'remote addition\n')
        self.git('add', 'remote.js')
        self.git('commit', '-qm', 'remote addition')
        remote = self.git('rev-parse', 'HEAD')
        self.git('push', '-q', 'origin', 'main')
        self.git('reset', '--hard', base)
        self.write('source.js', 'active edit one\n')

        with patch.object(sync.time, 'sleep', side_effect=lambda _: self.write(
                'source.js', 'active edit two\n')):
            with self.assertRaises(sync.SyncDeferred):
                sync.reconcile_git(False)

        self.assertEqual(self.git('rev-parse', 'HEAD'), base)
        self.assertEqual(self.remote_head(), remote)
        self.assertEqual((self.root / 'source.js').read_text(), 'active edit two\n')
        self.assertEqual(self.git('stash', 'list'), '')

    def test_remote_ahead_merges_and_restores_runtime_changes(self):
        base = self.git('rev-parse', 'HEAD')
        self.write('remote.js', 'remote addition\n')
        self.git('add', 'remote.js')
        self.git('commit', '-qm', 'remote addition')
        remote = self.git('rev-parse', 'HEAD')
        self.git('push', '-q', 'origin', 'main')
        self.git('reset', '--hard', base)
        self.write('logs/runtime.txt', 'pending runtime\n')
        self.write('graphify-out/cache/query.json', '{}')

        local, synced_remote = sync.reconcile_git(False)

        self.assertEqual((local, synced_remote), (remote, remote))
        self.assertEqual((self.root / 'remote.js').read_text(), 'remote addition\n')
        self.assertEqual((self.root / 'logs/runtime.txt').read_text(), 'pending runtime\n')
        self.assertTrue((self.root / 'graphify-out/cache/query.json').exists())
        self.assertEqual(self.git('stash', 'list'), '')


class BackupRetentionTests(unittest.TestCase):
    def test_keeps_recent_snapshots_and_one_per_day_for_older_window(self):
        now = dt.datetime(2026, 10, 9, 12, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(sync, "BACKUP_ROOT", root):
                def add_snapshot(timestamp: dt.datetime, size: int = 1) -> Path:
                    path = root / timestamp.strftime("%Y%m%dT%H%M%SZ")
                    path.mkdir()
                    (path / "snapshot.js").write_bytes(b"x" * size)
                    return path

                recent_early = add_snapshot(now - dt.timedelta(days=5), 2)
                recent_late = add_snapshot(now - dt.timedelta(days=5) + dt.timedelta(hours=1), 3)
                old_day_early = add_snapshot(now - dt.timedelta(days=35), 5)
                old_day_latest = add_snapshot(now - dt.timedelta(days=35) + dt.timedelta(hours=1), 7)
                expired = add_snapshot(now - dt.timedelta(days=95), 11)
                unrecognized = root / "manual-note"
                unrecognized.mkdir()

                removed_count, removed_bytes = sync.prune_backup_dirs(now)

                self.assertEqual(removed_count, 2)
                self.assertEqual(removed_bytes, 5 + 11)
                self.assertTrue(recent_early.exists())
                self.assertTrue(recent_late.exists())
                self.assertFalse(old_day_early.exists())
                self.assertTrue(old_day_latest.exists())
                self.assertFalse(expired.exists())
                self.assertTrue(unrecognized.exists())


if __name__ == "__main__":
    unittest.main()
