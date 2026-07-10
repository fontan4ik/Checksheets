import http.client
import pathlib
import sys
import unittest
from unittest import mock

import requests

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import gsheets_utils  # noqa: E402


class FakeWorksheet:
    row_count = 10

    def __init__(self, failures_before_success=0):
        self.failures_before_success = failures_before_success
        self.update_calls = []
        self.clear_calls = []
        self.row_value_calls = 0

    def row_values(self, row):
        self.row_value_calls += 1
        return ["Артикул", "Остаток АПИ", "Цена закуп"]

    def _maybe_fail(self):
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise requests.exceptions.ConnectionError(
                http.client.RemoteDisconnected("Remote end closed connection without response")
            )

    def update(self, range_label, values):
        self._maybe_fail()
        self.update_calls.append((range_label, values))
        return {"updatedRange": range_label}

    def batch_clear(self, ranges):
        self._maybe_fail()
        self.clear_calls.append(ranges)
        return {"clearedRanges": ranges}


class GSheetsRetryTests(unittest.TestCase):
    def setUp(self):
        self.sleep_patch = mock.patch.object(gsheets_utils.time, "sleep", lambda _seconds: None)
        self.sleep_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()

    def test_update_column_by_header_retries_transient_disconnect(self):
        ws = FakeWorksheet(failures_before_success=2)

        gsheets_utils.update_column_by_header(ws, "Остаток АПИ", [[1], [2], [3]])

        self.assertEqual(ws.update_calls, [("B2:B4", [[1], [2], [3]])])

    def test_clear_column_retries_transient_disconnect(self):
        ws = FakeWorksheet(failures_before_success=1)

        gsheets_utils.clear_column(ws, "Цена закуп")

        self.assertEqual(ws.clear_calls, [["C2:C10"]])

    def test_non_transient_error_is_not_retried(self):
        calls = {"count": 0}

        def fail_value_error():
            calls["count"] += 1
            raise ValueError("bad header")

        with self.assertRaises(ValueError):
            gsheets_utils._retry_gsheet_call("unit-test", fail_value_error)

        self.assertEqual(calls["count"], 1)


if __name__ == "__main__":
    unittest.main()
