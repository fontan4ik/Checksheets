import argparse
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import create_ozon_cpc_campaigns as creator


class FakeWorksheet:
    def __init__(self, values):
        self.values = values
        self.batch_updates = []

    def get_all_values(self):
        return self.values

    def batch_update(self, updates, raw=True):
        self.batch_updates.append((updates, raw))


def args(**overrides):
    values = {
        "limit": 0,
        "skip_sheet_write": False,
        "skip_analytics": False,
        "analytics_write_sheet": True,
        "analytics_stop_on_filter": True,
        "analytics_rotation_batches": 2,
        "lock_timeout": 0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class CreateOzonCpcCampaignsTests(unittest.TestCase):
    def test_pending_rows_require_empty_campaign_id(self):
        values = [
            ["art", "SKU OZON", "CAMPAIN ID"],
            ["A", "101", ""],
            ["B", "102", "999"],
            ["C", "103"],
        ]
        rows, column = creator.pending_creation_rows(values)
        self.assertEqual(column, 2)
        self.assertEqual([row.row_number for row in rows], [2, 4])

    def test_sparse_campaign_ids_are_written_to_exact_rows(self):
        worksheet = FakeWorksheet([])
        created = [
            (creator.CreationRow(2, "A", "101"), "1001"),
            (creator.CreationRow(4, "C", "103"), "1003"),
        ]
        creator.write_created_campaign_ids(worksheet, "F", created)
        self.assertEqual(
            worksheet.batch_updates[0],
            ([{"range": "F2", "values": [["1001"]]}, {"range": "F4", "values": [["1003"]]}], True),
        )

    def test_no_pending_rows_still_runs_scheduled_analytics(self):
        worksheet = FakeWorksheet([
            ["art", "SKU OZON", "CAMPAIN ID"],
            ["A", "101", "1001"],
        ])
        with (
            patch.object(creator.gsheets_utils, "get_worksheet", return_value=worksheet),
            patch.object(creator.ozon_cpc_cleanup, "run", return_value=0) as analytics,
        ):
            self.assertEqual(creator.run(args()), 0)
        analytics_args = analytics.call_args.args[0]
        self.assertTrue(analytics_args.write_sheet)
        self.assertTrue(analytics_args.stop_on_filter)
        self.assertEqual(analytics_args.rotation_batches, 2)


if __name__ == "__main__":
    unittest.main()
