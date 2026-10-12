import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import obor_summary_local


class ArticleResolutionTests(unittest.TestCase):
    def test_write_retry_does_not_double_qualify_sheet_ranges(self):
        updates = [{"range": "K1", "values": [["Озон ост"]]}]
        calls = []

        class Worksheet:
            def batch_update(self, payload, raw):
                calls.append(payload[0]["range"])
                payload[0]["range"] = "'ОБОР'!" + payload[0]["range"]
                if len(calls) == 1:
                    raise ConnectionError("response connection lost")
                return {"updated": True}

        def retry(label, operation):
            try:
                return operation()
            except ConnectionError:
                return operation()

        with patch.object(obor_summary_local, "retry_read", retry):
            self.assertEqual(obor_summary_local.write_summary_batch(Worksheet(), updates), {"updated": True})
        self.assertEqual(calls, ["K1", "K1"])
        self.assertEqual(updates[0]["range"], "K1")

    def test_source_map_prefers_exact_nested_article_before_outer_multiplier(self):
        target = "KKM11-009-230-10"
        source_values = {
            "KKM11-009-230-10": 56,
            "KKM11-009-230": 900,
        }

        self.assertEqual(
            obor_summary_local.resolve_source_value(source_values, target), 56
        )

    def test_source_map_keeps_existing_multiplier_family_fallback(self):
        self.assertEqual(
            obor_summary_local.resolve_source_value({"55222": 37}, "55222-10"),
            37,
        )

    def test_wb_base_map_matches_nested_target_article(self):
        target = "KKM11-009-230-10"
        self.assertEqual(
            obor_summary_local.resolve_wb_value(
                {"KKM11-009-230-10-1": 12},
                target,
                {target: 12},
            ),
            12,
        )


if __name__ == "__main__":
    unittest.main()
