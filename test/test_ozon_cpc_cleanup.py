import io
import pathlib
import sys
from unittest.mock import patch
import unittest
import zipfile
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ozon_cpc_cleanup import (
    PERIOD_DAY,
    PERIOD_MONTH,
    PERIOD_WEEK,
    Candidate,
    Metric,
    SheetRow,
    build_candidates,
    build_statistics_payload,
    campaign_budget,
    contiguous_row_groups,
    parse_report,
    parse_report_block,
    period_range,
    rows_for_campaign_batch,
    rows_from_values,
    request_json,
    rotation_slice,
    TokenManager,
    write_sheet_metrics,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.content = b"{}"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class OzonCpcCleanupTests(unittest.TestCase):
    def test_token_manager_refreshes_before_expiry(self):
        with patch(
            "ozon_cpc_cleanup._fetch_token_data",
            side_effect=[
                {"access_token": "token-1", "expires_in": 1800},
                {"access_token": "token-2", "expires_in": 1800},
            ],
        ) as fetch:
            manager = TokenManager(object())
            self.assertEqual(manager.get(), "token-1")
            manager._refresh_at = 0
            self.assertEqual(manager.get(), "token-2")
            self.assertEqual(fetch.call_count, 2)

    def test_request_json_refreshes_once_after_403(self):
        session = FakeSession([
            FakeResponse(403, {"error": "forbidden"}),
            FakeResponse(200, {"ok": True}),
        ])
        with patch(
            "ozon_cpc_cleanup._fetch_token_data",
            side_effect=[
                {"access_token": "expired", "expires_in": 1800},
                {"access_token": "fresh", "expires_in": 1800},
            ],
        ) as fetch:
            manager = TokenManager(session)
            self.assertEqual(request_json(session, "GET", "/api/client/campaign", token=manager), {"ok": True})
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(session.calls), 2)
            self.assertEqual(session.calls[0][2]["headers"]["Authorization"], "Bearer expired")
            self.assertEqual(session.calls[1][2]["headers"]["Authorization"], "Bearer fresh")

    def test_request_json_blocks_after_persistent_403(self):
        session = FakeSession([
            FakeResponse(403, {"error": "forbidden"}),
            FakeResponse(403, {"error": "forbidden"}),
        ])
        with patch(
            "ozon_cpc_cleanup._fetch_token_data",
            side_effect=[
                {"access_token": "token-1", "expires_in": 1800},
                {"access_token": "token-2", "expires_in": 1800},
            ],
        ):
            manager = TokenManager(session)
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                request_json(session, "POST", "/api/client/campaign/1/activate", token=manager)
            self.assertTrue(manager._auth_blocked)

    def test_period_range_uses_moscow_time(self):
        now = datetime.fromisoformat("2026-08-05T12:00:00+03:00")
        day_start, day_end = period_range(PERIOD_DAY, now)
        week_start, week_end = period_range(PERIOD_WEEK, now)
        month_start, month_end = period_range(PERIOD_MONTH, now)
        self.assertEqual((day_start, day_end), ("2026-08-05T00:00:00+03:00", "2026-08-05T23:59:59+03:00"))
        self.assertEqual((week_start, week_end), ("2026-07-30T00:00:00+03:00", "2026-08-05T23:59:59+03:00"))
        self.assertEqual((month_start, month_end), ("2026-08-01T00:00:00+03:00", "2026-08-05T23:59:59+03:00"))

    def test_statistics_payload_uses_documented_rfc3339_fields_and_no_group_by(self):
        payload = build_statistics_payload(
            ["33230388"],
            "2026-08-04T00:00:00+03:00",
            "2026-08-04T23:59:59+03:00",
        )
        self.assertEqual(payload["campaigns"], ["33230388"])
        self.assertEqual(payload["from"], "2026-08-04T00:00:00+03:00")
        self.assertEqual(payload["to"], "2026-08-04T23:59:59+03:00")
        self.assertEqual(payload["groupBy"], "NO_GROUP_BY")
        self.assertNotIn("dateFrom", payload)
        self.assertNotIn("dateTo", payload)
        with self.assertRaises(ValueError):
            build_statistics_payload([], "from", "to")

    def test_parse_report_block_maps_clicks_and_metrics_by_header(self):
        csv_text = (
            ";Кампания 33230388\n"
            "sku;Показы;Клики;CTR, %;Расход, ₽, с НДС;Средняя стоимость клика, ₽;Продано товаров;Добавления в корзину\n"
            "986315608;100;12;12;123,45;10,29;2;4\n"
            "986315608;50;3;6;30;10;1;2\n"
        )
        block = parse_report_block("33230388_24.07.2026.csv", csv_text)
        self.assertEqual(block.campaign_id, "33230388")
        self.assertEqual(block.metrics["986315608"].clicks, 15)
        self.assertEqual(block.metrics["986315608"].impressions, 150)
        self.assertAlmostEqual(block.metrics["986315608"].spend, 153.45)
        self.assertEqual(block.metrics["986315608"].sold, 3)
        self.assertEqual(block.metrics["986315608"].carts, 6)

    def test_parse_report_reads_zip_and_keeps_campaign_sku_key(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr(
                "33230388_24.07.2026.csv",
                "sku;Клики\n986315608;11\n",
            )
        stats = parse_report(content.getvalue(), ["33230388"])
        self.assertEqual(stats[("33230388", "986315608")].clicks, 11)

    def test_parse_report_filters_by_day_range_in_date_grouped_report(self):
        csv_text = (
            "День;sku;Показы;Клики;Расход, ₽, с НДС\n"
            "05.08.2026;986315608;10;1;5\n"
            "06.08.2026;986315608;20;4;10\n"
            "07.08.2026;986315608;30;6;15\n"
            "Всего;;;;;10;21;11;30\n"
        )
        all_block = parse_report_block("33230388.csv", csv_text)
        self.assertEqual(all_block.metrics["986315608"].clicks, 11)
        self.assertEqual(all_block.metrics["986315608"].impressions, 60)
        day09 = parse_report_block(
            "33230388.csv", csv_text, day_from="07.08.2026", day_to="07.08.2026"
        )
        self.assertEqual(day09.metrics["986315608"].clicks, 6)
        week_from = parse_report_block(
            "33230388.csv", csv_text, day_from="06.08.2026", day_to="07.08.2026"
        )
        self.assertEqual(week_from.metrics["986315608"].clicks, 10)

    def test_campaign_budget_uses_explicit_budget_not_weekly_cap(self):
        self.assertEqual(campaign_budget({"budget": "1500", "dailyBudget": "0", "weeklyBudget": "2000000000"}), 1500)
        self.assertEqual(campaign_budget({"budget": "0", "dailyBudget": "250"}), 0)
        self.assertEqual(campaign_budget(None), 0)

    def test_write_sheet_metrics_translates_all_cpc_columns(self):
        class FakeWorksheet:
            def __init__(self):
                self.updates = []

            def update(self, range_name=None, values=None, **kwargs):
                self.updates.append((range_name, values))

        headers = [
            "art", "model", "brand", "pic", "SKU OZON", "CAMPAIN ID", "CAMPAIN NAME",
            "Расход день", "Расход неделя", "Расход месяц",
            "Показы день", "Показы неделя", "Показы месяц",
            "Клики день", "Клики неделя", "Клики месяц",
            "CTR, % месяц", "Средняя стоимость клика месяц", "Продано месяц",
            "ДРР в продвижении месяц", "Бюджет", "Корзины месяц", "Статус",
            "Фильтр клики день", "Фильтр ДРР месяц",
        ]
        values = ["39171-1", "39171", "Stekker", "", "986315608", "33230388"] + [""] * 19
        row = SheetRow(2, "39171-1", "986315608", "33230388", 5, 0, "1", values)
        metrics_by_period = {
            PERIOD_DAY: {("33230388", "986315608"): Metric(clicks=12, impressions=100, spend=123.45)},
            PERIOD_WEEK: {("33230388", "986315608"): Metric(clicks=40, impressions=350, spend=400)},
            PERIOD_MONTH: {
                ("33230388", "986315608"): Metric(
                    clicks=90, impressions=900, ctr=10, average_cpc=8.89, sold=5, drr=12, carts=20, spend=800
                )
            },
        }
        campaigns_by_id = {
            "33230388": {"budget": "1500", "state": "CAMPAIGN_STATE_RUNNING", "title": "Кампания"}
        }
        worksheet = FakeWorksheet()

        write_sheet_metrics(worksheet, headers, [row], metrics_by_period, campaigns_by_id)

        updates = dict(worksheet.updates)
        self.assertEqual(
            set(updates),
            {
                "G2:G2", "H2:H2", "I2:I2", "J2:J2", "K2:K2", "L2:L2", "M2:M2",
                "N2:N2", "O2:O2", "P2:P2", "Q2:Q2", "R2:R2", "S2:S2", "T2:T2",
                "U2:U2", "V2:V2", "W2:W2",
            },
        )
        self.assertEqual(updates["G2:G2"], [["Кампания"]])
        self.assertEqual(updates["H2:H2"], [[123.45]])
        self.assertEqual(updates["I2:I2"], [[400]])
        self.assertEqual(updates["J2:J2"], [[800]])
        self.assertEqual(updates["N2:N2"], [[12]])
        self.assertEqual(updates["Q2:Q2"], [[10]])
        self.assertEqual(updates["T2:T2"], [[12]])
        self.assertEqual(updates["U2:U2"], [[1500]])
        self.assertEqual(updates["V2:V2"], [[20]])
        self.assertEqual(updates["W2:W2"], [["CAMPAIGN_STATE_RUNNING"]])
        self.assertNotIn("A2:Y2", updates)

    def test_incremental_batch_keeps_rows_when_day_metrics_are_empty(self):
        rows = [
            SheetRow(2, "39171-1", "986315608", "33230388", 0, 0, "", []),
            SheetRow(3, "39172-1", "986315609", "33230388", 0, 0, "", []),
            SheetRow(4, "39173-1", "986315610", "33230389", 0, 0, "", []),
        ]

        selected = rows_for_campaign_batch(rows, ["33230388"])

        self.assertEqual([row.row_number for row in selected], [2, 3])

    def test_rotation_slice_selects_sequential_campaigns_and_wraps_cursor(self):
        campaigns = ["c1", "c2", "c3", "c4", "c5"]
        selected, next_index = rotation_slice(campaigns, 3, 2)
        self.assertEqual(selected, ["c4", "c5"])
        self.assertEqual(next_index, 0)

        selected, next_index = rotation_slice(campaigns, next_index, 2)
        self.assertEqual(selected, ["c1", "c2"])
        self.assertEqual(next_index, 2)

    def test_rotation_slice_does_not_duplicate_within_one_run(self):
        campaigns = ["c1", "c2", "c3", "c4", "c5"]
        selected, next_index = rotation_slice(campaigns, 4, 4)
        self.assertEqual(selected, ["c5"])
        self.assertEqual(next_index, 0)

    def test_contiguous_row_groups_prevent_rectangular_range_overwrite(self):
        rows = [
            SheetRow(5, "later", "2", "1", 0, 0, "", []),
            SheetRow(2, "first", "1", "1", 0, 0, "", []),
            SheetRow(4, "gap", "3", "1", 0, 0, "", []),
        ]

        groups = contiguous_row_groups(rows)

        self.assertEqual([[row.row_number for row in group] for group in groups], [[2], [4, 5]])

    def test_write_sheet_metrics_preserves_week_month_when_day_is_empty(self):
        class FakeWorksheet:
            def __init__(self):
                self.updates = []

            def update(self, range_name=None, values=None, **kwargs):
                self.updates.append((range_name, values))

        headers = [
            "CAMPAIN NAME", "Расход день", "Расход неделя", "Расход месяц",
            "Показы день", "Показы неделя", "Показы месяц",
            "Клики день", "Клики неделя", "Клики месяц", "Бюджет", "Статус",
        ]
        row = SheetRow(2, "39171-1", "986315608", "33230388", 0, 0, "", [])
        key = ("33230388", "986315608")
        metrics_by_period = {
            PERIOD_DAY: {},
            PERIOD_WEEK: {key: Metric(spend=400, clicks=40, impressions=350)},
            PERIOD_MONTH: {key: Metric(spend=800, clicks=90, impressions=900)},
        }
        campaigns_by_id = {
            "33230388": {"budget": "1500", "state": "CAMPAIGN_STATE_INACTIVE", "title": "Кампания"}
        }
        worksheet = FakeWorksheet()

        write_sheet_metrics(worksheet, headers, [row], metrics_by_period, campaigns_by_id)

        updates = dict(worksheet.updates)
        self.assertEqual(updates["B2:B2"], [[0.0]])
        self.assertEqual(updates["C2:C2"], [[400]])
        self.assertEqual(updates["D2:D2"], [[800]])
        self.assertEqual(updates["H2:H2"], [[0.0]])
        self.assertEqual(updates["I2:I2"], [[40]])
        self.assertEqual(updates["J2:J2"], [[90]])

    def test_build_candidates_triggers_by_day_clicks_and_month_drr(self):
        rows = [
            SheetRow(2, "39171-1", "986315608", "33230388", 5, 0, "1", []),
            SheetRow(3, "other", "123", "33230388", 5, 0, "1", []),
            SheetRow(4, "third", "777", "33230388", 0, 10, "1", []),
            SheetRow(5, "clean", "999", "33230388", 0, 0, "1", []),
        ]
        metrics_by_period = {
            PERIOD_DAY: {
                ("33230388", "986315608"): Metric(clicks=10),
                ("33230388", "123"): Metric(clicks=12),
                ("33230388", "777"): Metric(clicks=2),
                ("33230388", "999"): Metric(clicks=1),
            },
            PERIOD_MONTH: {
                ("33230388", "777"): Metric(drr=12),
            },
        }
        candidates = build_candidates(rows, metrics_by_period, {"33230388": {"986315608", "123", "777"}})
        self.assertEqual(
            {(item.sku, item.action) for item in candidates},
            {("986315608", "delete"), ("123", "delete"), ("777", "delete")},
        )
        self.assertEqual({item.sku for item in candidates}, {"986315608", "123", "777"})

    def test_build_candidates_skips_row_when_both_filters_zero(self):
        rows = [
            SheetRow(2, "39171-1", "986315608", "33230388", 0, 0, "1", []),
        ]
        metrics_by_period = {
            PERIOD_DAY: {("33230388", "986315608"): Metric(clicks=9999)},
            PERIOD_MONTH: {("33230388", "986315608"): Metric(drr=9999)},
        }
        candidates = build_candidates(rows, metrics_by_period, {"33230388": {"986315608"}})
        self.assertEqual(candidates, [])

    def test_build_candidates_skips_when_sku_not_in_campaign(self):
        rows = [
            SheetRow(2, "a", "111", "33230388", 5, 0, "1", []),
        ]
        metrics_by_period = {
            PERIOD_DAY: {("33230388", "111"): Metric(clicks=10)},
            PERIOD_MONTH: {},
        }
        candidates = build_candidates(rows, metrics_by_period, {"33230388": set()})
        self.assertEqual(candidates[0].action, "skip_not_in_campaign")

    def test_rows_from_values_skips_rows_without_article(self):
        headers = [
            "art", "model", "brand", "pic", "SKU OZON", "CAMPAIN ID", "Фильтр клики день", "Фильтр ДРР месяц",
        ]
        values = [
            headers,
            ["39171-1", "39171", "Stekker", "", "986315608", "33230388", "10", "5"],
            ["", "no-art", "x", "", "123456", "999", "10", "5"],
            ["39172-2", "39172", "Stekker", "", "986315609", "33230389", "", ""],
        ]
        _, rows = rows_from_values(values)
        self.assertEqual([(row.row_number, row.article, row.sku) for row in rows], [
            (2, "39171-1", "986315608"),
            (4, "39172-2", "986315609"),
        ])

    def test_rows_from_values_reads_toggle_column(self):
        headers = [
            "art", "model", "brand", "pic", "SKU OZON", "CAMPAIN ID",
            "Фильтр клики день", "Фильтр ДРР месяц", "Включение/отключение компании",
        ]
        values = [
            headers,
            ["39171-1", "39171", "Stekker", "", "986315608", "33230388", "10", "5", "1"],
            ["39172-2", "39172", "Stekker", "", "986315609", "33230389", "", "", "0"],
            ["39173-3", "39173", "Stekker", "", "986315610", "33230390", "", "", ""],
        ]
        _, rows = rows_from_values(values)
        self.assertEqual([(row.row_number, row.toggle) for row in rows], [(2, "1"), (3, "0"), (4, "")])


if __name__ == "__main__":
    unittest.main()
