import contextlib
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "checksheets_github_sync.py"
SPEC = importlib.util.spec_from_file_location("checksheets_github_sync", SCRIPT_PATH)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class GithubSyncDeferralTests(unittest.TestCase):
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
