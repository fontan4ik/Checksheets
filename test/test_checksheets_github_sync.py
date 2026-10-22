import contextlib
import datetime as dt
import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "checksheets_github_sync.py"
SPEC = importlib.util.spec_from_file_location("checksheets_github_sync", SCRIPT_PATH)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class StaleIndexLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / '.git').mkdir()
        self.lock = self.root / '.git/index.lock'
        self.lock.touch()
        self.now = time.time() + 7200
        self.backups = self.root / 'backups'
        for patcher in (
            patch.object(sync, 'PROJECT_ROOT', self.root),
            patch.object(sync, 'BACKUP_ROOT', self.backups),
            patch.object(sync, '_exclusive_lock_held', True),
            patch.object(sync.time, 'time', return_value=self.now),
            patch.object(sync, 'run', return_value=subprocess.CompletedProcess(
                ['git'], 0, '.git/index.lock\n', '')),
            patch.object(sync, 'index_lock_has_holder', return_value=False),
            patch.object(sync, 'git_writer_active', return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_old_empty_unowned_lock_is_backed_up_before_removal(self):
        self.assertTrue(sync.recover_stale_git_index_lock())
        self.assertFalse(self.lock.exists())
        backups = list((self.backups / 'git-index-locks').glob('*.lock'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'')

    def test_recent_lock_is_not_removed(self):
        os.utime(self.lock, (self.now, self.now))
        self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertTrue(self.lock.exists())
        self.assertFalse(self.backups.exists())

    def test_newly_copied_lock_with_old_mtime_is_not_removed(self):
        os.utime(self.lock, (0, 0))
        with patch.object(sync.time, 'time', return_value=time.time() - 7199):
            self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertTrue(self.lock.exists())

    def test_nonempty_old_lock_is_not_removed(self):
        self.lock.write_bytes(b'pending git index')
        self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertEqual(self.lock.read_bytes(), b'pending git index')

    def test_symlink_lock_is_not_followed_or_removed(self):
        self.lock.unlink()
        target = self.root / 'other-file'
        target.touch()
        self.lock.symlink_to(target)
        self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertTrue(self.lock.is_symlink())
        self.assertTrue(target.exists())

    def test_active_holder_or_writer_prevents_removal(self):
        for probe in ('index_lock_has_holder', 'git_writer_active'):
            with self.subTest(probe=probe), patch.object(sync, probe, return_value=True):
                self.assertFalse(sync.recover_stale_git_index_lock())
                self.assertTrue(self.lock.exists())

    def test_process_appearing_during_backup_prevents_removal(self):
        with patch.object(sync, 'git_writer_active', side_effect=[False, True]):
            self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertTrue(self.lock.exists())

    def test_lock_changed_during_backup_is_preserved(self):
        probes = iter([False, True])
        def update_after_probe(*_args, **_kwargs):
            if next(probes):
                self.lock.write_bytes(b'new pending index')
            return False
        with patch.object(sync, 'index_lock_has_holder', side_effect=update_after_probe):
            self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertEqual(self.lock.read_bytes(), b'new pending index')

    def test_replacement_lock_is_preserved(self):
        probes = iter([False, True])
        original_inode = self.lock.stat().st_ino
        def replace_after_probe(*_args, **_kwargs):
            if next(probes):
                replacement = self.root / 'replacement'
                replacement.touch()
                replacement.replace(self.lock)
            return False
        with patch.object(sync, 'index_lock_has_holder', side_effect=replace_after_probe):
            self.assertFalse(sync.recover_stale_git_index_lock())
        self.assertTrue(self.lock.exists())
        self.assertNotEqual(self.lock.stat().st_ino, original_inode)

    def test_recovery_requires_deployment_flock(self):
        with patch.object(sync, '_exclusive_lock_held', False):
            with self.assertRaises(RuntimeError):
                sync.recover_stale_git_index_lock()
        self.assertTrue(self.lock.exists())


class GitProcessInspectionTests(unittest.TestCase):
    def test_read_only_git_processes_are_not_writers(self):
        self.assertFalse(sync._git_process_can_write('git status --porcelain=v1'))
        self.assertFalse(sync._git_process_can_write('git -C /tmp/work -c core.fsmonitor= diff'))
        self.assertTrue(sync._git_process_can_write('git -c core.hooksPath=/dev/null add --sparse'))
        self.assertTrue(sync._git_process_can_write('git --git-dir=/tmp/repo commit -m test'))
        self.assertTrue(sync._git_process_can_write('git custom-alias'))

    def test_inspection_distinguishes_git_from_command_text(self):
        result = subprocess.CompletedProcess(['ps'], 0,
            ' 10 /usr/bin/git /usr/bin/git -C /tmp/repo status\n'
            ' 11 /bin/zsh /bin/zsh -c git add something\n', '')
        with patch.object(sync.subprocess, 'run', return_value=result):
            self.assertFalse(sync.git_writer_active())
        result.stdout += ' 12 /usr/bin/git /usr/bin/git add --sparse\n'
        with patch.object(sync.subprocess, 'run', return_value=result):
            self.assertTrue(sync.git_writer_active())

    def test_unavailable_ps_or_lsof_fails_closed(self):
        with patch.object(sync.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertTrue(sync.git_writer_active())
        with patch.object(sync.shutil, 'which', return_value=None):
            self.assertTrue(sync.index_lock_has_holder(Path('/tmp/index.lock')))

    def test_lsof_ignores_only_recovery_process_descriptor(self):
        with patch.object(sync.shutil, 'which', return_value='/usr/sbin/lsof'):
            result = subprocess.CompletedProcess(['lsof'], 0, '100\n', '')
            with patch.object(sync.subprocess, 'run', return_value=result):
                self.assertFalse(sync.index_lock_has_holder(Path('/tmp/index.lock'), ignore_pid=100))
                self.assertTrue(sync.index_lock_has_holder(Path('/tmp/index.lock')))
            result.stdout = '100\n101\n'
            with patch.object(sync.subprocess, 'run', return_value=result):
                self.assertTrue(sync.index_lock_has_holder(Path('/tmp/index.lock'), ignore_pid=100))


class GithubSyncArtifactSelectionTests(unittest.TestCase):
    def test_generated_test_payloads_and_nested_caches_are_local_only(self):
        for name in (
            'test/certificate_api_pilot_20261012/api_calls.jsonl',
            'test/certificate_api_pilot_20261012/ozon_live.json',
            'test/etm_matrix_20261021/matched.json.gz', 'test/snapshot.zip',
            'test/pdfs/download.pdf', 'test/screen.png', 'test/sheet.xlsx',
            'test/catalog.csv', 'test/probe.err', 'test/probe.log',
            'tmp/diagnostic.py', '.runtime/worker.js', 'outputs/result.xlsx',
            'test/runtime/restore.js', 'test/vendor/node_modules/index.js',
            'sites/demo/.wrangler/state.sqlite', 'test/.pytest_cache/state',
        ):
            with self.subTest(name=name):
                self.assertTrue(sync.is_runtime_path(name))

    def test_regression_sources_and_declared_fixtures_are_preserved(self):
        for name in (
            'test/test_ozon_cpc_cleanup.py', 'test/test_obor_formulas_local.js',
            'test/package.json', 'test/package-lock.json', 'test/tsconfig.json',
            'test/fixtures/response.json', 'test/mocks/payload.json',
            'test/mock_response.json', 'test/response_fixture.json',
            'test/obor_canonical_formulas_fixture.json',
            'test/new_rs_cable_units_20261020.json',
            'Docs/context.json', 'ozon_perf_quota.py',
        ):
            with self.subTest(name=name):
                self.assertFalse(sync.is_runtime_path(name))
        self.assertTrue(sync.is_runtime_path('test/fixtures/node_modules/package.json'))
        self.assertTrue(sync.is_runtime_path('test/tmp/mock_response.json'))

    def test_copied_production_backups_are_local_only(self):
        for name in (
            'test/jazzway_ntc_disable_20261019/remote_main/Shared_Настройки.js',
            'test/jazzway_ntc_disable_20261019/remote_main/Shared_Telegram.js',
            'test/jazzway_ntc_disable_20261019/remote_main/List_ТЕСТ.js',
            'test/rs_moscow_disable_20261020/sync-feron-stocks.before.js',
            'test/repair/sync-rs-stocks.after.js', 'test/repair/script.js.before',
            'test/repair/script.js.after', 'test/repair/script.js.backup',
            'test/repair/script.js.bak', 'test/repair/script.before-20261022.js',
            'test/repair/backups/Shared_Telegram.js',
            'tests/repair/backup/config.py', 'test/remote_main/package.json',
        ):
            with self.subTest(name=name):
                self.assertTrue(sync.is_runtime_path(name))

    def test_backup_pattern_keeps_real_tests_and_mock_fixtures(self):
        for name in (
            'test/test_backup.before.js', 'test/test_campaign.after.py',
            'test/test_change.before-20261022.js', 'test/test_backups.py',
            'test/fixtures/remote_main/Shared_Telegram.js',
            'test/mocks/backups/old_response.json',
            'test/response_fixture.before.json', 'test/mock_response.after.json',
        ):
            with self.subTest(name=name):
                self.assertFalse(sync.is_runtime_path(name))

    def test_oversized_sources_never_reach_hashing_or_staging_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            huge = root / 'private-payload.js'
            with huge.open('wb') as handle:
                handle.truncate(sync.MAX_SOURCE_FILE_BYTES + 1)
            (root / 'source.py').write_text('print(1)')
            with (patch.object(sync, 'PROJECT_ROOT', root),
                  patch.object(sync, 'status_paths', return_value=['private-payload.js', 'source.py']),
                  patch.object(sync, 'sha256', return_value='digest') as digest,
                  self.assertLogs(sync.log, level='WARNING') as messages):
                self.assertEqual(sync.source_snapshot(), {'source.py': ('file', 'digest')})
                digest.assert_called_once_with(root / 'source.py')
                self.assertTrue(sync.oversized_source_file('private-payload.js'))
            self.assertIn('1 файлов', messages.output[0])
            self.assertNotIn('private-payload', messages.output[0])
            self.assertTrue(huge.exists())

    def test_size_guard_applies_to_declared_fixtures_too(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'test/fixtures/large.json'
            fixture.parent.mkdir(parents=True)
            with fixture.open('wb') as handle:
                handle.truncate(sync.MAX_SOURCE_FILE_BYTES + 1)
            with (patch.object(sync, 'PROJECT_ROOT', root),
                  patch.object(sync, 'status_paths', return_value=['test/fixtures/large.json']),
                  patch.object(sync, 'sha256') as digest,
                  self.assertLogs(sync.log, level='WARNING')):
                self.assertEqual(sync.source_snapshot(), {})
                digest.assert_not_called()

    def test_generated_payload_changes_are_excluded_even_when_tracked(self):
        with (patch.object(sync, 'status_paths', return_value=['test/old-tracked.jsonl', 'test/response_fixture.json']),
              patch.object(sync.Path, 'is_file', return_value=True),
              patch.object(sync.Path, 'stat', return_value=type('Stat', (), {'st_size': 10})()),
              patch.object(sync, 'sha256', return_value='fixture-digest')):
            self.assertEqual(sync.source_snapshot(), {'test/response_fixture.json': ('file', 'fixture-digest')})

    def test_child_without_origin_or_published_head_is_not_advertised(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / 'sites/app'
            child.mkdir(parents=True)
            for has_origin, known_ref in ((False, False), (True, False), (True, True)):
                with self.subTest(has_origin=has_origin, known_ref=known_ref):
                    def git(*args, **kwargs):
                        if 'get-url' in args:
                            return subprocess.CompletedProcess(['git'], 0 if has_origin else 2,
                                                               'https://example.invalid/site.git' if has_origin else '', '')
                        if 'for-each-ref' in args:
                            return subprocess.CompletedProcess(['git'], 0,
                                                               'refs/remotes/origin/main\n' if known_ref else '', '')
                        if 'rev-parse' in args:
                            return subprocess.CompletedProcess(['git'], 0, 'child-head\n', '')
                        self.fail(f'unexpected command {args}')
                    with (patch.object(sync, 'PROJECT_ROOT', root),
                          patch.object(sync, 'status_paths', return_value=['sites/app']),
                          patch.object(sync, 'git', side_effect=git)):
                        if known_ref:
                            self.assertEqual(sync.source_snapshot(), {'sites/app': ('gitlink', 'child-head')})
                        else:
                            with self.assertLogs(sync.log, level='WARNING') as messages:
                                self.assertEqual(sync.source_snapshot(), {})
                            self.assertNotIn('example.invalid', messages.output[0])
                    self.assertTrue(child.exists())


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

    def test_dry_run_does_not_recover_index_lock(self):
        with (
            patch.object(sys, 'argv', ['checksheets_github_sync.py', '--once', '--dry-run']),
            patch.object(sync, 'configure_logging'),
            patch.object(sync, 'exclusive_lock', return_value=contextlib.nullcontext()),
            patch.object(sync, 'recover_stale_git_index_lock') as recover,
            patch.object(sync, 'read_state', return_value={}),
            patch.object(sync, 'reconcile_git', return_value=('local', 'remote')),
        ):
            self.assertEqual(sync.main(), 0)
            recover.assert_not_called()

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
            patch.object(sync, "recover_stale_git_index_lock", return_value=False),
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

    def test_real_commit_keeps_generated_payloads_local_and_includes_fixture(self):
        self.write('test/api_calls.jsonl', 'original payload\n')
        self.git('add', 'test/api_calls.jsonl')
        self.git('commit', '-qm', 'existing tracked runtime')
        self.write('test/api_calls.jsonl', 'new local payload\n')
        self.write('test/snapshot.json', '{"generated": true}')
        self.git('add', 'test/snapshot.json')  # unrelated staging must remain untouched
        self.write('test/fixtures/response.json', '{"expected": true}')
        self.write('source.js', 'updated source\n')

        with patch.object(sync, 'SETTLE_SECONDS', 0):
            self.assertIsNotNone(sync.commit_stable_local_changes(False))

        committed = set(self.git('show', '--pretty=', '--name-only', 'HEAD').splitlines())
        self.assertEqual(committed, {'source.js', 'test/fixtures/response.json'})
        self.assertEqual((self.root / 'test/api_calls.jsonl').read_text(), 'new local payload\n')
        self.assertTrue((self.root / 'test/snapshot.json').exists())
        self.assertEqual(self.git('diff', '--cached', '--name-only'), 'test/snapshot.json')

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

    def test_unfinished_apps_script_source_is_not_deployed(self):
        with (
            patch.object(sys, "argv", ["checksheets_github_sync.py", "--once"]),
            patch.object(sync, "configure_logging"),
            patch.object(sync, "exclusive_lock", return_value=contextlib.nullcontext()),
            patch.object(sync, "recover_stale_git_index_lock", return_value=False),
            patch.object(sync, "read_state", return_value={}),
            patch.object(sync, "reconcile_git", return_value=("new", "new")),
            patch.object(sync, "git_changed_paths", return_value=None),
            patch.object(sync, "clasp_status", return_value=["Flow_Триггеры__Основные.js"]),
            patch.object(sync, "status_paths", return_value=["Flow_Триггеры__Основные.js"]),
            patch.object(sync, "push_apps_script") as push,
            patch.object(sync, "write_state") as write,
        ):
            self.assertEqual(sync.main(), 0)
            push.assert_not_called()
            write.assert_not_called()


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
