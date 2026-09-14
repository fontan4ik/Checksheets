import os
import unittest
from unittest import mock


with mock.patch.dict(os.environ, {"ARLIGHT_MIN_API_ITEMS": "2"}):
    import arlight_sync_local


class ParsePricePayloadTests(unittest.TestCase):
    def test_parses_integer_and_fractional_stock(self):
        payload = {
            "errors": [],
            "data": {
                "price": [
                    {"article": "A-1", "stock": 12.0},
                    {"article": "A-2", "stock": 2.5},
                ]
            },
        }

        self.assertEqual(
            arlight_sync_local.parse_price_payload(payload),
            {"A-1": 12, "A-2": 2.5},
        )

    def test_rejects_conflicting_duplicate_articles(self):
        payload = {
            "errors": [],
            "data": {
                "price": [
                    {"article": "A-1", "stock": 12},
                    {"article": "A-1", "stock": 10},
                ]
            },
        }

        with self.assertRaisesRegex(ValueError, "conflicting stock"):
            arlight_sync_local.parse_price_payload(payload)

    def test_rejects_negative_stock(self):
        payload = {
            "errors": [],
            "data": {
                "price": [
                    {"article": "A-1", "stock": -1},
                    {"article": "A-2", "stock": 2},
                ]
            },
        }

        with self.assertRaisesRegex(ValueError, "Invalid Arlight stock"):
            arlight_sync_local.parse_price_payload(payload)


class BuildStockValuesTests(unittest.TestCase):
    def test_preserves_row_alignment_and_zeros_missing_articles(self):
        values, stats = arlight_sync_local.build_stock_values(
            ["A-1", "", " A-2 ", "OLD"],
            {"A-1": 10, "A-2": 0},
        )

        self.assertEqual(values, [[10], [""], [0], [0]])
        self.assertEqual(stats.sheet_rows, 4)
        self.assertEqual(stats.nonempty_articles, 3)
        self.assertEqual(stats.matched, 2)
        self.assertEqual(stats.not_found, 1)
        self.assertEqual(stats.positive_stock, 1)
        self.assertEqual(stats.zero_stock, 2)
        self.assertAlmostEqual(stats.match_rate, 2 / 3)


if __name__ == "__main__":
    unittest.main()
