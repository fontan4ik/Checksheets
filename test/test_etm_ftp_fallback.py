import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import etm_sync_multi_store as etm


class EtmFtpFallbackTests(unittest.TestCase):
    def setUp(self):
        self.original_today = etm.today_ftp_date
        self.original_yesterday = etm.yesterday_ftp_date
        self.original_require_today = etm.FTP_REQUIRE_TODAY
        etm.today_ftp_date = lambda: "20260730"
        etm.yesterday_ftp_date = lambda: "20260729"
        etm.FTP_REQUIRE_TODAY = True

    def tearDown(self):
        etm.today_ftp_date = self.original_today
        etm.yesterday_ftp_date = self.original_yesterday
        etm.FTP_REQUIRE_TODAY = self.original_require_today

    def test_uses_yesterdays_files_when_todays_files_are_absent(self):
        files = [
            etm.FtpFile("/from_etm/13/price.csv", 10, "20260729042015"),
            etm.FtpFile("/from_etm/13/older.csv", 10, "20260728042015"),
        ]

        selected = etm.filter_today_files(files)

        self.assertEqual([item.remote_path for item in selected], ["/from_etm/13/price.csv"])

    def test_prefers_todays_files_over_yesterday_fallback(self):
        files = [
            etm.FtpFile("/from_etm/13/yesterday.csv", 10, "20260729042015"),
            etm.FtpFile("/from_etm/13/today.csv", 10, "20260730042015"),
        ]

        selected = etm.filter_today_files(files)

        self.assertEqual([item.remote_path for item in selected], ["/from_etm/13/today.csv"])

    def test_retries_warehouse_fetch_with_fresh_ftp_connection_after_eof(self):
        class FakeFTP:
            def __init__(self, number):
                self.number = number
                self.closed = False

            def quit(self):
                self.closed = True

            def close(self):
                self.closed = True

        original_connect = etm.connect_ftp
        original_fetch = etm.fetch_warehouse_stock_lookup
        original_sleep = etm.time.sleep
        connections = []
        calls = []
        try:
            def fake_connect():
                connection = FakeFTP(len(connections) + 1)
                connections.append(connection)
                return connection

            def fake_fetch(ftp, *_args, **_kwargs):
                calls.append(ftp.number)
                if ftp.number == 1:
                    raise EOFError("transient control connection drop")
                return ({"records": 1}, [{"remote_path": "price.csv"}], True)

            etm.connect_ftp = fake_connect
            etm.fetch_warehouse_stock_lookup = fake_fetch
            etm.time.sleep = lambda _seconds: None

            result = etm.fetch_warehouse_stock_lookup_with_retry(
                "/from_etm/13", "Samara", "latest", "smr", {}, force=True
            )

            self.assertEqual(result[0]["records"], 1)
            self.assertEqual(calls, [1, 2])
            self.assertTrue(all(connection.closed for connection in connections))
        finally:
            etm.connect_ftp = original_connect
            etm.fetch_warehouse_stock_lookup = original_fetch
            etm.time.sleep = original_sleep


if __name__ == "__main__":
    unittest.main()
