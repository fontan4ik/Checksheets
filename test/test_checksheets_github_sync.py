import contextlib
import importlib.util
from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
