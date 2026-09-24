"""Local connector checks; no Google/Ozon network calls."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ntc_live_local import (fetch_returns, normalize_postings, read_sheet, with_google_retry,
                            write_sheet)  # noqa: E402


class FakeSheet:
    def __init__(self):
        self.rows = [
            ["Артикул продавца", "Модель", "", "", "", "Остаток склад по моделям",
             "", "Х", "", "", "Ручное списание штук"],
            ["M-5", "M", "", "", "", 100, "", 5, "", "", 2],
            ["M-10", "M", "", "", "", 100, "", 10, "", "", ""],
        ]
        self.updated_ranges = []

    def get(self, range_name, value_render_option=None):
        if range_name == "A1:K1000":
            return self.rows
        raise AssertionError(range_name)

    def batch_update(self, requests, value_input_option):
        assert value_input_option == "USER_ENTERED"
        for request in requests:
            self.updated_ranges.append(request["range"])
            column = ord(request["range"][0]) - ord("A")
            for row, values in zip(self.rows[1:], request["values"]):
                row[column] = values[0]


class LocalConnectorTests(unittest.TestCase):
    def test_retries_transient_google_connection_errors_with_backoff(self):
        attempts = []
        delays = []

        def operation():
            attempts.append(1)
            if len(attempts) < 3:
                raise requests.exceptions.ConnectionError("remote closed connection")
            return "ok"

        result = with_google_retry("test", operation, sleep_fn=delays.append, jitter_fn=lambda: 0)
        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(delays, [5, 10])

    def test_does_not_retry_non_transient_errors(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise ValueError("bad input")

        with self.assertRaisesRegex(ValueError, "bad input"):
            with_google_retry("test", operation,
                              sleep_fn=lambda _delay: self.fail("must not sleep"))
        self.assertEqual(len(attempts), 1)

    def test_reads_model_once_and_writes_only_f(self):
        sheet = FakeSheet()
        snapshot = read_sheet(sheet)
        self.assertEqual(snapshot["stock_by_model"], {"M": 100})
        self.assertEqual(snapshot["manual_k"], {"M-5": 2, "M-10": 0})
        write_sheet(sheet, {"M": 80}, snapshot["model_rows"], snapshot["row_count"])
        self.assertEqual(sheet.updated_ranges, ["F2:F3"])
        self.assertEqual(read_sheet(sheet)["stock_by_model"], {"M": 80})
        self.assertEqual(sheet.rows[1][10], 2)  # K input unchanged.

    def test_rejects_inconsistent_physical_stock(self):
        sheet = FakeSheet()
        sheet.rows[2][5] = 99
        with self.assertRaisesRegex(ValueError, "F differs"):
            read_sheet(sheet)

    def test_imports_only_new_or_previously_tracked_postings(self):
        start = datetime(2026, 9, 16, 8, 53, tzinfo=timezone.utc)
        raw = [
            {"posting_number": "old", "status": "delivering", "in_process_at": "2026-09-15T00:00:00Z",
             "products": [{"offer_id": "M-5", "quantity": 1}]},
            {"posting_number": "tracked", "status": "delivering", "in_process_at": "2026-09-15T00:00:00Z",
             "products": [{"offer_id": "M-5", "quantity": 1}]},
            {"posting_number": "new", "status": "awaiting_packaging", "in_process_at": "2026-09-16T10:00:00Z",
             "products": [{"offer_id": "M-10", "quantity": 1}]},
        ]
        updates = normalize_postings(raw, {"M-5", "M-10"}, {"tracked"}, start)
        self.assertEqual({item["posting_number"] for item in updates}, {"tracked", "new"})

    def test_cancellation_after_ship_flag_survives_missed_intermediate_status(self):
        start = datetime(2026, 9, 16, 8, 53, tzinfo=timezone.utc)
        posting = {"posting_number": "tracked", "status": "cancelled",
                   "in_process_at": "2026-09-16T10:00:00Z",
                   "products": [{"offer_id": "M-5", "quantity": 1}],
                   "cancellation": {"cancelled_after_ship": True}}
        update = normalize_postings([posting], {"M-5"}, {"tracked"}, start)[0]
        self.assertIs(update["ever_handed_over"], True)
        posting["cancellation"]["cancelled_after_ship"] = False
        update = normalize_postings([posting], {"M-5"}, {"tracked"}, start)[0]
        self.assertIs(update["ever_handed_over"], False)
        del posting["cancellation"]
        update = normalize_postings([posting], {"M-5"}, {"tracked"}, start)[0]
        self.assertIs(update["ever_handed_over"], True)

    def test_return_api_is_read_only_and_uses_posting_filter(self):
        calls = []
        def fake_post(_http, _headers, path, body):
            calls.append((path, body))
            return {"returns": [], "has_next": False}
        import ntc_live_local
        original = ntc_live_local.post
        ntc_live_local.post = fake_post
        try:
            self.assertEqual(fetch_returns(object(), {}, ["P-1"]), [])
        finally:
            ntc_live_local.post = original
        self.assertEqual(calls[0][0], "/v1/returns/list")
        self.assertEqual(calls[0][1]["filter"], {"posting_numbers": ["P-1"]})


if __name__ == "__main__":
    unittest.main()
