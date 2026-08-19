import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "sync_etm_codes.py"
spec = importlib.util.spec_from_file_location("sync_etm_codes", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SyncEtmCodesTests(unittest.TestCase):
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

    def test_load_mapping_rejects_conflicting_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.csv"
            path.write_text(
                "Код ЭТМ;Артикул;Производитель\n"
                "7;00123;Arlight\n"
                "8;00123;arlight\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                module.load_csv_mapping(path)

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
            {"model": 2, "brand": 3, "etm_code": 4},
            {("00123", "arlight"): "0007"},
        )

        self.assertEqual([(u.row, u.code) for u in updates], [(2, "0007")])
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(stats["unmatched"], 2)

    def test_a1_ranges_group_adjacent_rows(self):
        updates = [
            module.Update(2, "10", "a", "b"),
            module.Update(3, "11", "a", "b"),
            module.Update(7, "12", "a", "b"),
        ]
        self.assertEqual(
            module.a1_ranges(updates, 23),
            [("W2:W3", [["10"], ["11"]]), ("W7:W7", [["12"]])],
        )


if __name__ == "__main__":
    unittest.main()
