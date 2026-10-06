import argparse
import pathlib
import sys
import tempfile
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
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.object(creator, "CREATION_STATE_FILE", pathlib.Path(self.directory.name) / "state.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def creation_values(self):
        return [
            ["art", "SKU OZON", "CAMPAIN ID", "Включение/отключение компании",
             "Клики день", "Фильтр клики день", "ДРР в продвижении месяц", "Фильтр ДРР месяц"],
            ["A", "101", "", "1", "0", "3", "0", "5"],
        ]

    def test_failed_product_addition_resumes_same_campaign_next_run(self):
        worksheet = FakeWorksheet(self.creation_values())
        with (
            patch.object(creator.gsheets_utils, "get_worksheet", return_value=worksheet),
            patch.object(creator, "create_session"), patch.object(creator, "TokenManager"),
            patch.object(creator, "get_campaigns", return_value=[]),
            patch.object(creator, "get_campaign_products", return_value=set()),
            patch.object(creator, "create_cpc_campaign", return_value={"campaignId": "1001"}) as create,
            patch.object(creator, "add_sku_to_campaign", side_effect=[RuntimeError("HTTP 429"), RuntimeError("HTTP 429"), RuntimeError("HTTP 429"), {}]) as add,
            patch.object(creator.time, "sleep"), patch.object(creator, "activate_campaign") as activate,
        ):
            self.assertEqual(creator.run(args(skip_analytics=True)), 1)
            self.assertEqual(creator.load_creation_state(), {"A:101": "1001"})
            activate.assert_not_called()
            self.assertEqual(creator.run(args(skip_analytics=True)), 0)
            self.assertEqual(create.call_count, 1)
            self.assertEqual(add.call_count, 4)
            activate.assert_called_once()
            self.assertEqual(worksheet.batch_updates[0][0], [{"range": "C2", "values": [["1001"]]}])

    def test_recovers_existing_empty_campaign_without_creating_another(self):
        campaign = {"id": "1001", "title": "я A", "state": "CAMPAIGN_STATE_INACTIVE", "PaymentType": "CPC"}
        with patch.object(creator, "get_campaign_products", return_value=set()):
            self.assertEqual(creator.resume_campaign(None, None, creator.CreationRow(2, "A", "101"), [campaign], set()), "1001")
            self.assertEqual(creator.resume_campaign(None, None, creator.CreationRow(2, "A", "101"), [campaign], {"1001"}), "")
        with patch.object(creator, "get_campaign_products", return_value={"102"}):
            self.assertEqual(creator.resume_campaign(None, None, creator.CreationRow(2, "A", "101"), [campaign], set()), "")

    def test_creation_activation_respects_toggle_and_filters(self):
        values = self.creation_values()
        row = creator.CreationRow(2, "A", "101")
        self.assertTrue(creator.should_activate(values, row))
        values[1][4] = "3"
        self.assertFalse(creator.should_activate(values, row))
        values[1][4] = "0"
        values[1][6] = "5"
        self.assertFalse(creator.should_activate(values, row))
        values[1][6] = "0"
        values[1][3] = "0"
        self.assertFalse(creator.should_activate(values, row))

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
