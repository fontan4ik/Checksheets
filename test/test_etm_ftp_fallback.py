import sys
import tempfile
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

    def test_retries_transient_ftp_download_eof(self):
        class FlakyFTP:
            def __init__(self):
                self.calls = 0

            def retrbinary(self, _command, callback):
                self.calls += 1
                if self.calls == 1:
                    raise EOFError("transient data connection drop")
                callback(b"payload")

        original_root = etm.FTP_LOCAL_ROOT
        original_sleep = etm.time.sleep
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                etm.FTP_LOCAL_ROOT = Path(tmp_dir)
                etm.time.sleep = lambda _seconds: None
                ftp = FlakyFTP()

                content = etm.download_ftp_file(ftp, "/from_etm/13/price.csv")

                self.assertEqual(content, b"payload")
                self.assertEqual(ftp.calls, 2)
                self.assertEqual(
                    (Path(tmp_dir) / "from_etm/13/price.csv").read_bytes(),
                    b"payload",
                )
            finally:
                etm.FTP_LOCAL_ROOT = original_root
                etm.time.sleep = original_sleep


if __name__ == "__main__":
    unittest.main()
