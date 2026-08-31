import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


    def test_download_logs_bytes_and_duration(self):
        class FakeFTP:
            def retrbinary(self, command, callback):
                callback(b"abc")
                callback(b"de")

        with patch.object(etm.time, "monotonic", side_effect=[10.0, 12.5]):
            with self.assertLogs(etm.logging.getLogger(), level="INFO") as captured:
                content = etm.download_ftp_file(FakeFTP(), "/from_etm/13/price.csv")

        self.assertEqual(content, b"abcde")
        self.assertTrue(any("bytes=5" in line and "duration=2.50s" in line for line in captured.output))

    def test_validate_ftp_csv_reads_all_rows_and_requires_stock_columns(self):
        content = (
            "Код ЭТМ;Количество;Артикул;Производитель\n"
            "0007;4;00123;Arlight\n"
            "0008;0;00124;Arlight\n"
        ).encode("cp1251")

        stats = etm.validate_ftp_csv(content, "/from_etm/13/price.csv")

        self.assertEqual(stats["header_columns"], 4)
        self.assertEqual(stats["data_rows"], 2)
        self.assertTrue(stats["has_data"])

    def test_invalid_csv_is_not_cached_or_processed(self):
        ftp_file = etm.FtpFile("/from_etm/13/price.csv", 10, "20260730042015")
        with patch.object(etm, "walk_ftp_files", return_value=[ftp_file]), patch.object(
            etm, "download_ftp_file", return_value=b"broken"
        ), patch.object(
            etm, "validate_ftp_csv", side_effect=ValueError("invalid CSV")
        ), patch.object(etm, "save_ftp_cache") as save_cache:
            with self.assertRaises(ValueError):
                etm.fetch_warehouse_stock_lookup(
                    object(), "/from_etm/13", "Samara", "latest", "smr", {}, force=True
                )

        save_cache.assert_not_called()

    def test_ftp_defaults_use_300_second_timeout_and_three_attempts(self):
        self.assertEqual(etm.FTP_TIMEOUT, 300)
        self.assertEqual(etm.FTP_WAREHOUSE_RETRIES, 3)


if __name__ == "__main__":
    unittest.main()
