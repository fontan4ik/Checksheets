import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "sync_etm_codes.py"
spec = importlib.util.spec_from_file_location("sync_etm_codes", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SyncEtmCodesTests(unittest.TestCase):
    def test_load_mapping_from_ftp_cp1251_columns(self):
        content = (
            "Код ЭТМ;Полное наименование;Цена;Количество;Артикул;Производитель\n"
            "0007;Товар;1;0;00123;Arlight\n"
        ).encode("cp1251")

        mapping, stats = module.load_mapping_from_bytes(content, "price.csv")

        self.assertEqual(mapping[("00123", "arlight")], "0007")
        self.assertEqual(stats["source_rows"], 1)

    def test_load_mapping_preserves_leading_zero_and_accepts_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.csv"
            path.write_text(
                "Код ЭТМ;Артикул;Производитель\n"
                "0007;00123;Arlight\n"
                "0007;00123;Arlight\n",
                encoding="utf-8",
            )
            mapping, stats = module.load_csv_mapping(path)

        self.assertEqual(mapping[("00123", "arlight")], "0007")
        self.assertEqual(stats["duplicate_rows"], 1)
        self.assertEqual(stats["mapping_keys"], 1)

    def test_load_mapping_excludes_conflicting_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.csv"
            path.write_text(
                "Код ЭТМ;Артикул;Производитель\n"
                "7;00123;Arlight\n"
                "8;00123;arlight\n",
                encoding="utf-8",
            )
            mapping, stats = module.load_csv_mapping(path)

        self.assertEqual(mapping, {})
        self.assertEqual(stats["conflict_keys"], 1)

    def test_plan_updates_matches_model_and_brand_and_preserves_unmatched(self):
        rows = [
            ["art", "model", "brand", "Коды ЭТМ"],
            ["a", "00123", "Arlight", ""],
            ["b", "99999", "Arlight", "old"],
            ["c", "00123", "Other", "keep"],
            ["d", "00123", "ARLIGHT", "0007"],
        ]
        updates, stats = module.plan_updates(
            rows,
            {"article": 1, "model": 2, "brand": 3, "etm_code": 4},
            {("00123", "arlight"): "0007"},
        )

        self.assertEqual([(u.row, u.code) for u in updates], [(2, "0007")])
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["existing"], 3)
        self.assertEqual(stats["unmatched"], 0)

    def test_a1_ranges_group_adjacent_rows(self):
        updates = [
            module.Update(2, "10", "a", "b", "brand", "model"),
            module.Update(3, "11", "a", "b", "brand", "model"),
            module.Update(7, "12", "a", "b", "brand", "model"),
        ]
        self.assertEqual(
            module.a1_ranges(updates, 23),
            [("W2:W3", [["10"], ["11"]]), ("W7:W7", [["12"]])],
        )

    def test_update_sheet_uses_one_batch_request(self):
        class FakeWorksheet:
            def __init__(self):
                self.calls = []

            def batch_update(self, data, **kwargs):
                self.calls.append((data, kwargs))

        worksheet = FakeWorksheet()
        updates = [
            module.Update(2, "10", "m1", "a1", "b", "model"),
            module.Update(4, "20", "m2", "a2", "b", "article"),
        ]

        range_count = module.update_sheet(worksheet, updates, 23)

        self.assertEqual(range_count, 2)
        self.assertEqual(len(worksheet.calls), 1)
        payload, kwargs = worksheet.calls[0]
        self.assertEqual([item["range"] for item in payload], ["W2:W2", "W4:W4"])
        self.assertEqual(kwargs["value_input_option"], "USER_ENTERED")

    def test_plan_updates_falls_back_to_article_and_rejects_ambiguous_match(self):
        rows = [
            ["art", "model", "brand", "Коды ЭТМ"],
            ["art-1", "unknown-model", "Brand", ""],
            ["art-2", "model-2", "Brand", ""],
        ]
        mapping = {
            ("art-1", "brand"): "100",
            ("model-2", "brand"): "200",
            ("art-2", "brand"): "201",
        }

        updates, stats = module.plan_updates(
            rows,
            {"article": 1, "model": 2, "brand": 3, "etm_code": 4},
            mapping,
        )

        self.assertEqual([(item.row, item.code, item.matched_by) for item in updates], [(2, "100", "article")])
        self.assertEqual(stats["ambiguous"], 1)

    def test_second_warehouse_only_sees_cells_left_blank_by_first(self):
        rows = [
            ["art", "model", "brand", "Коды ЭТМ"],
            ["a", "m", "Brand", ""],
        ]
        columns = {"article": 1, "model": 2, "brand": 3, "etm_code": 4}
        updates_13, stats_13 = module.plan_updates(
            rows, columns, {("m", "brand"): "13-code"}
        )
        module._apply_updates_to_memory(rows, updates_13, 4)
        updates_14, stats_14 = module.plan_updates(
            rows, columns, {("m", "brand"): "14-code"}
        )

        self.assertEqual([(item.row, item.code) for item in updates_13], [(2, "13-code")])
        self.assertEqual(updates_14, [])
        self.assertEqual(stats_14["existing"], 1)

    def test_ftp_download_logs_bytes_and_duration(self):
        class FakeFTP:
            def retrbinary(self, command, callback):
                self.command = command
                callback(b"abc")
                callback(b"de")

        ftp_file = module.FtpFile("/from_etm/13/price.csv")
        with patch.object(module.time, "monotonic", side_effect=[10.0, 12.5]):
            with self.assertLogs(module.logging.getLogger(), level="INFO") as captured:
                content = module.download_ftp_file(FakeFTP(), ftp_file)

        self.assertEqual(content, b"abcde")
        self.assertTrue(any("bytes=5" in line and "duration=2.50s" in line for line in captured.output))

    def test_fetch_ftp_source_retries_with_reconnect_and_backoff(self):
        class FakeFTP:
            def quit(self):
                pass

        ftp_file = module.FtpFile("/from_etm/13/price.csv", modified="20260831031122")
        first = FakeFTP()
        second = FakeFTP()
        with patch.object(module, "FTP_DOWNLOAD_ATTEMPTS", 3), patch.object(
            module, "FTP_DOWNLOAD_BASE_DELAY", 2.0
        ), patch.object(module, "connect_ftp", side_effect=[first, second]) as connect, patch.object(
            module, "list_ftp_files", return_value=[ftp_file]
        ), patch.object(
            module, "download_ftp_file", side_effect=[OSError("EOF"), b"valid csv"]
        ), patch.object(
            module, "validate_ftp_csv", return_value={"source_rows": 1}
        ), patch.object(module, "save_ftp_cache") as save_cache, patch.object(
            module.time, "sleep"
        ) as sleep:
            content, selected = module.fetch_ftp_source("/from_etm/13")

        self.assertEqual(content, b"valid csv")
        self.assertEqual(selected, ftp_file)
        self.assertEqual(connect.call_count, 2)
        sleep.assert_called_once_with(2.0)
        save_cache.assert_called_once_with(ftp_file, b"valid csv")

    def test_invalid_csv_is_never_cached_after_all_download_attempts(self):
        class FakeFTP:
            def quit(self):
                pass

        ftp_file = module.FtpFile("/from_etm/13/price.csv", modified="20260831031122")
        with patch.object(module, "FTP_DOWNLOAD_ATTEMPTS", 3), patch.object(
            module, "FTP_DOWNLOAD_BASE_DELAY", 0
        ), patch.object(module, "connect_ftp", side_effect=[FakeFTP(), FakeFTP(), FakeFTP()]), patch.object(
            module, "list_ftp_files", return_value=[ftp_file]
        ), patch.object(module, "download_ftp_file", return_value=b"broken"), patch.object(
            module, "validate_ftp_csv", side_effect=ValueError("invalid CSV")
        ), patch.object(module, "save_ftp_cache") as save_cache, patch.object(
            module.time, "sleep"
        ):
            with self.assertRaises(RuntimeError):
                module.fetch_ftp_source("/from_etm/13")

        save_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
