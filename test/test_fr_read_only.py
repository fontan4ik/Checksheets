import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import gsheets_utils


class FakeWorksheet:
    title = "StreamSupps"
    row_count = 10

    def __init__(self):
        self.cleared = []
        self.updated = []

    def row_values(self, row):
        self.assert_first_row(row)
        return ["A", "B", "FR", "RS SMR"]

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)

    def update(self, range_label, values):
        self.updated.append((range_label, values))

    def assert_first_row(self, row):
        if row != 1:
            raise AssertionError(f"unexpected row read: {row}")


class FrReadOnlyTests(unittest.TestCase):
    def test_update_by_header_rejects_fr(self):
        worksheet = FakeWorksheet()
        with self.assertRaisesRegex(PermissionError, "read-only"):
            gsheets_utils.update_column_by_header(worksheet, "FR", [[1]])
        self.assertEqual([], worksheet.updated)

    def test_numeric_update_rejects_column_with_fr_header(self):
        worksheet = FakeWorksheet()
        with self.assertRaisesRegex(PermissionError, "read-only"):
            gsheets_utils.update_column(worksheet, 3, [[1]])
        self.assertEqual([], worksheet.updated)

    def test_numeric_clear_rejects_column_with_fr_header(self):
        worksheet = FakeWorksheet()
        with self.assertRaisesRegex(PermissionError, "read-only"):
            gsheets_utils.clear_column_at_index(worksheet, 3)
        self.assertEqual([], worksheet.cleared)

    def test_other_column_remains_writable(self):
        worksheet = FakeWorksheet()
        gsheets_utils.update_column(worksheet, 4, [[7]])
        self.assertEqual([("D2:D2", [[7]])], worksheet.updated)


if __name__ == "__main__":
    unittest.main()
